"""
Watchline NYC -- AI Query Layer
watchline/agent/pipeline.py

A LangGraph pipeline that translates plain-language investigative questions
into evidence-backed answers grounded in the Watchline knowledge graph.

Architecture (Charter Principle 17: AI as orchestrator, not reasoner):
  The LLM identifies intent and narrates results.
  The graph retrieves evidence and evaluates rules.
  Claims are never produced by the LLM -- only by defined Rules.

Pipeline nodes:
  identify_intent     -- LLM extracts entity and investigative intent
  select_rules        -- Logic maps intent to Cypher traversal patterns
  execute_traversal   -- Runs Cypher against Neo4j, returns raw graph data
  present_results     -- LLM narrates graph data with Rule citations
  request_clarification -- Fires when entity cannot be resolved

Usage:
  from watchline.agent.pipeline import build_pipeline

  graph = build_pipeline()
  result = graph.invoke({"question": "Tell me about 530 East 169th Street Bronx"})
  print(result["answer"])
"""

import os
from typing import Optional
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from neo4j import GraphDatabase
from langgraph.graph import END, START, StateGraph

load_dotenv()

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class WatchlineState(TypedDict):
    question:               str
    intent:                 dict           # entity type, identifiers, intent category
    traversal_results:      dict           # raw data returned from Neo4j
    answer:                 str            # final plain-language answer
    needs_clarification:    bool           # routing flag
    clarification_request:  str            # what to ask the user
    error:                  Optional[str]  # pipeline error message


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=2048,
    )


def _normalize_address(address: str) -> str:
    """
    Normalize a street address for fuzzy matching against the graph.
    Strips ordinal suffixes (1st->1, 2nd->2, 169th->169) and uppercases.
    Graph addresses are stored as '530 EAST 169 STREET' not '530 East 169th Street'.
    """
    import re
    if not address:
        return address
    # Strip ordinal suffixes: 1st, 2nd, 3rd, 4th..169th etc.
    normalized = re.sub(r'(\d+)(st|nd|rd|th)\b', r'\1', address, flags=re.IGNORECASE)
    return normalized.upper().strip()


def neo4j_query(cypher: str, params: dict = None) -> list:
    """Run a read-only Cypher query and return results as a list of dicts."""
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    try:
        result = driver.execute_query(cypher, parameters_=params or {}, database_=database)
        return [dict(record) for record in result.records]
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Node 1: identify_intent
# The LLM reads the question and returns structured intent.
# No graph access here. Output is a dict with:
#   entity_type:     Building | Actor | Network | Unknown
#   entity_raw:      The raw entity string from the question
#   bbl:             10-digit BBL if resolvable from question
#   address:         Street address if mentioned
#   borough:         Borough if mentioned
#   actor_name:      Landlord/owner name if mentioned
#   intent_category: EnforcementHistory | Ownership | Portfolio |
#                    PHC | ECB | Litigations | RentStabilization | General
# ---------------------------------------------------------------------------

INTENT_SYSTEM_PROMPT = """You are the intent extraction component of Watchline NYC,
an evidence-based housing accountability system. Your only job is to identify:
1. What entity the user is asking about (a building address, a landlord name,
   or an ownership network)
2. What investigative question they are asking

Respond ONLY with a JSON object. No explanation, no preamble, no markdown fences.

JSON schema:
{
  "entity_type": "Building" | "Actor" | "Network" | "Unknown",
  "entity_raw": "<the exact entity string from the question>",
  "address": "<street address if mentioned, else null>",
  "borough": "<borough name if mentioned, else null>",
  "bbl": "<10-digit BBL if user provided it directly, else null>",
  "actor_name": "<landlord or owner name if mentioned, else null>",
  "intent_category": "EnforcementHistory" | "Ownership" | "Portfolio" |
                     "PHC" | "ECB" | "Litigations" | "RentStabilization" | "General",
  "confidence": "High" | "Medium" | "Low"
}

Intent category definitions:
- EnforcementHistory: all violations, judgments, litigations for a building
- Ownership: who owns or controls a building
- Portfolio: what buildings does a landlord/network control
- PHC: persistent hazardous conditions (Class C violations)
- ECB: OATH/ECB enforcement judgments and outstanding balances
- Litigations: HPD housing court cases
- RentStabilization: rent-stabilized unit counts and deregulation
- General: anything else about a building or landlord
"""


