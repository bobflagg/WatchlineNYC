"""
watchline/fw/intents/geographic_concentration.py

Intent: GeographicConcentration
Rule:   None — data retrieval only. Aggregates pre-computed PHC-001 claims
        by borough.

Dataset-level query, like WorstFirst. The router bypasses entity resolution.
Optional $borough param filters to a single borough; null returns all boroughs.

The intent extractor's `borough` field is used directly — the LLM extracts
"Bronx", "Brooklyn", etc. from the question. If no borough is mentioned,
$borough is null and all boroughs are returned.
"""

from watchline.fw.intents.base import IntentHandler

# Canonical borough names as stored in Building nodes
_BOROUGH_MAP = {
    "bronx":        "Bronx",
    "the bronx":    "Bronx",
    "brooklyn":     "Brooklyn",
    "bklyn":        "Brooklyn",
    "manhattan":    "Manhattan",
    "queens":       "Queens",
    "staten island": "Staten Island",
    "si":           "Staten Island",
    "richmond":     "Staten Island",
}


def _normalize_borough(raw: str | None) -> str | None:
    """Normalize a raw borough string to the canonical form used in Building nodes.
    Returns None for any string not recognized as a valid borough — unrecognized
    strings produce a city-wide (unfiltered) query rather than an empty result.
    """
    if not raw:
        return None
    return _BOROUGH_MAP.get(raw.lower().strip())  # None if not a known borough


_CYPHER = """
// Start from PHC Claims — Building.bbl IS KEY so each lookup is O(1)
MATCH (phc:Claim {interpretive_concept: "PersistentHazardousConditions"})
MATCH (b:Building {bbl: phc.subject_id})
WHERE $borough IS NULL OR b.borough = $borough

// Order by units before collecting so top_buildings contains largest first
WITH b
ORDER BY COALESCE(b.residential_units, 0) DESC

WITH b.borough                                AS borough,
  count(DISTINCT b.bbl)                       AS phc_buildings,
  sum(COALESCE(b.residential_units, 0))       AS affected_units,
  collect({
    bbl:     b.bbl,
    address: b.address,
    units:   b.residential_units
  })[..15]                                    AS top_buildings

RETURN borough, phc_buildings, affected_units, top_buildings
ORDER BY phc_buildings DESC
"""


class GeographicConcentrationHandler(IntentHandler):

    intent_category = "GeographicConcentration"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        # Prefer the structured `borough` field; fall back to entity_raw
        raw = intent.get("borough") or intent.get("entity_raw")
        return {"borough": _normalize_borough(raw)}

    def evaluate(self, raw_results: list) -> dict | None:
        return None
