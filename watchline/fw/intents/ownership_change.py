"""
watchline/fw/intents/ownership_change.py

Intent: OwnershipChange
Rule:   OC-001 (RUL-00014) — Ownership Change Deterioration

Question: Did conditions change after this building was sold?

Uses ACRIS DeedTransfer events as the ownership change date, then compares
annualized HPD Class C violation rates before and after the most recent
arm's-length sale.

Arm's-length filter: doc_type = 'DEED', doc_amount > 0, pct_transferred >= 50.
Excludes trust transfers ($0 deeds), partial interest sales, and corrective deeds.

Rule fires when:
  - A qualifying deed transfer exists
  - >= 180 days have elapsed since the transfer
  - Annualized Class C rate after the transfer >= 1.5x the rate before
    OR there were zero violations before and at least one after

Interpretive status: Inferred
"""

from __future__ import annotations

from datetime import date

from watchline.fw.intents.base import IntentHandler

# ---------------------------------------------------------------------------
# Rule metadata — loaded from graph at runtime, fallback below
# ---------------------------------------------------------------------------

_RULE_ID       = "OC-001"
_RULE_VERSION  = "1.0"
_GRAPH_RULE_ID = "RUL-00014"

_THRESHOLD_STATEMENT_FALLBACK = (
    "A building satisfies Watchline Rule OC-001 (Ownership Change Deterioration) "
    "if: (1) at least one arm's-length deed transfer is recorded in ACRIS since "
    "2010, defined as doc_type DEED with doc_amount greater than zero and "
    "pct_transferred of 50 or more; AND (2) the annualized rate of Class C "
    "(immediately hazardous) HPD violations in the period after the most recent "
    "qualifying transfer is at least 50% higher than the annualized rate in the "
    "period before the transfer; AND (3) at least 180 days have elapsed since the "
    "transfer. A building with no Class C violations before the transfer and at "
    "least one after also satisfies the rule."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """Load OC-001 Rule metadata from the graph. Cached after first load."""
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
        "authority":                "ACRIS deed records + HPD violation data; Watchline editorial judgment",
        "effective_date":           "2026-07-08",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MIN_DAYS_AFTER  = 180   # minimum post-transfer window before rule can fire
_MIN_DAYS_BEFORE = 365   # minimum pre-transfer history for rate comparison
_RATE_INCREASE   = 1.5   # annualized rate_after / rate_before to trigger


# ---------------------------------------------------------------------------
# Cypher
# ---------------------------------------------------------------------------

_CYPHER = """
MATCH (b:Building {bbl: $bbl})

// Arm's-length deed transfers only: actual sales, not trust/LLC restructurings
OPTIONAL MATCH (b)-[:HAS_EVENT]->(deed:Event {event_type: 'DeedTransfer', doc_type: 'DEED'})
WHERE deed.doc_amount > 0
  AND deed.pct_transferred >= 50
  AND deed.event_date IS NOT NULL

WITH b, deed ORDER BY deed.event_date DESC

WITH b,
  collect(deed)[0]   AS latest_deed,
  collect({
    deed_date:     toString(deed.event_date),
    grantor:       deed.grantor_names,
    grantee:       deed.grantee_names,
    amount:        deed.doc_amount,
    pct:           deed.pct_transferred,
    recorded_date: toString(deed.recorded_date)
  }) AS deed_history

// Class C violations before the latest qualifying transfer
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v_before:Event {
  event_type: 'Violation', source_name: 'HPD', violation_class: 'C'
})
WHERE v_before.open_date IS NOT NULL
  AND latest_deed IS NOT NULL
  AND v_before.open_date < latest_deed.event_date

WITH b, latest_deed, deed_history,
  count(DISTINCT v_before) AS c_before,
  min(CASE WHEN v_before IS NOT NULL THEN v_before.open_date END) AS earliest_violation_date

// Class C violations after (all statuses — for rate comparison)
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v_after:Event {
  event_type: 'Violation', source_name: 'HPD', violation_class: 'C'
})
WHERE v_after.open_date IS NOT NULL
  AND latest_deed IS NOT NULL
  AND v_after.open_date >= latest_deed.event_date

WITH b, latest_deed, deed_history, c_before, earliest_violation_date,
  count(DISTINCT v_after) AS c_after

// Currently open Class C violations in the after period
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v_open:Event {
  event_type: 'Violation', source_name: 'HPD', violation_class: 'C', status: 'Open'
})
WHERE v_open.open_date IS NOT NULL
  AND latest_deed IS NOT NULL
  AND v_open.open_date >= latest_deed.event_date

RETURN b.bbl                       AS bbl,
  b.address                        AS address,
  b.borough                        AS borough,
  b.residential_units              AS residential_units,
  b.year_built                     AS year_built,
  toString(latest_deed.event_date) AS deed_date,
  latest_deed.grantor_names        AS grantor_names,
  latest_deed.grantee_names        AS grantee_names,
  latest_deed.doc_amount           AS deed_amount,
  latest_deed.pct_transferred      AS pct_transferred,
  deed_history,
  c_before,
  c_after,
  count(DISTINCT v_open)           AS c_open_after,
  toString(earliest_violation_date) AS earliest_violation_date,
  toString(date())                 AS today
"""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class OwnershipChangeHandler(IntentHandler):

    intent_category = "OwnershipChange"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return None

        row = raw_results[0]
        rule = _load_rule_from_graph()

        deed_date_str = row.get("deed_date")

        # No qualifying deed transfer found
        if not deed_date_str:
            return {
                "rule_id":              _RULE_ID,
                "rule_version":         rule.get("version", _RULE_VERSION),
                "interpretive_status":  "Observed",
                "no_deed_found":        True,
                "deterioration_signal": False,
                "insufficient_data":    True,
                "insufficient_data_reason": (
                    "No arm's-length deed transfer found in ACRIS since 2010. "
                    "ACRIS coverage begins 2010; earlier deed history is not in the graph."
                ),
                "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            }

        deed_date   = date.fromisoformat(deed_date_str)
        today       = date.fromisoformat(row["today"])
        days_after  = (today - deed_date).days

        c_before    = row.get("c_before") or 0
        c_after     = row.get("c_after")  or 0
        c_open_after = row.get("c_open_after") or 0
        earliest_str = row.get("earliest_violation_date")

        days_before = (
            (deed_date - date.fromisoformat(earliest_str)).days
            if earliest_str else 0
        )

        # Annualized rates (violations per year)
        rate_before = round(c_before / days_before * 365, 1) if days_before > 0 else 0.0
        rate_after  = round(c_after  / days_after  * 365, 1) if days_after  > 0 else 0.0

        # Insufficient data checks
        insufficient_before = days_before < _MIN_DAYS_BEFORE and c_before == 0
        insufficient_after  = days_after  < _MIN_DAYS_AFTER
        insufficient_data   = insufficient_before or insufficient_after

        # Rule evaluation
        if rate_before > 0:
            deterioration_signal = rate_after >= rate_before * _RATE_INCREASE
            rate_increase_pct    = round((rate_after - rate_before) / rate_before * 100, 1)
        elif c_after > 0:
            # Zero before, violations after — clear deterioration
            deterioration_signal = True
            rate_increase_pct    = None  # not meaningful (division by zero)
        else:
            deterioration_signal = False
            rate_increase_pct    = 0.0

        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "interpretive_status":  "Inferred",
            "deed_date":            deed_date_str,
            "grantor_names":        row.get("grantor_names"),
            "grantee_names":        row.get("grantee_names"),
            "deed_amount":          row.get("deed_amount"),
            "pct_transferred":      row.get("pct_transferred"),
            "deed_history":         [d for d in (row.get("deed_history") or []) if d.get("deed_date")],
            "c_before":             c_before,
            "c_after":              c_after,
            "c_open_after":         c_open_after,
            "days_before":          days_before,
            "days_after":           days_after,
            "rate_before":          rate_before,
            "rate_after":           rate_after,
            "rate_increase_pct":    rate_increase_pct,
            "deterioration_signal": deterioration_signal,
            "insufficient_data":    insufficient_data,
            "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
        }