def identify_intent(state: WatchlineState) -> dict:
    """Extract structured intent from the user's question."""
    import json

    llm = get_llm()
    response = llm.invoke([
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user",   "content": state["question"]},
    ])

    try:
        text = response.content
        # Strip markdown fences if model added them
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        intent = json.loads(text.strip())
    except Exception as e:
        intent = {
            "entity_type": "Unknown",
            "entity_raw": state["question"],
            "address": None,
            "borough": None,
            "bbl": None,
            "actor_name": None,
            "intent_category": "General",
            "confidence": "Low",
        }

    return {"intent": intent, "needs_clarification": False, "error": None}


# ---------------------------------------------------------------------------
# Node 2: select_rules
# Pure logic -- no LLM, no graph. Maps intent to traversal type.
# Sets traversal_results["traversal_type"] and ["params"] for
# execute_traversal to use.
# ---------------------------------------------------------------------------

def select_rules(state: WatchlineState) -> dict:
    """Map intent to traversal type and parameters. No LLM, no graph."""
    intent = state["intent"]
    entity_type = intent.get("entity_type", "Unknown")
    intent_cat = intent.get("intent_category", "General")

    # Cannot proceed without a resolvable entity
    if entity_type == "Unknown" or (
        not intent.get("address") and
        not intent.get("bbl") and
        not intent.get("actor_name")
    ):
        return {
            "needs_clarification": True,
            "clarification_request": (
                "I wasn't able to identify a specific building or landlord in your "
                "question. Could you provide a street address (e.g. '530 East 169th "
                "Street, Bronx') or a landlord name?"
            ),
            "traversal_results": {},
        }

    # Map to traversal type
    if entity_type == "Building":
        if intent_cat == "PHC":
            traversal_type = "building_phc"
        elif intent_cat == "ECB":
            traversal_type = "building_ecb"
        elif intent_cat == "Litigations":
            traversal_type = "building_litigations"
        elif intent_cat == "RentStabilization":
            traversal_type = "building_rentstab"
        elif intent_cat == "Ownership":
            traversal_type = "building_ownership"
        else:
            traversal_type = "building_summary"  # full enforcement summary
    elif entity_type in ("Actor", "Network"):
        if intent_cat == "Portfolio":
            traversal_type = "actor_portfolio"
        elif intent_cat == "PHC":
            traversal_type = "actor_phc"
        else:
            traversal_type = "actor_summary"
    else:
        traversal_type = "building_summary"

    return {
        "needs_clarification": False,
        "traversal_results": {
            "traversal_type": traversal_type,
            "params": {
                "address":    intent.get("address"),
                "borough":    intent.get("borough"),
                "bbl":        intent.get("bbl"),
                "actor_name": intent.get("actor_name"),
            },
        },
    }


# ---------------------------------------------------------------------------
# Node 3: execute_traversal
# Runs Cypher against Neo4j. Returns raw graph data.
# No LLM here. All reasoning about what is true lives in the graph.
# ---------------------------------------------------------------------------

# --- Building lookup helper ---

BUILDING_LOOKUP_CYPHER = """
MATCH (bld:Building)
WHERE ($bbl IS NOT NULL AND bld.bbl = $bbl)
   OR ($address IS NOT NULL AND $borough IS NOT NULL
       AND (toLower(bld.address) CONTAINS toLower($address)
            OR toLower($address) CONTAINS toLower(bld.address))
       AND bld.borough = $borough)
   OR ($address IS NOT NULL AND $borough IS NULL
       AND (toLower(bld.address) CONTAINS toLower($address)
            OR toLower($address) CONTAINS toLower(bld.address)))
RETURN bld.bbl AS bbl, bld.address AS address, bld.borough AS borough,
       bld.residential_units AS units,
       bld.rs_units_current AS rs_units,
       bld.rs_deregulating AS rs_deregulating
LIMIT 1
"""

