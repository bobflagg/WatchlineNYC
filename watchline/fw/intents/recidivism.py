"""
watchline/fw/intents/recidivism.py

Intent: Recidivism
Rule:   RCV-001 (RUL-00013)

Evaluates whether an actor has allowed hazardous conditions to persist
repeatedly across their portfolio — either in multiple boroughs (structural
neglect) or over multiple years (chronic neglect).

Two signals, either sufficient:
  A. Multi-borough: PHC-flagged buildings in > 1 borough
  B. Multi-year:    buildings with Class C violations open since >= 3 years ago
"""

from watchline.fw.intents.base import IntentHandler
from watchline.fw.connections import neo4j_query

import datetime

_GRAPH_RULE_ID     = "RUL-00013"
_RULE_ID           = "RCV-001"
_RULE_VERSION      = "1.0"
_THRESHOLD_BOROUGHS = 1   # > this many boroughs triggers signal A
_THRESHOLD_YEARS   = 3    # >= this many years triggers signal B

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
            "rule_id":   _GRAPH_RULE_ID,
            "name":      _RULE_ID,
            "title":     "Recidivism",
            "version":   _RULE_VERSION,
            "threshold_description": (
                "An actor satisfies Rule RCV-001 if: (1) PHC-flagged buildings span "
                "more than one borough; OR (2) one or more buildings have an open "
                "Class C violation first opened 3 or more years ago."
            ),
        })
    return _rule_cache


_CYPHER = """
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (bc:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
MATCH (bc)-[:INVOLVES_BUILDING]->(b:Building)

// PHC claim for this building
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions",
  subject_id: b.bbl
})

// Oldest currently-open Class C violation per building
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v:Event {
  event_type: "Violation", source_name: "HPD",
  violation_class: "C", status: "Open"
})
WHERE v.open_date IS NOT NULL

WITH a, b, phc,
  count(DISTINCT v)                                                    AS open_c_count,
  min(CASE WHEN v IS NOT NULL THEN v.open_date.year ELSE null END)     AS first_open_c_year

WITH a,
  count(DISTINCT b.bbl)                                                                   AS portfolio_size,
  count(DISTINCT CASE WHEN phc IS NOT NULL THEN b.bbl END)                               AS phc_buildings,
  count(DISTINCT CASE WHEN phc IS NOT NULL THEN b.borough END)                           AS phc_borough_count,
  collect(DISTINCT CASE WHEN phc IS NOT NULL THEN b.borough END)                         AS phc_boroughs,
  count(DISTINCT CASE WHEN first_open_c_year IS NOT NULL
    AND (date().year - first_open_c_year) >= $years THEN b.bbl END)                      AS multi_year_buildings,
  collect(CASE WHEN phc IS NOT NULL
    OR (first_open_c_year IS NOT NULL AND (date().year - first_open_c_year) >= $years)
    THEN {
      bbl:           b.bbl,
      address:       b.address,
      borough:       b.borough,
      units:         b.residential_units,
      has_phc:       CASE WHEN phc IS NOT NULL THEN true ELSE false END,
      years_with_open_c: CASE WHEN first_open_c_year IS NOT NULL
                         THEN (date().year - first_open_c_year) ELSE 0 END
    } END)                                                                                AS notable_buildings

RETURN a.display_name    AS name,
       a.canonical_id    AS canonical_id,
       portfolio_size,
       phc_buildings,
       phc_borough_count,
       phc_boroughs,
       multi_year_buildings,
       notable_buildings
"""


class RecidivismHandler(IntentHandler):

    intent_category = "Recidivism"
    entity_class    = "actor"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {
            "canonical_id": intent["canonical_id"],
            "years":        _THRESHOLD_YEARS,
        }

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return {
                "rule_id":             _RULE_ID,
                "rule_version":        _RULE_VERSION,
                "interpretive_status": "Inferred",
                "insufficient_data":   True,
                "recidivist":          False,
                "signal_a":            False,
                "signal_b":            False,
                "phc_borough_count":   0,
                "multi_year_buildings": 0,
                "threshold_statement": _load_rule_from_graph().get("threshold_description", ""),
            }

        r                 = raw_results[0]
        phc_borough_count = int(r.get("phc_borough_count") or 0)
        multi_year_bldgs  = int(r.get("multi_year_buildings") or 0)
        phc_buildings     = int(r.get("phc_buildings") or 0)
        portfolio_size    = int(r.get("portfolio_size") or 0)

        signal_a  = phc_borough_count > _THRESHOLD_BOROUGHS   # > 1 borough
        signal_b  = multi_year_bldgs > 0                      # any multi-year building
        recidivist = signal_a or signal_b

        notable = [x for x in (r.get("notable_buildings") or []) if x is not None]

        rule = _load_rule_from_graph()
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         _RULE_VERSION,
            "interpretive_status":  "Inferred",
            "insufficient_data":    portfolio_size == 0,
            "recidivist":           recidivist,
            "signal_a":             signal_a,
            "signal_b":             signal_b,
            "phc_borough_count":    phc_borough_count,
            "phc_boroughs":         list(r.get("phc_boroughs") or []),
            "multi_year_buildings": multi_year_bldgs,
            "phc_buildings":        phc_buildings,
            "portfolio_size":       portfolio_size,
            "affected_buildings":   notable,
            "threshold_statement":  rule.get("threshold_description", ""),
            "threshold_logic":      rule.get("threshold_logic", ""),
            "rule_title":           rule.get("title", "Recidivism"),
            "authority":            rule.get("authority", ""),
        }
