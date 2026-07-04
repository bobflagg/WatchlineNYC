"""
watchline/fw/intents/deterioration.py

Intent: DeteriorationTrajectory
Rule:   DT-001 v1.0

A building satisfies DT-001 if two signals are both present over the most recent
5 full calendar years:
  Signal A: average annual Class C violation issuance is higher in the most recent
            2 years than in the earliest 2 years of the window.
  Signal B: the resolution rate of Class C violations open more than 180 days is
            lower in the most recent 2 years than in the earliest 2 years.

Both signals must be satisfied. The current partial year is retrieved separately
and presented as early-signal context only — it does not contribute to rule evaluation.
"""

from watchline.fw.intents.base import IntentHandler


# ---------------------------------------------------------------------------
# Cypher
# ---------------------------------------------------------------------------

_CYPHER = """
MATCH (b:Building {bbl: $bbl})
MATCH (b)-[:HAS_EVENT]->(e:Event {source_name: 'HPD', event_type: 'Violation',
                                   violation_class: 'C'})
WHERE e.open_date IS NOT NULL

WITH b, e,
     e.open_date.year AS issue_year,
     duration.inDays(e.open_date, date()).days AS age_days,
     CASE WHEN e.status = 'Closed' AND e.current_status_date IS NOT NULL
          THEN duration.inDays(e.open_date, e.current_status_date).days
          ELSE null END AS days_to_resolve

WITH b,
     collect(CASE WHEN issue_year >= 2021 AND issue_year <= 2025
             THEN {year: issue_year, age: age_days,
                   resolved: e.status = 'Closed',
                   days_to_resolve: days_to_resolve}
             END) AS window_events,
     collect(CASE WHEN issue_year = 2026
             THEN {age: age_days, resolved: e.status = 'Closed'}
             END) AS current_year_events

UNWIND window_events AS we
WITH b, current_year_events, we
WHERE we IS NOT NULL

WITH b, current_year_events,
     we.year AS yr,
     count(*) AS issued,
     sum(CASE WHEN we.age > 180 THEN 1 ELSE 0 END) AS eligible,
     sum(CASE WHEN we.age > 180 AND we.resolved THEN 1 ELSE 0 END) AS resolved_of_eligible

WITH b, current_year_events,
     collect({
       year:                  yr,
       issued:                issued,
       eligible:              eligible,
       resolved_of_eligible:  resolved_of_eligible,
       resolution_rate:       CASE WHEN eligible > 0
                              THEN toFloat(resolved_of_eligible) / eligible
                              ELSE null END
     }) AS yearly,
     size([x IN current_year_events WHERE x IS NOT NULL]) AS cy_issued,
     size([x IN current_year_events WHERE x IS NOT NULL AND x.age > 180]) AS cy_over_180

RETURN
  b.bbl               AS bbl,
  b.address           AS address,
  b.borough           AS borough,
  b.residential_units AS residential_units,
  yearly              AS annual_trajectory,
  cy_issued           AS current_year_issued,
  cy_over_180         AS current_year_over_180
"""

# ---------------------------------------------------------------------------
# Rule metadata
# Charter §11: Rules are first-class objects stored in the graph.
# _load_rule_from_graph() fetches live metadata from RUL-00007 at runtime.
# Fallback constants are used only if the graph is unavailable.
# ---------------------------------------------------------------------------

_RULE_ID        = "DT-001"
_RULE_VERSION   = "1.0"
_GRAPH_RULE_ID  = "RUL-00007"