BUILDING_PHC_CYPHER = """
MATCH (bld:Building {bbl: $bbl})-[:SUBJECT_OF]->(c:Claim)
WHERE c.interpretive_concept = 'PersistentHazardousConditions'
  AND c.superseded_by IS NULL
MATCH (c)-[:SUPPORTED_BY]->(ev:Evidence)
MATCH (c)-[:PRODUCED_BY]->(r:Rule)
RETURN
  bld.address AS address,
  bld.borough AS borough,
  c.claim_text AS claim_text,
  c.interpretive_status AS interpretive_status,
  ev.summary AS evidence_summary,
  r.name AS rule_name,
  r.rule_id AS rule_id,
  r.authority AS rule_authority,
  r.threshold_description AS threshold_description,
  r.falsification_conditions AS falsification_conditions
LIMIT 1
"""

BUILDING_ECB_CYPHER = """
MATCH (bld:Building {bbl: $bbl})-[:HAS_EVENT]->(e:Event {source_name: 'ECB'})
WHERE e.status = 'Active' AND e.balance_due > 0
WITH bld, e
ORDER BY e.balance_due DESC
WITH bld,
     count(e) AS active_judgments,
     sum(e.balance_due) AS total_balance_due,
     sum(e.penalty_imposed) AS total_penalties,
     collect(e.infraction_codes)[0..3] AS sample_infractions
RETURN
  bld.address AS address,
  bld.borough AS borough,
  active_judgments,
  total_balance_due,
  total_penalties,
  sample_infractions
LIMIT 1
"""

BUILDING_LITIGATIONS_CYPHER = """
MATCH (bld:Building {bbl: $bbl})-[:HAS_EVENT]->(e:Event {source_name: 'HPD-Litigations'})
WITH bld, e
ORDER BY e.event_date DESC
WITH bld,
     count(e) AS total_cases,
     count(CASE WHEN e.status = 'Pending' THEN 1 END) AS pending_cases,
     count(CASE WHEN e.is_harassment_finding = true THEN 1 END) AS harassment_findings,
     collect(CASE WHEN e.is_harassment_finding = true
             THEN {finding: e.finding_of_harassment,
                   date: toString(e.finding_date),
                   respondent: e.respondent}
             END)[0..3] AS harassment_details,
     count(CASE WHEN e.open_judgement = true THEN 1 END) AS open_judgements
RETURN
  bld.address AS address,
  bld.borough AS borough,
  total_cases,
  pending_cases,
  harassment_findings,
  harassment_details,
  open_judgements
LIMIT 1
"""

BUILDING_RENTSTAB_CYPHER = """
MATCH (bld:Building {bbl: $bbl})
WHERE bld.rs_units_2018 IS NOT NULL OR bld.rs_units_current IS NOT NULL
RETURN
  bld.address AS address,
  bld.borough AS borough,
  bld.rs_units_2018 AS units_2018,
  bld.rs_units_2019 AS units_2019,
  bld.rs_units_2020 AS units_2020,
  bld.rs_units_2021 AS units_2021,
  bld.rs_units_2022 AS units_2022,
  bld.rs_units_2023 AS units_2023,
  bld.rs_units_current AS units_current,
  bld.rs_units_change AS units_change,
  bld.rs_deregulating AS deregulating,
  bld.rs_pdfsoa_2023 AS pdfsoa_2023
LIMIT 1
"""

BUILDING_OWNERSHIP_CYPHER = """
MATCH (bld:Building {bbl: $bbl})
OPTIONAL MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})
      -[:INVOLVES_BUILDING]->(bld)
OPTIONAL MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
OPTIONAL MATCH (a)-[:SUBJECT_OF]->(pbc:Claim)
WHERE pbc.interpretive_concept = 'ProbableBeneficialControl'
  AND pbc.superseded_by IS NULL
RETURN
  bld.address AS address,
  bld.borough AS borough,
  a.display_name AS network_name,
  a.resolution_confidence AS confidence,
  a.actor_type AS actor_type,
  pbc.claim_text AS pbc_claim_text,
  rel.basis AS relationship_basis
LIMIT 1
"""

