"""
watchline/fw/intents/network_exposure.py

Intent: NetworkExposure
Rule:   NE-001 v1.0 (RUL-00008)

Two or more actors satisfy NE-001 if they are connected by ProbableAffiliation
relationships derived from shared WCC component membership in HPD registration
data. The combined PHC rate across the unified portfolio is the primary
accountability signal. ProbableAffiliation is a weaker inference than
ProbableBeneficialControl — it should never be presented as proven co-ownership.
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (aff:Relationship {relationship_type: "ProbableAffiliation"})
MATCH (aff)-[:INVOLVES_ACTOR]->(a)
MATCH (aff)-[:INVOLVES_ACTOR]->(affiliated:Actor)
WHERE affiliated.canonical_id <> a.canonical_id

WITH a, collect(DISTINCT affiliated) AS affiliates,
     collect(DISTINCT aff.basis) AS affiliation_bases,
     [a] + collect(DISTINCT affiliated) AS all_actors

UNWIND all_actors AS member
MATCH (bc:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(member)
MATCH (bc)-[:INVOLVES_BUILDING]->(b:Building)
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl
})
OPTIONAL MATCH (pbc:Claim {
  interpretive_concept: "ProbableBeneficialControl", subject_id: member.canonical_id
})
RETURN member.display_name           AS actor_name,
       member.canonical_id           AS actor_id,
       member.canonical_id = a.canonical_id AS is_named_actor,
       count(DISTINCT b.bbl)         AS portfolio_size,
       count(DISTINCT phc.claim_id)  AS phc_buildings,
       sum(b.residential_units)      AS total_units,
       left(pbc.claim_text, 300)     AS pbc_summary,
       affiliation_bases[0]          AS affiliation_basis
ORDER BY portfolio_size DESC
"""

_GRAPH_RULE_ID = "RUL-00008"
_RULE_ID       = "NE-001"
_RULE_VERSION  = "1.0"

_THRESHOLD_FALLBACK = (
    "Two or more actors satisfy Watchline Rule NE-001 (Network Exposure) if they "
    "are connected by ProbableAffiliation relationships derived from shared Weakly "
    "Connected Component membership in HPD registration data (RUL-00005 and "
    "RUL-00006). This is a weaker signal than Probable Beneficial Control: it "
    "indicates that the two ownership networks were originally part of the same "
    "registration graph before community detection split them. Confidence is Medium. "
    "A different community detection threshold would produce a different network boundary."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """Load NE-001 Rule metadata from the graph (Charter §11). Cached after first load."""
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
        "name":                     _RULE_ID,
        "version":                  _RULE_VERSION,
        "threshold_description":    _THRESHOLD_FALLBACK,
        "authority":                "Watchline editorial judgment",
        "effective_date":           "2026-07-05",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


class NetworkExposureHandler(IntentHandler):

    intent_category = "NetworkExposure"
    entity_class    = "actor"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"canonical_id": intent["canonical_id"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return None

        rule = _load_rule_from_graph()

        network_size = len(raw_results)
        if network_size < 2:
            return {
                "rule_id":            _RULE_ID,
                "rule_version":       rule.get("version", _RULE_VERSION),
                "network_size":       network_size,
                "insufficient_data":  True,
                "interpretive_status": "Inferred",
                "threshold_statement": rule.get("threshold_description", _THRESHOLD_FALLBACK),
                "authority":           rule.get("authority", ""),
                "effective_date":      rule.get("effective_date", ""),
                "author":              rule.get("author", ""),
            }

        combined_portfolio = sum(r.get("portfolio_size", 0) or 0 for r in raw_results)
        combined_phc       = sum(r.get("phc_buildings",  0) or 0 for r in raw_results)
        combined_units     = sum(r.get("total_units",    0) or 0 for r in raw_results)
        combined_phc_rate  = (
            round(combined_phc / combined_portfolio, 3)
            if combined_portfolio > 0 else 0.0
        )
        affiliation_basis  = raw_results[0].get("affiliation_basis") or ""

        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "network_size":         network_size,
            "combined_portfolio":   combined_portfolio,
            "combined_phc":         combined_phc,
            "combined_units":       combined_units,
            "combined_phc_rate":    combined_phc_rate,
            "affiliation_basis":    affiliation_basis,
            "confidence":           "Medium",
            "insufficient_data":    False,
            "interpretive_status":  "Inferred",
            "threshold_statement":  rule.get("threshold_description", _THRESHOLD_FALLBACK),
            "authority":            rule.get("authority", ""),
            "effective_date":       rule.get("effective_date", ""),
            "author":               rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
