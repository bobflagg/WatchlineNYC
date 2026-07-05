"""
watchline/fw/intents/building_due_diligence.py

Intent: BuildingDueDiligence
Rule:   None — data retrieval only

Comprehensive single-building report: violations by class and status,
ownership, court filings, ECB judgments, PHC status.
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (b:Building {bbl: $bbl})

OPTIONAL MATCH (b)-[:HAS_EVENT]->(v:Event {event_type: "Violation", source_name: "HPD"})
WITH b,
  sum(CASE WHEN v.violation_class = "C" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_c,
  sum(CASE WHEN v.violation_class = "B" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_b,
  sum(CASE WHEN v.violation_class = "A" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_a,
  count(DISTINCT v) AS total_violations

OPTIONAL MATCH (b)-[:HAS_EVENT]->(cf:Event {event_type: "CourtFiling"})
WITH b, open_c, open_b, open_a, total_violations,
  count(DISTINCT cf) AS total_filings,
  sum(CASE WHEN cf.status = "OPEN" THEN 1 ELSE 0 END) AS open_filings,
  sum(CASE WHEN cf.is_harassment_finding = true THEN 1 ELSE 0 END) AS harassment_findings

OPTIONAL MATCH (b)-[:HAS_EVENT]->(ecb:Event {event_type: "Judgment", source_name: "ECB"})
WITH b, open_c, open_b, open_a, total_violations,
  total_filings, open_filings, harassment_findings,
  count(DISTINCT ecb) AS total_ecb,
  sum(CASE WHEN ecb.balance_due > 0 THEN ecb.balance_due ELSE 0 END) AS total_balance_due

// EXISTS avoids cartesian product with multiple PHC claims
WITH b, open_c, open_b, open_a, total_violations,
  total_filings, open_filings, harassment_findings,
  total_ecb, total_balance_due,
  EXISTS {
    MATCH (:Claim {interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl})
  } AS has_phc

OPTIONAL MATCH (phc:Claim {interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl})
WITH b, open_c, open_b, open_a, total_violations,
  total_filings, open_filings, harassment_findings,
  total_ecb, total_balance_due, has_phc,
  collect(phc.claim_text)[0] AS phc_claim

// COLLECT controllers to avoid cartesian product with multiple BeneficialControl relationships
OPTIONAL MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_BUILDING]->(b)
OPTIONAL MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
WITH b, open_c, open_b, open_a, total_violations,
  total_filings, open_filings, harassment_findings,
  total_ecb, total_balance_due, has_phc, phc_claim,
  collect(DISTINCT {name: a.display_name, id: a.canonical_id}) AS controllers

RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
       b.residential_units AS residential_units, b.year_built AS year_built,
       b.building_class AS building_class,
       b.rs_units_current AS rs_units_current, b.rs_deregulating AS rs_deregulating,
       open_c, open_b, open_a, total_violations,
       total_filings, open_filings, harassment_findings,
       total_ecb, total_balance_due,
       has_phc, phc_claim, controllers
"""


class BuildingDueDiligenceHandler(IntentHandler):

    intent_category = "BuildingDueDiligence"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        return None
