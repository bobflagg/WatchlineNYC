"""
watchline/fw/intents/portfolio_condition.py

Intent: PortfolioCondition
Rule:   PHC-001 (RUL-00001) — counts buildings in the actor's portfolio that
        already satisfy the Persistent Hazardous Conditions rule.

No new rule is applied here. The evaluate() aggregates pre-computed PHC Claims
across the portfolio and flags the actor if the PHC rate exceeds 50%.
The 50% threshold is Watchline editorial judgment, not a formal rule.
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(b:Building)
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions",
  subject_id: b.bbl
})
OPTIONAL MATCH (pbc:Claim {
  interpretive_concept: "ProbableBeneficialControl",
  subject_id: a.canonical_id
})
WITH a, pbc, b, phc
RETURN a.display_name AS name,
       a.canonical_id AS canonical_id,
       pbc.claim_text AS pbc_claim,
       count(DISTINCT b.bbl) AS portfolio_size,
       count(DISTINCT CASE WHEN phc IS NOT NULL THEN b.bbl END) AS phc_buildings,
       collect(DISTINCT CASE WHEN phc IS NOT NULL THEN {
         bbl:     b.bbl,
         address: b.address,
         borough: b.borough,
         units:   b.residential_units,
         claim:   phc.claim_text
       } END) AS phc_building_list
"""

# PHC-001 is the rule whose Claim nodes this intent aggregates.
_GRAPH_RULE_ID = "RUL-00001"
_PHC_RATE_THRESHOLD = 0.50

_rule_cache: dict | None = None


def _load_phc_rule_from_graph() -> dict:
    """
    Load PHC-001 Rule metadata from the graph (Charter §11).
    Cached in module scope after first load.
    """
    global _rule_cache
    if _rule_cache is not None:
        return _rule_cache
    try:
        from watchline.fw.connections import neo4j_query
        results = neo4j_query(
            "MATCH (r:Rule {rule_id: $rule_id}) "
            "RETURN r.name AS name, r.version AS version, "
            "r.threshold_description AS threshold_description, "
            "r.authority AS authority, r.effective_date AS effective_date, "
            "r.author AS author, "
            "r.falsification_conditions AS falsification_conditions",
            params={"rule_id": _GRAPH_RULE_ID},
        )
        if results:
            r = dict(results[0])
            if r.get("effective_date") and not isinstance(r["effective_date"], str):
                r["effective_date"] = str(r["effective_date"])
            _rule_cache = r
            return _rule_cache
    except Exception:
        pass
    _rule_cache = {
        "name":    "PHC-001",
        "version": "1.0",
        "threshold_description": (
            "Three or more Class C (immediately hazardous) violations are currently "
            "open AND the oldest open Class C violation has been open for more than "
            "180 days AND no active remediation order is in effect for the building."
        ),
        "authority":                "HPD violation classification standards (Class C: immediately hazardous).",
        "effective_date":           "2026-06-01",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


class PortfolioConditionHandler(IntentHandler):

    intent_category = "PortfolioCondition"
    entity_class    = "actor"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"canonical_id": intent["canonical_id"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return None

        row           = raw_results[0]
        portfolio_size = int(row.get("portfolio_size") or 0)
        phc_buildings  = int(row.get("phc_buildings") or 0)

        if portfolio_size == 0:
            return None

        phc_rate      = phc_buildings / portfolio_size
        high_phc_rate = phc_rate >= _PHC_RATE_THRESHOLD

        rule = _load_phc_rule_from_graph()
        return {
            "rule_id":             "PHC-001",
            "rule_version":        rule.get("version", "1.0"),
            "portfolio_size":      portfolio_size,
            "phc_buildings":       phc_buildings,
            "phc_rate":            round(phc_rate, 3),
            "high_phc_rate":       high_phc_rate,
            "insufficient_data":   False,
            "interpretive_status": "Inferred",
            "threshold_statement": rule.get("threshold_description", ""),
            "authority":           rule.get("authority", ""),
            "effective_date":      rule.get("effective_date", ""),
            "author":              rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