BUILDING_SUMMARY_CYPHER = """
MATCH (bld:Building {bbl: $bbl})
// PHC claim
OPTIONAL MATCH (bld)-[:SUBJECT_OF]->(phc:Claim)
WHERE phc.interpretive_concept = 'PersistentHazardousConditions'
  AND phc.superseded_by IS NULL
OPTIONAL MATCH (phc)-[:SUPPORTED_BY]->(phc_ev:Evidence)
// Ownership
OPTIONAL MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})
      -[:INVOLVES_BUILDING]->(bld)
OPTIONAL MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
// Violation counts
OPTIONAL MATCH (bld)-[:HAS_EVENT]->(hpd_open:Event)
WHERE hpd_open.source_name = 'HPD'
  AND hpd_open.status = 'Open'
  AND hpd_open.violation_class = 'C'
// ECB outstanding
OPTIONAL MATCH (bld)-[:HAS_EVENT]->(ecb:Event)
WHERE ecb.source_name = 'ECB'
  AND ecb.status = 'Active'
  AND ecb.balance_due > 0
RETURN
  bld.address AS address,
  bld.borough AS borough,
  bld.residential_units AS residential_units,
  bld.rs_units_current AS rs_units,
  bld.rs_deregulating AS rs_deregulating,
  count(DISTINCT hpd_open) AS open_c_violations,
  count(DISTINCT ecb) AS active_ecb_judgments,
  sum(DISTINCT ecb.balance_due) AS ecb_balance_due,
  phc.claim_text AS phc_claim,
  phc.interpretive_status AS phc_status,
  phc_ev.summary AS phc_evidence,
  a.display_name AS network_name,
  a.resolution_confidence AS network_confidence
LIMIT 1
"""

ACTOR_PORTFOLIO_CYPHER = """
MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
WHERE toLower(a.display_name) CONTAINS toLower($actor_name)
WITH a LIMIT 1
MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})
      -[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(bld:Building)
OPTIONAL MATCH (bld)-[:SUBJECT_OF]->(phc:Claim)
WHERE phc.interpretive_concept = 'PersistentHazardousConditions'
  AND phc.superseded_by IS NULL
OPTIONAL MATCH (phc)-[:SUPPORTED_BY]->(phc_ev:Evidence)
WITH a,
     count(DISTINCT bld) AS total_buildings,
     count(DISTINCT phc) AS phc_buildings,
     collect(DISTINCT bld.borough) AS boroughs,
     collect({
       address: bld.address,
       borough: bld.borough,
       phc: phc_ev.summary
     })[0..10] AS sample_buildings
RETURN
  a.display_name AS network_name,
  a.resolution_confidence AS confidence,
  total_buildings,
  phc_buildings,
  boroughs,
  sample_buildings
LIMIT 1
"""

ACTOR_PHC_CYPHER = """
MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
WHERE toLower(a.display_name) CONTAINS toLower($actor_name)
WITH a LIMIT 1
MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})
      -[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(bld:Building)
MATCH (bld)-[:SUBJECT_OF]->(phc:Claim)
WHERE phc.interpretive_concept = 'PersistentHazardousConditions'
  AND phc.superseded_by IS NULL
MATCH (phc)-[:SUPPORTED_BY]->(ev:Evidence)
MATCH (phc)-[:PRODUCED_BY]->(r:Rule)
WITH a, bld, phc, ev, r
ORDER BY toInteger(split(ev.summary, ' ')[0]) DESC
WITH a,
     count(bld) AS phc_count,
     collect({
       address: bld.address,
       borough: bld.borough,
       summary: ev.summary
     })[0..10] AS worst_buildings,
     r.name AS rule_name,
     r.rule_id AS rule_id,
     r.threshold_description AS threshold
RETURN
  a.display_name AS network_name,
  a.resolution_confidence AS confidence,
  phc_count,
  worst_buildings,
  rule_name,
  rule_id,
  threshold
LIMIT 1
"""

