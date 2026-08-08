"""Building facts and events — Tier-1 lookups and a Tier-2 aggregate. Phase 3.

Three tools keyed on ``bbl``:

* :func:`lookup_building` — the building's own record (Type I).
* :func:`lookup_building_events` — its events, filtered by source/type/status/
  class/date, or the single most recent (Type I).
* :func:`aggregate_building_events` — counts and breakdowns over its events
  (Type II is *not* involved; still Type I). *(Added in group 2.)*

**Every event query goes through :mod:`..vocab`.** ``event_type`` is coarse —
``'Violation'`` spans HPD *and* DOB, whose ``violation_class`` codebooks collide
on A/B/C — and ``status`` casing differs by type. So a source is mandatory
(``require_pair``), and status/class filters are built by ``vocab`` rather than
by raw equality, which would silently return the wrong rows.

Dates are returned with ``toString`` so the payload is plain JSON — a neo4j
``Date`` is not serializable, and a "most recent" date is often the whole answer.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import read
from ..reliability import tagged
from ..vocab import (
    OPEN_STATUSES,
    Status,
    VocabularyError,
    canonical_class,
    canonical_status,
    class_filter,
    require_pair,
    status_filter,
)
from ._events import rollup_events

__all__ = [
    "lookup_building",
    "lookup_building_events",
    "aggregate_building_events",
    "LOOKUP_BUILDING_DESCRIPTION",
    "LOOKUP_BUILDING_EVENTS_DESCRIPTION",
    "AGGREGATE_BUILDING_EVENTS_DESCRIPTION",
]

_BBL_PATTERN = re.compile(r"^[1-5][0-9]{9}$")

#: Default cap on events returned in a sample. Large event sets return a count
#: plus this many rows, never the whole list (CLAUDE.md).
_DEFAULT_LIMIT = 20


LOOKUP_BUILDING_DESCRIPTION = (
    "Look up a building's own record by BBL: address, borough, residential unit "
    "count, year built, building class, zoning district, and recorded owner. Call "
    "this for factual questions about a single building that are not about its "
    "violations, complaints, sales, or ownership inference. Takes a 10-digit BBL."
)

LOOKUP_BUILDING_EVENTS_DESCRIPTION = (
    "List or find a building's public-record events (HPD/DOB violations, HPD "
    "complaints, vacate orders, ACRIS deeds and mortgages, ECB judgments, housing "
    "court filings, evictions). Requires the source (HPD, DOB, ACRIS, ECB, "
    "HPD-Litigations, Marshal) and event type, because the same event_type and "
    "class codes mean different things across sources. Use most_recent=true for "
    "'last sold' (ACRIS DeedTransfer) or 'latest complaint'. Filter open items "
    "with status='open'. Takes a 10-digit BBL."
)

_BUILDING_CYPHER = (
    "MATCH (b:Building {bbl: $bbl}) "
    "RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough, "
    "b.residential_units AS residential_units, b.year_built AS year_built, "
    "b.building_class AS building_class, b.dof_zonedist1 AS zoning, "
    "b.dof_ownername AS recorded_owner, b.bin AS bin, "
    "b.latitude AS latitude, b.longitude AS longitude"
)


def _invalid_bbl(bbl: Any) -> dict[str, Any]:
    return {
        "found": False,
        "bbl": bbl if isinstance(bbl, str) else repr(bbl),
        "reason": "Not a valid BBL. Expected 10 digits: borough (1-5), 5-digit "
        "block, 4-digit lot — for example '1000050010'.",
    }


@tagged(["Building"])
def lookup_building(bbl: str) -> dict[str, Any]:
    """Return a building's own record. Type I — directly-sourced fields only.

    ``zoning`` is ``Building.dof_zonedist1`` (the DOF zoning district);
    ``recorded_owner`` is ``dof_ownername`` (may be a shell entity — for the
    apparent controller too, use ``lookup_building_ownership``). ``address`` is a
    display field, never a key.
    """
    if not isinstance(bbl, str) or not _BBL_PATTERN.match(bbl.strip()):
        return _invalid_bbl(bbl)
    row = read(_BUILDING_CYPHER, {"bbl": bbl.strip()}).single
    if row is None:
        return {"found": False, "bbl": bbl.strip(),
                "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}
    return {"found": True, **row}


def _resolve_statuses(source, event_type, status: str) -> set[Status]:
    """Interpret a status argument as canonical status(es).

    ``'open'`` means "outstanding right now" (:data:`OPEN_STATUSES`); any other
    value must name a canonical :class:`Status`. Invalid values raise, so the
    tool can report the valid set rather than silently matching nothing.
    """
    if status.strip().lower() == "open":
        return set(OPEN_STATUSES)
    try:
        return {Status(status.strip().upper())}
    except ValueError as exc:
        valid = ", ".join(s.value for s in Status)
        raise VocabularyError(
            f"Unknown status {status!r}; use 'open' or one of: {valid}"
        ) from exc


def _interpret_event(source, event_type, row: dict[str, Any]) -> dict[str, Any]:
    """Attach canonical status/class to a raw event row."""
    scheme, class_value = canonical_class(source, event_type, row.get("violation_class"))
    return {
        "event_id": row.get("event_id"),
        "event_date": row.get("event_date"),  # already toString'd
        "status_raw": row.get("status"),
        "status": canonical_status(source, event_type, row.get("status")).value,
        "violation_class_raw": row.get("violation_class"),
        "class_scheme": scheme.value if scheme else None,
    }


@tagged(["Building", "HAS_EVENT", "Event"])
def lookup_building_events(
    bbl: str,
    source_name: str,
    event_type: str,
    status: str | None = None,
    violation_class: str | None = None,
    since_months: int | None = None,
    most_recent: bool = False,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Find a building's events for one ``(source_name, event_type)`` pair.

    Type I. ``require_pair`` makes the source mandatory; ``status`` and
    ``violation_class`` are matched through :mod:`..vocab`, never raw equality.

    * ``status='open'`` → outstanding items (OPEN/PENDING), source-aware.
    * ``most_recent=True`` → the single latest event by ``event_date``, with a
      ``date_anomaly`` flag when that date is in the future (a real data defect —
      surfaced, never clamped) and null dates excluded from the ordering.
    * otherwise → a capped list plus the ``total`` count.
    """
    if not isinstance(bbl, str) or not _BBL_PATTERN.match(bbl.strip()):
        return _invalid_bbl(bbl)
    try:
        source, etype = require_pair(source_name, event_type)
        preds = ["e.source_name = $source", "e.event_type = $type"]
        params: dict[str, Any] = {"bbl": bbl.strip(), "source": source.value,
                                  "type": etype.value, "limit": max(1, int(limit))}
        if status is not None:
            # Distinct param names per filter — the default 'vals' collides when
            # a query applies both a status and a class filter (each would emit
            # $vals_exact, and the second silently overwrites the first).
            frag, p = status_filter(
                source, etype, _resolve_statuses(source, etype, status)
            ).to_cypher("e.status", param="statusv")
            preds.append(frag)
            params.update(p)
        if violation_class is not None:
            frag, p = class_filter(source, etype, {violation_class}).to_cypher(
                "e.violation_class", param="classv")
            preds.append(frag)
            params.update(p)
    except VocabularyError as exc:
        return {"found": False, "bbl": bbl.strip() if isinstance(bbl, str) else repr(bbl),
                "error": "invalid_event_filter", "reason": str(exc)}

    if since_months is not None:
        preds.append("e.event_date >= date() - duration({months: $since_months})")
        params["since_months"] = int(since_months)
    if most_recent:
        preds.append("e.event_date IS NOT NULL")
    where = " AND ".join(preds)

    cypher = (
        "MATCH (b:Building {bbl: $bbl}) "
        f"OPTIONAL MATCH (b)-[:HAS_EVENT]->(e:Event) WHERE {where} "
        "WITH b, e ORDER BY e.event_date DESC "
        "WITH b, [ev IN collect(e) WHERE ev IS NOT NULL | {"
        "event_id: ev.event_id, event_date: toString(ev.event_date), "
        "status: ev.status, violation_class: ev.violation_class}] AS events "
        "RETURN b.bbl AS bbl, size(events) AS total, events[..$limit] AS sample"
    )
    row = read(cypher, params).single
    if row is None:
        return {"found": False, "bbl": bbl.strip(),
                "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}

    events = [_interpret_event(source, etype, ev) for ev in row["sample"]]
    result: dict[str, Any] = {
        "found": True, "bbl": row["bbl"],
        "source_name": source.value, "event_type": etype.value,
        "total": row["total"],
    }
    if most_recent:
        top = events[0] if events else None
        result["most_recent"] = top
        result["date_anomaly"] = bool(top and _is_future(top["event_date"]))
        if result["date_anomaly"]:
            result["date_anomaly_note"] = (
                "The most recent event carries a future date, which is a data "
                "defect in the source record — reported as-is, not corrected."
            )
    else:
        result["events"] = events
        result["truncated"] = row["total"] > len(events)
    return result


def _is_future(iso_date: str | None) -> bool:
    """Whether an ISO date string is after today. Purely lexical — ISO dates
    sort correctly as strings, so no date parsing is needed."""
    if not iso_date:
        return False
    from datetime import date

    return iso_date > date.today().isoformat()


AGGREGATE_BUILDING_EVENTS_DESCRIPTION = (
    "Summarise a building's events for one source and type: a total, a breakdown "
    "by status (with the percentage open), and a class breakdown. Requires the "
    "source (HPD, DOB, ACRIS, ECB, HPD-Litigations, Marshal) and event type. Use "
    "for 'how many …', 'what percentage are open', and violation-class counts on "
    "a single building. For open Class C HPD violations, read the OPEN count under "
    "class C in the breakdown. Optional violation_class narrows to one class; "
    "since_months limits to recent events. Takes a 10-digit BBL."
)


@tagged(["Building", "HAS_EVENT", "Event"])
def aggregate_building_events(
    bbl: str,
    source_name: str,
    event_type: str,
    violation_class: str | None = None,
    since_months: int | None = None,
) -> dict[str, Any]:
    """Counts and breakdowns for one building's events. Type I.

    Returns a ``total``, a ``by_status`` breakdown (canonical statuses),
    ``percent_open`` (from :data:`..vocab.OPEN_STATUSES`), and a ``by_class``
    breakdown carrying an OPEN count per class — so "open Class C" is
    ``by_class['C']['open_count']``. For HPD violations each class is labelled
    and flagged as a hazard (A/B/C) or informational (I). Never returns raw rows.
    """
    if not isinstance(bbl, str) or not _BBL_PATTERN.match(bbl.strip()):
        return _invalid_bbl(bbl)
    try:
        source, etype = require_pair(source_name, event_type)
        preds = ["e.source_name = $source", "e.event_type = $type"]
        params: dict[str, Any] = {"bbl": bbl.strip(), "source": source.value, "type": etype.value}
        if violation_class is not None:
            frag, p = class_filter(source, etype, {violation_class}).to_cypher("e.violation_class")
            preds.append(frag)
            params.update(p)
    except VocabularyError as exc:
        return {"found": False, "bbl": bbl.strip() if isinstance(bbl, str) else repr(bbl),
                "error": "invalid_event_filter", "reason": str(exc)}
    if since_months is not None:
        preds.append("e.event_date >= date() - duration({months: $since_months})")
        params["since_months"] = int(since_months)
    where = " AND ".join(preds)

    cypher = (
        "MATCH (b:Building {bbl: $bbl}) "
        f"OPTIONAL MATCH (b)-[:HAS_EVENT]->(e:Event) WHERE {where} "
        "WITH b, e WHERE e IS NOT NULL "
        "RETURN e.status AS status, e.violation_class AS cls, count(e) AS c"
    )
    # A building with no matching events yields zero rows; distinguish that from
    # a missing building with a cheap existence check.
    result = read(cypher, params)
    if not result.records:
        exists = read("MATCH (b:Building {bbl: $bbl}) RETURN b.bbl AS bbl", {"bbl": bbl.strip()}).single
        if exists is None:
            return {"found": False, "bbl": bbl.strip(),
                    "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}

    rollup = rollup_events(source, etype, result.records)
    return {"found": True, "bbl": bbl.strip(), "source_name": source.value,
            "event_type": etype.value, **rollup}
