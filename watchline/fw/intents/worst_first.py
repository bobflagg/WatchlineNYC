"""
watchline/fw/intents/worst_first.py

Intent: WorstFirst
Rule:   None — ranking output only.

Dataset-level query. No entity resolution required — the router bypasses
entity resolution for this intent category. Returns the top 20 actors
ranked by PHC building count across their portfolio (minimum 5 buildings).
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
// Phase 1: Count PHC buildings per actor.
// Starting from 41K pre-computed PHC Claims (not all 444K buildings)
// avoids a costly OPTIONAL MATCH loop. Building.bbl IS KEY, so the
// lookup here uses the unique index.
MATCH (phc:Claim {interpretive_concept: "PersistentHazardousConditions"})
MATCH (bc:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_BUILDING]->(b:Building {bbl: phc.subject_id})
MATCH (bc)-[:INVOLVES_ACTOR]->(a:Actor)
WITH a, count(DISTINCT phc.subject_id) AS phc_count

// Phase 2: Count total portfolio size for each actor with PHC buildings.
MATCH (bc2:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
MATCH (bc2)-[:INVOLVES_BUILDING]->(b2:Building)
WITH a, phc_count,
     count(DISTINCT b2.bbl)       AS portfolio_size,
     sum(b2.residential_units)    AS total_units
WHERE portfolio_size >= 5

RETURN a.display_name                      AS name,
       a.canonical_id                      AS canonical_id,
       portfolio_size,
       phc_count,
       total_units,
       toFloat(phc_count) / portfolio_size AS phc_rate
ORDER BY phc_count DESC, phc_rate DESC
LIMIT 20
"""


class WorstFirstHandler(IntentHandler):

    intent_category = "WorstFirst"
    entity_class    = "actor"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {}

    def evaluate(self, raw_results: list) -> dict | None:
        return None