ACTOR_SUMMARY_CYPHER = """
MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
WHERE toLower(a.display_name) CONTAINS toLower($actor_name)
WITH a LIMIT 1
MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})
      -[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(bld:Building)
OPTIONAL MATCH (bld)-[:SUBJECT_OF]->(phc:Claim)
WHERE phc.interpretive_concept = 'PersistentHazardousConditions'
  AND phc.superseded_by IS NULL
OPTIONAL MATCH (bld)-[:HAS_EVENT]->(ecb:Event)
WHERE ecb.source_name = 'ECB' AND ecb.status = 'Active' AND ecb.balance_due > 0
WITH a,
     count(DISTINCT bld) AS total_buildings,
     count(DISTINCT phc) AS phc_buildings,
     sum(ecb.balance_due) AS total_ecb_balance,
     collect(DISTINCT bld.borough) AS boroughs
RETURN
  a.display_name AS network_name,
  a.resolution_confidence AS confidence,
  total_buildings,
  phc_buildings,
  total_ecb_balance,
  boroughs
LIMIT 1
"""

TRAVERSAL_MAP = {
    "building_phc":        (BUILDING_PHC_CYPHER,       "building"),
    "building_ecb":        (BUILDING_ECB_CYPHER,        "building"),
    "building_litigations":(BUILDING_LITIGATIONS_CYPHER,"building"),
    "building_rentstab":   (BUILDING_RENTSTAB_CYPHER,   "building"),
    "building_ownership":  (BUILDING_OWNERSHIP_CYPHER,  "building"),
    "building_summary":    (BUILDING_SUMMARY_CYPHER,    "building"),
    "actor_portfolio":     (ACTOR_PORTFOLIO_CYPHER,     "actor"),
    "actor_phc":           (ACTOR_PHC_CYPHER,           "actor"),
    "actor_summary":       (ACTOR_SUMMARY_CYPHER,       "actor"),
}


def execute_traversal(state: WatchlineState) -> dict:
    """Run Cypher against Neo4j and return raw graph data."""
    if state.get("needs_clarification"):
        return {}

    tr = state["traversal_results"]
    traversal_type = tr.get("traversal_type")
    params = tr.get("params", {})

    if not traversal_type:
        return {"error": "No traversal type selected."}

    cypher, entity_class = TRAVERSAL_MAP.get(traversal_type, (None, None))
    if not cypher:
        return {"error": f"Unknown traversal type: {traversal_type}"}

    # For building traversals: resolve BBL first if not provided
    if entity_class == "building" and not params.get("bbl"):
        # Normalize address to match graph storage format (e.g. strip ordinal suffixes)
        raw_address = params.get("address")
        normalized_address = _normalize_address(raw_address) if raw_address else None

        lookup = neo4j_query(
            BUILDING_LOOKUP_CYPHER,
            params={
                "bbl":     None,
                "address": normalized_address,
                "borough": params.get("borough"),
            }
        )
        if not lookup:
            return {
                "needs_clarification": True,
                "clarification_request": (
                    f"I couldn't find a building matching "
                    f"'{raw_address}'"
                    f"{' in ' + params['borough'] if params.get('borough') else ''} "
                    f"in the Watchline database. Could you check the address "
                    f"or provide the BBL?"
                ),
                "traversal_results": tr,
            }
        params["bbl"] = lookup[0]["bbl"]
        tr["resolved_building"] = lookup[0]

    # Run the main traversal
    try:
        results = neo4j_query(cypher, params=params)
    except Exception as e:
        return {"error": f"Graph traversal failed: {str(e)}"}

    tr["raw_results"] = results
    tr["params"] = params

    return {"traversal_results": tr}


# ---------------------------------------------------------------------------
# Node 4: present_results
# LLM narrates the graph data. The only place the LLM speaks.
# Rules and interpretive status are always cited.
# ---------------------------------------------------------------------------

