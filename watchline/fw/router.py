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
# select_rules
# ---------------------------------------------------------------------------

def select_rules(state: WatchlineState) -> dict:
    """
    Map intent to handler, resolve entity, prepare traversal params.
    No LLM, no graph queries here (entity resolution is graph access
    but is treated as infrastructure, not reasoning).
    """
    intent       = state["intent"]
    entity_type  = intent.get("entity_type", "Unknown")
    intent_cat   = intent.get("intent_category", "General")

    # Look up handler — fall back to General if category is unrecognised
    handler = REGISTRY.get(intent_cat) or REGISTRY["General"]

    # Stub handlers have no Cypher — return not_supported immediately
    if not handler.get_cypher():
        return {
            "needs_clarification": False,
            "traversal_results": {
                **handler.not_supported_response(),
                "handler":        handler,
                "traversal_type": handler.traversal_key(),
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
            "handler":         handler,
            "traversal_type":  handler.traversal_key(),
            "params":          handler.get_params(intent),
            "resolved_entity": resolved_entity,
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
