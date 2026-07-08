"""
watchline/fw/intents/enforcement_accountability.py

Intent: EnforcementAccountability
Rule:   EA-001 (RUL-00012) — Enforcement Accountability Gap

Evaluates whether HPD has followed up with court action on buildings
that have long-open Class C (immediately hazardous) violations.
"""

from watchline.fw.intents.base import IntentHandler
from watchline.fw.connections import neo4j_query


_GRAPH_RULE_ID    = "RUL-00012"
_RULE_ID          = "EA-001"
_RULE_VERSION     = "1.0"
_THRESHOLD_COUNT  = 3    # minimum stale Class C violations
_THRESHOLD_DAYS   = 365  # days open before a violation is "stale"

_rule_cache: dict = {}


def _load_rule_from_graph() -> dict:
    if _rule_cache:
        return _rule_cache
    rows = neo4j_query(
        "MATCH (r:Rule {rule_id: $rid}) RETURN r", {"rid": _GRAPH_RULE_ID}
    )
    if rows:
        r = dict(rows[0]["r"])
        if hasattr(r.get("effective_date"), "year"):
            r["effective_date"] = str(r["effective_date"])
        _rule_cache.update(r)
    else:
        _rule_cache.update({
            "rule_id":             _GRAPH_RULE_ID,
            "name":                _RULE_ID,
            "title":               "Enforcement Accountability Gap",
            "version":             _RULE_VERSION,
            "threshold_description": (
                f"A building satisfies Watchline Rule EA-001 (Enforcement Accountability Gap) "
                f"if it has {_THRESHOLD_COUNT} or more open Class C (immediately hazardous) "
                f"violations open for more than {_THRESHOLD_DAYS} days, with zero HPD court "
                f"filings recorded since the earliest such violation was opened."
            ),
        })
    return _rule_cache


_CYPHER = """
MATCH (b:Building {bbl: $bbl})

// Long-open Class C violations (>= 365 days open, still open)
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v:Event {
  event_type: "Violation", source_name: "HPD",
  violation_class: "C", status: "Open"
})
WHERE v.open_date IS NOT NULL
  AND duration.inDays(v.open_date, date()).days > 365

WITH b,
  count(DISTINCT v) AS long_open_c,
  min(v.open_date)  AS earliest_stale_date,
  collect(CASE WHEN v IS NOT NULL THEN {
    date:           toString(v.open_date),
    days_open:      duration.inDays(v.open_date, date()).days,
    description:    v.description,
    violation_code: v.violation_code
  } END) AS stale_violations

// Court filings since the earliest stale violation was opened
OPTIONAL MATCH (b)-[:HAS_EVENT]->(cf:Event {event_type: "CourtFiling"})
WHERE cf.event_date IS NOT NULL
  AND (earliest_stale_date IS NULL OR cf.event_date >= earliest_stale_date)

RETURN b.bbl              AS bbl,
       b.address          AS address,
       b.borough          AS borough,
       b.residential_units AS residential_units,
       long_open_c,
       count(DISTINCT cf) AS court_actions_in_period,
       earliest_stale_date,
       stale_violations
"""


class EnforcementAccountabilityHandler(IntentHandler):

    intent_category = "EnforcementAccountability"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return {
                "rule_id":              _RULE_ID,
                "rule_version":         _RULE_VERSION,
                "interpretive_status":  "Inferred",
                "insufficient_data":    True,
                "accountability_gap":   False,
                "long_open_c_count":    0,
                "court_actions":        0,
                "threshold_statement":  _load_rule_from_graph().get("threshold_description", ""),
            }

        r                    = raw_results[0]
        long_open_c          = int(r.get("long_open_c") or 0)
        court_actions        = int(r.get("court_actions_in_period") or 0)
        earliest_stale_date  = r.get("earliest_stale_date")
        if hasattr(earliest_stale_date, "year"):
            earliest_stale_date = str(earliest_stale_date)

        accountability_gap = (long_open_c >= _THRESHOLD_COUNT) and (court_actions == 0)

        rule = _load_rule_from_graph()
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         _RULE_VERSION,
            "interpretive_status":  "Inferred",
            "insufficient_data":    False,
            "accountability_gap":   accountability_gap,
            "long_open_c_count":    long_open_c,
            "court_actions":        court_actions,
            "earliest_stale_date":  earliest_stale_date,
            "threshold_statement":  rule.get("threshold_description", ""),
            "threshold_logic":      rule.get("threshold_logic", ""),
            "rule_title":           rule.get("title", "Enforcement Accountability Gap"),
            "authority":            rule.get("authority", ""),
        }