_THRESHOLD_STATEMENT_FALLBACK = (
    "A building satisfies Watchline Rule DT-001 (Deterioration Trajectory) if two "
    "signals are both present over the most recent 5 full calendar years: "
    "(A) average annual Class C violation issuance is higher in the most recent "
    "2 years than in the earliest 2 years of the window; and "
    "(B) the resolution rate of Class C violations that have been open more than "
    "180 days is lower in the most recent 2 years than in the earliest 2 years. "
    "Both signals must be satisfied. This threshold reflects Watchline editorial "
    "judgment, not a statutory definition. A different threshold would produce "
    "a different result."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load DT-001 Rule metadata from the graph (Charter §11).
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
            # effective_date comes back as a neo4j.time.Date object — convert to str
            if r.get("effective_date") and not isinstance(r["effective_date"], str):
                r["effective_date"] = str(r["effective_date"])
            _rule_cache = r
            return _rule_cache
    except Exception:
        pass
    # Fallback if graph unavailable
    _rule_cache = {
        "name":                     _RULE_ID,
        "version":                  _RULE_VERSION,
        "threshold_description":    _THRESHOLD_STATEMENT_FALLBACK,
        "authority":                "Watchline editorial judgment",
        "effective_date":           "2026-07-04",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class DeteriorationTrajectoryHandler(IntentHandler):

    intent_category = "DeteriorationTrajectory"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return None

        annual_trajectory = raw_results[0].get("annual_trajectory", [])
        by_year  = {
            row["year"]: row
            for row in annual_trajectory
            if row is not None
        }
        available = sorted(by_year.keys())

        # Require at least 3 years of history to detect a trend
        if len(available) < 3:
            rule = _load_rule_from_graph()
            return {
                "rule_id":              _RULE_ID,
                "rule_version":         rule.get("version", _RULE_VERSION),
                "signal_a_satisfied":   None,
                "signal_b_satisfied":   None,
                "deteriorating":        None,
                "insufficient_data":    True,
                "available_years":      available,
                "interpretive_status":  "Inferred",
                "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
                "authority":            rule.get("authority", ""),
                "effective_date":       rule.get("effective_date", ""),
                "author":               rule.get("author", ""),
            }

        early_years  = available[:2]
        recent_years = available[-2:]

        # Signal A — issuance trend
        early_avg_issued  = sum(by_year[y]["issued"] for y in early_years)  / 2
        recent_avg_issued = sum(by_year[y]["issued"] for y in recent_years) / 2
        signal_a = recent_avg_issued > early_avg_issued

        # Signal B — resolution rate trend (only years with eligible violations)
        early_rates  = [
            by_year[y]["resolution_rate"] for y in early_years
            if by_year[y]["resolution_rate"] is not None
        ]
        recent_rates = [
            by_year[y]["resolution_rate"] for y in recent_years
            if by_year[y]["resolution_rate"] is not None
        ]

        if early_rates and recent_rates:
            early_avg_rate  = sum(early_rates)  / len(early_rates)
            recent_avg_rate = sum(recent_rates) / len(recent_rates)
            signal_b = recent_avg_rate < early_avg_rate
        else:
            early_avg_rate  = None
            recent_avg_rate = None
            signal_b        = None

        rule = _load_rule_from_graph()
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "signal_a_satisfied":   signal_a,
            "signal_b_satisfied":   signal_b,
            "deteriorating":        bool(signal_a and signal_b),
            "insufficient_data":    False,
            "signal_a_detail": {
                "early_years":       early_years,
                "recent_years":      recent_years,
                "early_avg_issued":  round(early_avg_issued,  1),
                "recent_avg_issued": round(recent_avg_issued, 1),
            },
            "signal_b_detail": {
                "early_years":      early_years,
                "recent_years":     recent_years,
                "early_avg_rate":   round(early_avg_rate,  3) if early_avg_rate  is not None else None,
                "recent_avg_rate":  round(recent_avg_rate, 3) if recent_avg_rate is not None else None,
            },
            "interpretive_status":       "Inferred",
            "threshold_statement":       rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":                 rule.get("authority", ""),
            "effective_date":            rule.get("effective_date", ""),
            "author":                    rule.get("author", ""),
            "falsification_conditions":  rule.get("falsification_conditions", ""),
        }
