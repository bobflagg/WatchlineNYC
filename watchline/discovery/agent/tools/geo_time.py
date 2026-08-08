"""Geo + time event aggregation. Phase 3 Tier 2.

The one aggregation not scoped to a single building, landlord, or portfolio, so
the only one that touches the ~42.3M ``Event`` population directly. It rides the
composite ``Event(source_name, event_type, event_date)`` index, and therefore
**requires a bounded date range** — an unbounded citywide scan is a hung session,
not a slow query (D6/§2.1).

``require_pair`` makes the source mandatory as everywhere else: "how many
violations" is ambiguous until you say HPD or DOB, whose class codes collide.
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged
from ..vocab import VocabularyError, require_pair

__all__ = ["aggregate_events_by_geo_time", "AGGREGATE_EVENTS_BY_GEO_TIME_DESCRIPTION"]

#: Borough names as stored in ``Building.borough``.
_BOROUGHS = frozenset({"Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island"})
_BOROUGH_BY_LOWER = {b.lower(): b for b in _BOROUGHS}

AGGREGATE_EVENTS_BY_GEO_TIME_DESCRIPTION = (
    "Count public-record events across the city or one borough over a date range "
    "— e.g. 'evictions in the Bronx in 2025', 'DOB violations citywide last "
    "month'. Requires the source and event type and a start date (a bounded range "
    "is mandatory). Optional borough (Manhattan, Bronx, Brooklyn, Queens, Staten "
    "Island); omit for citywide. Returns the total and a per-borough breakdown."
)


@tagged(["Building", "HAS_EVENT", "Event"])
def aggregate_events_by_geo_time(
    source_name: str,
    event_type: str,
    date_from: str,
    date_to: str | None = None,
    borough: str | None = None,
) -> dict[str, Any]:
    """Count events by borough over ``[date_from, date_to)``. Type I.

    :param date_from: Inclusive lower bound, ISO ``YYYY-MM-DD``. **Required** —
        this is what keeps the query bounded and index-backed.
    :param date_to: Exclusive upper bound; defaults to today (so "since" ranges
        work). ISO ``YYYY-MM-DD``.
    :param borough: One of the five borough names, or omit for citywide.
    """
    try:
        source, etype = require_pair(source_name, event_type)
    except VocabularyError as exc:
        return {"error": "invalid_event_filter", "reason": str(exc)}
    if not isinstance(date_from, str) or not date_from.strip():
        return {"error": "date_range_required",
                "reason": "A start date (date_from, YYYY-MM-DD) is required so the "
                          "query stays bounded — an unbounded citywide scan is not "
                          "permitted."}

    resolved_borough: str | None = None
    if borough is not None:
        resolved_borough = _BOROUGH_BY_LOWER.get(str(borough).strip().lower())
        if resolved_borough is None:
            return {"error": "invalid_borough",
                    "reason": f"{borough!r} is not a borough. Expected one of: "
                              f"{', '.join(sorted(_BOROUGHS))}, or omit for citywide."}

    params: dict[str, Any] = {
        "source": source.value, "type": etype.value,
        "date_from": date_from.strip(),
        "date_to": (date_to.strip() if isinstance(date_to, str) and date_to.strip() else None),
    }
    borough_pred = ""
    if resolved_borough is not None:
        borough_pred = "AND b.borough = $borough "
        params["borough"] = resolved_borough

    # Upper bound defaults to today (exclusive) when not given.
    upper = "coalesce(date($date_to), date())"
    cypher = (
        "MATCH (b:Building)-[:HAS_EVENT]->(e:Event) "
        "WHERE e.source_name = $source AND e.event_type = $type "
        f"AND e.event_date >= date($date_from) AND e.event_date < {upper} "
        f"{borough_pred}"
        "RETURN b.borough AS borough, count(e) AS c"
    )
    rows = read(cypher, params).records
    by_borough = {row["borough"]: row["c"] for row in rows}
    return {
        "source_name": source.value, "event_type": etype.value,
        "borough": resolved_borough, "date_from": params["date_from"],
        "date_to": params["date_to"],
        "total": sum(by_borough.values()),
        "by_borough": by_borough,
    }
