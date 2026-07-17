"""
watchline/fw/router.py

LangGraph nodes: select_rules, execute_traversal, request_clarification
Routing functions: route_after_rules, route_after_traversal

select_rules:
  - Looks up the IntentHandler from the registry
  - Resolves the entity (BBL or actor canonical_id)
  - Injects resolved identifiers into traversal_results for execute_traversal

execute_traversal:
  - Runs the handler's Cypher query
  - Calls handler.evaluate() for rule-based intents
  - Attaches rule_evaluation to traversal_results
"""

from watchline.fw.connections import neo4j_query
from watchline.fw.intents import REGISTRY
from watchline.fw.resolver import resolve_building, resolve_actor
from watchline.fw.state import WatchlineState


# ---------------------------------------------------------------------------
# Intent validation (Charter Principle 17)
#
# "Every conditional transition must be justified by a defined Rule or
# Canonical Question in the ontology." identify_intent's LLM call chooses
# an intent_category with no graph access at all (see intent.py). This is
# the one place that classification is checked against a real ontology
# object before the pipeline trusts it. See
# scripts/04_seed_investigative_intents.cypher for the seed data.
# ---------------------------------------------------------------------------

def _validate_intent(intent_cat: str) -> str | None:
    """
    Look up intent_cat against InvestigativeIntent.name in the graph.

    Returns the matching intent_id, or None if no node was found. None is
    expected for 'General' (a catch-all fallback, not a named investigative
    question — no InvestigativeIntent node is seeded for it). For any other
    category, None means either the LLM classified into a category outside
    the ontology, or REGISTRY and the seeded InvestigativeIntent nodes have
    drifted apart — both are worth surfacing, not silently swallowing.
    """
    if intent_cat == "General":
        return None
    results = neo4j_query(
        "MATCH (ii:InvestigativeIntent {name: $name}) RETURN ii.intent_id AS intent_id",
        params={"name": intent_cat},
    )
    return results[0]["intent_id"] if results else None


# ---------------------------------------------------------------------------
# select_rules
# ---------------------------------------------------------------------------

def select_rules(state: WatchlineState) -> dict:
    """
    Map intent to handler, resolve entity, prepare traversal params.
    No LLM here. Entity resolution and the InvestigativeIntent check below
    are graph access but are treated as infrastructure, not reasoning.
    """
    intent       = state["intent"]
    entity_type  = intent.get("entity_type", "Unknown")
    intent_cat   = intent.get("intent_category", "General")

    justified_by_intent_id = _validate_intent(intent_cat)
    if justified_by_intent_id is None and intent_cat != "General":
        print(
            f"WARNING: intent_category '{intent_cat}' has no matching "
            f"InvestigativeIntent node in the graph — routing is proceeding "
            f"on LLM classification alone, unjustified by the ontology. "
            f"Check scripts/04_seed_investigative_intents.cypher against "
            f"REGISTRY in watchline/fw/intents/__init__.py for drift."
        )

    # Look up handler — fall back to General if category is unrecognised
    handler = REGISTRY.get(intent_cat) or REGISTRY["General"]

    # Stub handlers have no Cypher — return not_supported immediately
    if not handler.get_cypher():
        return {
            "needs_clarification": False,
            "traversal_results": {
                **handler.not_supported_response(),
                "handler":                handler,
                "traversal_type":         handler.traversal_key(),
                "justified_by_intent_id": justified_by_intent_id,
            },
        }

    # WorstFirst is a dataset-level query — no entity needed
    if intent_cat == "WorstFirst":
        return {
            "needs_clarification": False,
            "traversal_results": {
                "handler":                handler,
                "traversal_type":         handler.traversal_key(),
                "params":                 {},
                "resolved_entity":        None,
                "justified_by_intent_id": justified_by_intent_id,
            },
        }

    # GeographicConcentration is a geographic query — no named entity needed;
    # passes optional borough from the intent extractor's borough field
    if intent_cat == "GeographicConcentration":
        return {
            "needs_clarification": False,
            "traversal_results": {
                "handler":                handler,
                "traversal_type":         handler.traversal_key(),
                "params":                 handler.get_params(intent),
                "resolved_entity":        None,
                "justified_by_intent_id": justified_by_intent_id,
            },
        }

    # Cannot proceed without any entity signal
    if entity_type == "Unknown" or not any([
        intent.get("address"),
        intent.get("bbl"),
        intent.get("actor_name"),
    ]):
        return {
            "needs_clarification": True,
            "clarification_request": (
                "I wasn't able to identify a specific building or landlord in your "
                "question. Could you provide a street address (e.g. '530 East 169th "
                "Street, Bronx') or a landlord name?"
            ),
            "traversal_results": {},
        }

    # Resolve entity and inject into intent for handler.get_params()
    resolved_entity = None

    if handler.entity_class == "building":
        record, error = resolve_building(intent)
        if error:
            return {
                "needs_clarification": True,
                "clarification_request": error,
                "traversal_results": {},
            }
        intent = {**intent, "bbl": record["bbl"]}
        resolved_entity = record

    elif handler.entity_class == "actor":
        record, error = resolve_actor(intent)
        if error:
            return {
                "needs_clarification": True,
                "clarification_request": error,
                "traversal_results": {},
            }
        intent = {**intent, "canonical_id": record["canonical_id"]}
        resolved_entity = record

    return {
        "needs_clarification": False,
        "traversal_results": {
            "handler":                handler,
            "traversal_type":         handler.traversal_key(),
            "params":                 handler.get_params(intent),
            "resolved_entity":        resolved_entity,
            "justified_by_intent_id": justified_by_intent_id,
        },
    }


# ---------------------------------------------------------------------------
# execute_traversal
# ---------------------------------------------------------------------------

def execute_traversal(state: WatchlineState) -> dict:
    """Run the handler's Cypher and apply rule evaluation if defined."""
    if state.get("needs_clarification"):
        return {}

    tr      = state["traversal_results"]
    handler = tr.get("handler")

    if not handler:
        return {"error": "No handler found in traversal_results."}

    # Stub — already handled in select_rules, pass through
    if tr.get("not_supported"):
        return {"traversal_results": tr}

    cypher = handler.get_cypher()
    params = tr.get("params", {})

    try:
        results = neo4j_query(cypher, params=params)
    except Exception as e:
        return {"error": f"Graph traversal failed: {str(e)}"}

    tr["raw_results"] = results

    # Rule evaluation (returns None for pure data-retrieval intents)
    rule_eval = handler.evaluate(results)
    if rule_eval is not None:
        tr["rule_evaluation"] = rule_eval

    return {"traversal_results": tr}


# ---------------------------------------------------------------------------
# request_clarification
# ---------------------------------------------------------------------------

def request_clarification(state: WatchlineState) -> dict:
    return {
        "answer": state.get(
            "clarification_request",
            "Could you clarify your question?",
        )
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_rules(state: WatchlineState) -> str:
    if state.get("needs_clarification"):
        return "request_clarification"
    return "execute_traversal"


def route_after_traversal(state: WatchlineState) -> str:
    if state.get("needs_clarification"):
        return "request_clarification"
    return "present_results"
