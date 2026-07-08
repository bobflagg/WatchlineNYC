"""
watchline/fw/intents/fine_evasion.py

Intent: FineEvasion
Rule:   FE-001 (RUL-00011)

A building satisfies FE-001 if it has one or more outstanding ECB/OATH
judgments with a combined unpaid balance exceeding $10,000.

Entity class: building (actor-level multi-building check is a planned v2).
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (b:Building {bbl: $bbl})-[:HAS_EVENT]->(e:Event {
  event_type: "Judgment", source_name: "ECB"
})
WITH b, e
WHERE e.balance_due IS NOT NULL
RETURN b.bbl     AS bbl,
       b.address  AS address,
       b.borough  AS borough,
       b.residential_units AS residential_units,
       count(e)   AS total_judgments,
       sum(CASE WHEN e.balance_due > 0 THEN 1 ELSE 0 END) AS judgments_with_balance,
       sum(CASE WHEN e.balance_due > 0 THEN e.balance_due ELSE 0 END) AS total_balance_due,
       sum(e.penalty_imposed)  AS total_penalties_imposed,
       sum(e.amount_paid)      AS total_paid,
       collect(CASE WHEN e.balance_due > 0 THEN {
         date:        e.issue_date,
         description: e.violation_description,
         penalty:     e.penalty_imposed,
         paid:        e.amount_paid,
         balance:     e.balance_due,
         status:      e.hearing_status
       } END) AS outstanding_items
"""

_GRAPH_RULE_ID = "RUL-00011"
_RULE_ID       = "FE-001"
_RULE_VERSION  = "1.0"
_THRESHOLD_BALANCE = 10_000.0

_THRESHOLD_FALLBACK = (
    "A building satisfies Watchline Rule FE-001 (Fine Evasion) if it has one or more "
    "outstanding ECB/OATH judgments with a combined unpaid balance exceeding $10,000. "
    "ECB judgments are civil penalty decisions issued by the Office of Administrative "
    "Trials and Hearings (OATH) for violations of the NYC Administrative Code. A "
    "balance_due greater than zero indicates a judgment that has not been fully paid. "
    "This threshold reflects Watchline editorial judgment, not a statutory definition."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load FE-001 Rule metadata from the graph (Charter §11).
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
        "authority":                "NYC OATH / ECB judgment records",
        "effective_date":           "2026-07-07",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


class FineEvasionHandler(IntentHandler):

    intent_category = "FineEvasion"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            rule = _load_rule_from_graph()
            return {
                "rule_id":             _RULE_ID,
                "rule_version":        rule.get("version", _RULE_VERSION),
                "evasion_flagged":     False,
                "insufficient_data":   True,
                "total_balance_due":   0.0,
                "judgment_count":      0,
                "interpretive_status": "Observed",
                "threshold_statement": rule.get("threshold_description", _THRESHOLD_FALLBACK),
                "authority":           rule.get("authority", ""),
                "effective_date":      rule.get("effective_date", ""),
                "author":              rule.get("author", ""),
                "falsification_conditions": rule.get("falsification_conditions", ""),
            }

        row = raw_results[0]
        total_balance_due      = float(row.get("total_balance_due") or 0)
        total_penalties        = float(row.get("total_penalties_imposed") or 0)
        total_paid             = float(row.get("total_paid") or 0)
        total_judgments        = int(row.get("total_judgments") or 0)
        judgments_with_balance = int(row.get("judgments_with_balance") or 0)

        evasion_flagged = total_balance_due > _THRESHOLD_BALANCE

        rule = _load_rule_from_graph()
        return {
            "rule_id":                  _RULE_ID,
            "rule_version":             rule.get("version", _RULE_VERSION),
            "evasion_flagged":          evasion_flagged,
            "insufficient_data":        False,
            "total_balance_due":        total_balance_due,
            "total_penalties_imposed":  total_penalties,
            "total_paid":               total_paid,
            "total_judgments":          total_judgments,
            "judgments_with_balance":   judgments_with_balance,
            "threshold":                _THRESHOLD_BALANCE,
            "interpretive_status":      "Inferred",
            "threshold_statement":      rule.get("threshold_description", _THRESHOLD_FALLBACK),
            "authority":                rule.get("authority", ""),
            "effective_date":           rule.get("effective_date", ""),
            "author":                   rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
