"""
watchline/fw/intents/portfolio_identification.py

Intent: PortfolioIdentification
Rule:   PBC-001 (RUL-00002) — pre-evaluated at graph-build time

Traces a building to its probable beneficial controller(s) via BeneficialControl
Relationship nodes. Returns one row per distinct controller. evaluate() returns
None because the ProbableBeneficialControl Claim already encodes the rule
conclusion and threshold statement — no re-evaluation is performed here.
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (b:Building {bbl: $bbl})
MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_BUILDING]->(b)
MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
OPTIONAL MATCH (c:Claim {
  interpretive_concept: "ProbableBeneficialControl",
  subject_id: a.canonical_id
})
WITH b, a, c,
  EXISTS {
    MATCH (phc:Claim {interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl})
  } AS building_has_phc
RETURN a.display_name        AS controller_name,
       a.canonical_id        AS controller_id,
       a.actor_type          AS actor_type,
       c.claim_text          AS pbc_claim,
       c.interpretive_status AS interpretive_status,
       building_has_phc,
       b.address             AS address,
       b.borough             AS borough,
       b.bbl                 AS bbl,
       b.residential_units   AS residential_units
"""

_GRAPH_RULE_ID = "RUL-00002"
_RULE_ID       = "PBC-001"
_RULE_VERSION  = "1.0"

_THRESHOLD_FALLBACK = (
    "An OwnershipNetwork Actor generates a ProbableBeneficialControl Claim when: "
    "(1) it has at least one IdentityAssertion of confidence Medium or above; AND "
    "(2) it contains at least two distinct BBLs; AND (3) it has at least one "
    "address-based connection (RMT-002 edge) OR at least two name-based connections "
    "(RMT-001 edges). Each building in the network receives a BeneficialControl "
    "Relationship node linking it to the OwnershipNetwork Actor."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load PBC-001 Rule metadata from the graph (Charter §11).
    Cached in module scope after first load.
    Falls back to hardcoded constants if graph is unavailable.
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
        "name":                     _RULE_ID,
        "version":                  _RULE_VERSION,
        "threshold_description":    _THRESHOLD_FALLBACK,
        "authority":                "Watchline editorial judgment",
        "effective_date":           "2026-06-01",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


class PortfolioIdentificationHandler(IntentHandler):

    intent_category = "PortfolioIdentification"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        return None
