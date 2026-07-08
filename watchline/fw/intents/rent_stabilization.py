"""
watchline/fw/intents/rent_stabilization.py

Intent: RentStabilization
Rule:   RS-001 (RUL-00010)

A building satisfies RS-001 if both signals are present:
  Signal A: rs_units_change < 0 (unit count has declined over available history)
  Signal B: rs_deregulating flag is true (active removal from DHCR registry)

Both signals must be satisfied. A building with a negative unit change but no
active deregistration signal does not satisfy the rule.
"""

from watchline.fw.intents.base import IntentHandler


_CYPHER = """
MATCH (b:Building {bbl: $bbl})
RETURN b.bbl               AS bbl,
       b.address            AS address,
       b.borough            AS borough,
       b.residential_units  AS residential_units,
       b.rs_units_2018      AS rs_2018,
       b.rs_units_2019      AS rs_2019,
       b.rs_units_2020      AS rs_2020,
       b.rs_units_2021      AS rs_2021,
       b.rs_units_2022      AS rs_2022,
       b.rs_units_2023      AS rs_2023,
       b.rs_units_current   AS rs_current,
       b.rs_units_change    AS rs_change,
       b.rs_deregulating    AS rs_deregulating,
       b.rs_pdfsoa_2023     AS pdfsoa_url
"""

_GRAPH_RULE_ID = "RUL-00010"
_RULE_ID       = "RS-001"
_RULE_VERSION  = "1.0"

_THRESHOLD_FALLBACK = (
    "A building satisfies Watchline Rule RS-001 (Rent Stabilization Loss) if two "
    "conditions are both present: (1) the change in rent-stabilized unit count from "
    "the earliest available year to the most recent is negative (rs_units_change < 0); "
    "and (2) the DHCR rs_deregulating flag is true, indicating active removal of units "
    "from the stabilization registry. Both conditions must be satisfied. A building "
    "with a negative unit change but no active deregistration signal is noted but does "
    "not satisfy the rule."
)

# Year columns in chronological order — must match CYPHER aliases above
_RS_YEAR_FIELDS = [
    (2018, "rs_2018"), (2019, "rs_2019"), (2020, "rs_2020"),
    (2021, "rs_2021"), (2022, "rs_2022"), (2023, "rs_2023"),
]

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load RS-001 Rule metadata from the graph (Charter §11).
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
        "authority":                "DHCR rent registration records; Furman Center for Real Estate and Urban Policy",
        "effective_date":           "2026-07-07",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


class RentStabilizationHandler(IntentHandler):

    intent_category = "RentStabilization"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return None

        row            = raw_results[0]
        rs_change      = row.get("rs_change")
        rs_deregulating = row.get("rs_deregulating")

        # Build year-indexed dict of non-null RS unit counts
        year_data = [
            (yr, int(row[key]))
            for yr, key in _RS_YEAR_FIELDS
            if row.get(key) is not None
        ]

        # No DHCR data at all — building has no rent-stabilized history
        if not year_data and row.get("rs_current") is None:
            rule = _load_rule_from_graph()
            return {
                "rule_id":             _RULE_ID,
                "rule_version":        rule.get("version", _RULE_VERSION),
                "deregulating":        None,
                "insufficient_data":   True,
                "no_rs_history":       True,
                "interpretive_status": "Observed",
                "threshold_statement": rule.get("threshold_description", _THRESHOLD_FALLBACK),
                "authority":           rule.get("authority", ""),
                "effective_date":      rule.get("effective_date", ""),
                "author":              rule.get("author", ""),
                "falsification_conditions": rule.get("falsification_conditions", ""),
            }

        earliest_year = year_data[0][0]  if year_data else None
        latest_year   = year_data[-1][0] if year_data else None
        earliest_val  = year_data[0][1]  if year_data else None

        # Units lost = absolute value of negative rs_change
        if rs_change is not None and rs_change < 0:
            units_lost = -int(rs_change)
        else:
            units_lost = 0

        pct_lost = (
            round(units_lost / earliest_val * 100, 1)
            if earliest_val and earliest_val > 0
            else None
        )

        # RS-001 evaluation — both signals must be satisfied
        signal_a = rs_change is not None and rs_change < 0
        signal_b = bool(rs_deregulating)
        deregulating = signal_a and signal_b

        rule = _load_rule_from_graph()
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "deregulating":         deregulating,
            "insufficient_data":    False,
            "no_rs_history":        False,
            "signal_a_satisfied":   signal_a,
            "signal_b_satisfied":   signal_b,
            "units_lost":           units_lost,
            "pct_lost":             pct_lost,
            "earliest_year":        earliest_year,
            "latest_year":          latest_year,
            "rs_change":            rs_change,
            "rs_deregulating":      rs_deregulating,
            "interpretive_status":  "Inferred",
            "threshold_statement":  rule.get("threshold_description", _THRESHOLD_FALLBACK),
            "authority":            rule.get("authority", ""),
            "effective_date":       rule.get("effective_date", ""),
            "author":               rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
