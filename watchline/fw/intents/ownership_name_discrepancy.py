"""
watchline/fw/intents/ownership_name_discrepancy.py

Intent: OwnershipNameDiscrepancy
Rule:   OND-001 v1.0 (RUL-00016)

A building satisfies OND-001 if DOF's recorded owner-of-record name
(dof_ownername) does not look corporate AND shares no name token with the
display_name of the Actor Watchline has resolved as the building's probable
beneficial controller (RUL-00002 / PBC-001).

IMPORTANT — read before changing thresholds: this rule's positive-flag rate
is HIGH relative to every other rule in this codebase (~71% of its
applicable population, verified against live evidentiary data 2026-07-17).
display_name is chosen in portfolio/store.py as the single most frequent
registered contact name across an Actor's ENTIRE portfolio network, not the
specific name this individual building was registered under — the raw
per-building HPD-registered name is not currently preserved anywhere in the
evidentiary graph (intermediate Landlord nodes are deleted after each
portfolio run). A positive flag here is therefore Low confidence and should
be presented as a lead worth checking by hand, NOT as evidence of
concealment. See RUL-00016's amendment_notes for the full calibration
numbers and the future-work path (a constituent_names list per Actor) that
would make this comparison more precise.

Entity class: building.
"""

import re

from watchline.fw.intents.base import IntentHandler


# ---------------------------------------------------------------------------
# Cypher
# ---------------------------------------------------------------------------

_CYPHER = """
MATCH (b:Building {bbl: $bbl})
OPTIONAL MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})-[:INVOLVES_BUILDING]->(b)
OPTIONAL MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
OPTIONAL MATCH (c:Claim {interpretive_concept: 'ProbableBeneficialControl', subject_id: a.canonical_id})
RETURN
  b.bbl               AS bbl,
  b.address           AS address,
  b.borough           AS borough,
  b.residential_units AS residential_units,
  b.dof_ownername     AS dof_ownername,
  b.dof_ownertype     AS dof_ownertype,
  a.canonical_id       AS controller_id,
  a.display_name       AS controller_name,
  a.actor_type          AS controller_type,
  c.claim_text          AS pbc_claim
"""

# ---------------------------------------------------------------------------
# Corporate-suffix heuristic (see RUL-00016 threshold_logic — same regex,
# kept in sync manually; not loaded from the graph since it's a Python-side
# implementation detail, not part of the Rule's stated threshold)
# ---------------------------------------------------------------------------

_CORPORATE_SUFFIX_RE = re.compile(
    r"(LLC|L\.L\.C\.|INC|CORP|CO\.|COMPANY|LP|L\.P\.|LTD|TRUST|ASSOC|"
    r"REALTY|PROPERTIES|MGMT|MANAGEMENT|HOLDINGS)",
    re.IGNORECASE,
)


def _norm_tokens(name: str | None) -> set:
    if not name:
        return set()
    cleaned = re.sub(r"[^A-Za-z\s]", " ", name.upper())
    return {t for t in cleaned.split() if len(t) > 1}


# ---------------------------------------------------------------------------
# Rule metadata
# Charter §11: Rules are first-class objects stored in the graph.
# _load_rule_from_graph() fetches live metadata from RUL-00016 at runtime.
# Fallback constants are used only if the graph is unavailable.
# ---------------------------------------------------------------------------

_RULE_ID       = "OND-001"
_RULE_VERSION  = "1.0"
_GRAPH_RULE_ID = "RUL-00016"

_THRESHOLD_STATEMENT_FALLBACK = (
    "A building satisfies Watchline Rule OND-001 (Ownership Name Discrepancy) "
    "if: (1) DOF's recorded owner-of-record name does not look corporate; AND "
    "(2) DOF's owner name shares no name token in common with the display_name "
    "of the Actor Watchline has resolved as the building's probable "
    "beneficial controller. Corporate-looking DOF names are excluded from "
    "evaluation entirely because a corporate title-holder differing from a "
    "named natural-person beneficial owner is the expected, non-suspicious "
    "shape of NYC LLC-held rental property. This finding is Low confidence."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load OND-001 Rule metadata from the graph (Charter §11).
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
        "threshold_description":    _THRESHOLD_STATEMENT_FALLBACK,
        "authority":                "Watchline editorial judgment",
        "effective_date":           "2026-07-17",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class OwnershipNameDiscrepancyHandler(IntentHandler):

    intent_category = "OwnershipNameDiscrepancy"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def _insufficient(self, rule: dict, reason: str, **extra) -> dict:
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "discrepancy_flagged":  None,
            "insufficient_data":    True,
            "reason":               reason,
            "is_corporate":         extra.get("is_corporate"),
            "dof_ownername":        extra.get("dof_ownername"),
            "controller_name":      extra.get("controller_name"),
            "controller_id":        extra.get("controller_id"),
            "token_overlap":        None,
            "confidence":           "Low",
            "interpretive_status":  "Inferred",
            "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":            rule.get("authority", ""),
            "effective_date":       rule.get("effective_date", ""),
            "author":               rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }

    def evaluate(self, raw_results: list) -> dict | None:
        rule = _load_rule_from_graph()

        if not raw_results:
            return self._insufficient(rule, "building_not_resolved")

        row = raw_results[0]
        dof_name        = (row.get("dof_ownername") or "").strip()
        controller_name = row.get("controller_name")
        controller_id   = row.get("controller_id")

        if not dof_name:
            return self._insufficient(
                rule, "no_dof_owner_name",
                controller_name=controller_name, controller_id=controller_id,
            )

        if not controller_name:
            return self._insufficient(
                rule, "no_resolved_controller", dof_ownername=dof_name,
            )

        is_corporate = bool(_CORPORATE_SUFFIX_RE.search(dof_name))
        if is_corporate:
            return self._insufficient(
                rule, "corporate_owner_out_of_scope",
                is_corporate=True, dof_ownername=dof_name,
                controller_name=controller_name, controller_id=controller_id,
            )

        dof_tokens  = _norm_tokens(dof_name)
        ctrl_tokens = _norm_tokens(controller_name)
        token_overlap = bool(dof_tokens & ctrl_tokens)
        discrepancy_flagged = not token_overlap

        return {
            "rule_id":                  _RULE_ID,
            "rule_version":             rule.get("version", _RULE_VERSION),
            "discrepancy_flagged":      discrepancy_flagged,
            "insufficient_data":        False,
            "reason":                   None,
            "is_corporate":             False,
            "dof_ownername":            dof_name,
            "dof_ownertype":            row.get("dof_ownertype"),
            "controller_name":          controller_name,
            "controller_id":            controller_id,
            "controller_type":          row.get("controller_type"),
            "pbc_claim":                row.get("pbc_claim"),
            "token_overlap":            token_overlap,
            "confidence":               "Low",
            "interpretive_status":      "Inferred",
            "threshold_statement":      rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":                rule.get("authority", ""),
            "effective_date":           rule.get("effective_date", ""),
            "author":                   rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
