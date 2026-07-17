"""
watchline/fw/intents/vacate_history.py

Intent: VacateHistory
Rule:   VA-001 v1.0 (RUL-00015)

A building satisfies VA-001 if HPD has issued one or more vacate orders
against it. No minimum count above one is required -- a vacate order is
already HPD's own severe displacement determination, unlike routine
violation-count thresholds elsewhere in this ruleset (PHC-001, RCV-001).
Two sub-signals are additionally surfaced without gating the base verdict:
currently_active (an order with no recorded rescind date -- ongoing
displacement) and recurring (two or more orders on record, active or
historical).
"""

from watchline.fw.intents.base import IntentHandler


# ---------------------------------------------------------------------------
# Cypher
# ---------------------------------------------------------------------------

_CYPHER = """
MATCH (b:Building {bbl: $bbl})
OPTIONAL MATCH (b)-[:HAS_EVENT]->(e:Event {event_type: 'VacateOrder', source_name: 'HPD'})

WITH b, e
ORDER BY e.event_date DESC

WITH b, collect(CASE WHEN e IS NOT NULL THEN {
  vacate_order_number: e.source_record_id,
  event_date:          e.event_date,
  status:              e.status,
  vacate_reason:       e.violation_class,
  vacate_type:         e.vacate_type,
  units_vacated:       e.units_vacated,
  rescind_date:        e.rescind_date,
  registration_id:     e.registration_id
} END) AS raw_orders

WITH b, [o IN raw_orders WHERE o IS NOT NULL] AS vacate_orders

RETURN
  b.bbl               AS bbl,
  b.address           AS address,
  b.borough           AS borough,
  b.residential_units AS residential_units,
  vacate_orders        AS vacate_orders,
  size(vacate_orders)  AS vacate_order_count,
  size([o IN vacate_orders WHERE o.status = 'Active']) AS active_count
"""

# ---------------------------------------------------------------------------
# Rule metadata
# Charter §11: Rules are first-class objects stored in the graph.
# _load_rule_from_graph() fetches live metadata from RUL-00015 at runtime.
# Fallback constants are used only if the graph is unavailable.
# ---------------------------------------------------------------------------

_RULE_ID       = "VA-001"
_RULE_VERSION  = "1.0"
_GRAPH_RULE_ID = "RUL-00015"

_THRESHOLD_STATEMENT_FALLBACK = (
    "A building satisfies Watchline Rule VA-001 (Vacate History) if HPD has "
    "issued one or more vacate orders against the building on record. Because "
    "a vacate order already represents HPD's own severe safety determination "
    "-- residents were displaced, not merely cited -- no minimum count above "
    "one is required to establish evidentiary significance, unlike routine "
    "violation-count thresholds elsewhere in this ruleset. A vacate order "
    "with no recorded rescind date is currently Active, indicating ongoing "
    "displacement at query time. Two or more vacate orders recorded for the "
    "same building, active or historical, are additionally flagged as a "
    "recurring displacement pattern."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load VA-001 Rule metadata from the graph (Charter §11).
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

class VacateHistoryHandler(IntentHandler):

    intent_category = "VacateHistory"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        rule = _load_rule_from_graph()

        # resolve_building() guarantees the Building exists before this
        # handler runs, and the OPTIONAL MATCH guarantees exactly one row
        # back even with zero vacate orders -- a confirmed zero is a valid,
        # confident answer, not missing data (see rent_stabilization.py's
        # no_rs_history for the same distinction pattern in this codebase).
        if not raw_results:
            return {
                "rule_id":              _RULE_ID,
                "rule_version":         rule.get("version", _RULE_VERSION),
                "vacate_history_flagged": None,
                "insufficient_data":    True,
                "no_vacate_history":    False,
                "vacate_order_count":   0,
                "active_count":         0,
                "currently_active":     False,
                "recurring":            False,
                "vacate_orders":        [],
                "interpretive_status":  "Inferred",
                "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
                "authority":            rule.get("authority", ""),
                "effective_date":       rule.get("effective_date", ""),
                "author":               rule.get("author", ""),
                "falsification_conditions": rule.get("falsification_conditions", ""),
            }

        row = raw_results[0]
        count        = int(row.get("vacate_order_count") or 0)
        active_count = int(row.get("active_count") or 0)
        orders       = row.get("vacate_orders") or []

        satisfied         = count >= 1
        currently_active  = active_count >= 1
        recurring         = count >= 2

        return {
            "rule_id":                  _RULE_ID,
            "rule_version":             rule.get("version", _RULE_VERSION),
            "vacate_history_flagged":   satisfied,
            "insufficient_data":        False,
            "no_vacate_history":        count == 0,
            "vacate_order_count":       count,
            "active_count":             active_count,
            "currently_active":         currently_active,
            "recurring":                recurring,
            "vacate_orders":            orders,
            "interpretive_status":      "Inferred",
            "threshold_statement":      rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":                rule.get("authority", ""),
            "effective_date":           rule.get("effective_date", ""),
            "author":                   rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