PRESENT_SYSTEM_PROMPT = """You are the narrator for Watchline NYC, an evidence-based
housing accountability system. Your job is to explain what the knowledge graph found
in response to the user's question.

CRITICAL RULES:
1. Never make claims beyond what the graph data shows. If the data is empty or null,
   say so honestly.
2. Always cite the Rule name and ID when reporting a Claim (e.g. "Rule PHC-001").
3. Always state the interpretive_status of any Claim
   (Inferred / Stipulated / Observed / Disputed).
4. Always name the source agency for any data (HPD, DOB, ECB/OATH, DHCR).
5. Never attribute malicious intent to any person or entity.
6. Use plain language. Explain what Class C violations are, what ECB/OATH is,
   what beneficial control means -- don't assume the user knows.
7. End every answer with the Watchline epistemic disclaimer:
   "This answer is based on public records as of the last data ingestion date.
    It does not constitute legal advice or a finding of wrongdoing."

Format your answer in clear prose. Use short paragraphs. Do not use bullet points
unless listing more than 5 items.
"""


def present_results(state: WatchlineState) -> dict:
    """LLM narrates the graph data into a plain-language answer."""
    import json

    tr = state.get("traversal_results", {})
    raw = tr.get("raw_results", [])
    resolved_building = tr.get("resolved_building")

    if not raw:
        answer = (
            "The Watchline knowledge graph did not return any data for this query. "
            "This may mean the building or entity is not in the database, or that "
            "no records of this type exist for the entity you asked about. "
            "\n\nThis answer is based on public records as of the last data "
            "ingestion date. It does not constitute legal advice or a finding "
            "of wrongdoing."
        )
        return {"answer": answer}

    # Prepare context for the LLM
    context = {
        "question":         state["question"],
        "intent":           state["intent"],
        "traversal_type":   tr.get("traversal_type"),
        "resolved_building": resolved_building,
        "graph_data":       raw,
    }

    llm = get_llm()
    response = llm.invoke([
        {"role": "system", "content": PRESENT_SYSTEM_PROMPT},
        {"role": "user",   "content": (
            f"User question: {state['question']}\n\n"
            f"Graph data returned:\n{json.dumps(context, indent=2, default=str)}\n\n"
            f"Please write a clear, honest, evidence-grounded answer."
        )},
    ])

    return {"answer": response.content}


# ---------------------------------------------------------------------------
# Node 5: request_clarification
# ---------------------------------------------------------------------------

def request_clarification(state: WatchlineState) -> dict:
    """Return the clarification request as the answer."""
    return {"answer": state.get("clarification_request", "Could you clarify your question?")}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_traversal(state: WatchlineState) -> str:
    if state.get("needs_clarification"):
        return "request_clarification"
    if state.get("error"):
        return "present_results"  # present_results handles empty data gracefully
    return "present_results"


def route_after_rules(state: WatchlineState) -> str:
    if state.get("needs_clarification"):
        return "request_clarification"
    return "execute_traversal"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_pipeline() -> object:
    """Build and compile the Watchline LangGraph pipeline."""
    builder = StateGraph(WatchlineState)

    builder.add_node("identify_intent",      identify_intent)
    builder.add_node("select_rules",         select_rules)
    builder.add_node("execute_traversal",    execute_traversal)
    builder.add_node("present_results",      present_results)
    builder.add_node("request_clarification",request_clarification)

    builder.add_edge(START, "identify_intent")
    builder.add_edge("identify_intent", "select_rules")

    builder.add_conditional_edges(
        "select_rules",
        route_after_rules,
        {
            "execute_traversal":     "execute_traversal",
            "request_clarification": "request_clarification",
        },
    )

    builder.add_conditional_edges(
        "execute_traversal",
        route_after_traversal,
        {
            "present_results":       "present_results",
            "request_clarification": "request_clarification",
        },
    )

    builder.add_edge("present_results",       END)
    builder.add_edge("request_clarification", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Tell me about 530 East 169th Street in the Bronx"
    )

    print(f"\nQuestion: {question}\n")
    print("-" * 60)

    pipeline = build_pipeline()
    result = pipeline.invoke({"question": question})

    print(result["answer"])

    if result.get("error"):
        print(f"\n[Pipeline error: {result['error']}]")
