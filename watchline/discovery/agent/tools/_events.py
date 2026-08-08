"""Shared event-aggregation helpers, so the building and portfolio aggregate
tools roll up ``(status, class, count)`` rows identically.

Not a tool module — no ``@tagged`` functions here. Just the canonicalization
rollup, kept in one place so a fix to how statuses are counted lands everywhere.
"""

from __future__ import annotations

from typing import Any

from ..vocab import (
    HPD_HAZARD_CLASSES,
    HPD_VIOLATION_CLASSES,
    OPEN_STATUSES,
    ClassScheme,
    EventType,
    Source,
    canonical_status,
    class_schemes_for,
)

__all__ = ["rollup_events", "hazard_coverage_note"]


def rollup_events(source: Source, event_type: EventType, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll ``(status, cls, c)`` rows into totals, breakdowns, and percent-open.

    Every raw status is canonicalized through :mod:`..vocab`, so ``'OPEN'``
    (complaints) and ``'Open'`` (violations) both count as open without the
    caller knowing that casing difference exists. For HPD violations each class
    carries its label and hazard flag, so a breakdown can exclude the
    administrative Class I from a hazard count.
    """
    total = 0
    by_status: dict[str, int] = {}
    open_count = 0
    by_class: dict[str, dict[str, Any]] = {}
    is_hpd_violation = source is Source.HPD and event_type is EventType.VIOLATION

    for row in rows:
        count = row["c"]
        total += count
        status = canonical_status(source, event_type, row["status"])
        by_status[status.value] = by_status.get(status.value, 0) + count
        is_open = status in OPEN_STATUSES
        if is_open:
            open_count += count
        cls = row["cls"]
        if cls is not None:
            entry = by_class.setdefault(cls, {"count": 0, "open_count": 0})
            entry["count"] += count
            if is_open:
                entry["open_count"] += count
            if is_hpd_violation and cls in HPD_VIOLATION_CLASSES:
                entry["label"] = HPD_VIOLATION_CLASSES[cls].label
                entry["is_hazard"] = HPD_VIOLATION_CLASSES[cls].is_hazard

    return {
        "total": total,
        "by_status": by_status,
        "open_count": open_count,
        "percent_open": round(100 * open_count / total, 1) if total else None,
        "by_class": by_class,
        "hpd_hazard_classes": sorted(HPD_HAZARD_CLASSES) if is_hpd_violation else None,
    }


def hazard_coverage_note(source: Source, event_type: EventType) -> str | None:
    """A disclosure when the hazard scheme covers only part of a source.

    ECB ``Judgment`` mixes a numeric class scheme and a hazard scheme in one
    column, and the hazard labels cover only ~35% of ECB judgments — so a
    hazard-filtered ECB aggregate is reporting a minority of the data and must
    say so (roadmap OQ8).
    """
    schemes = class_schemes_for(source, event_type)
    if ClassScheme.ECB_HAZARD in schemes and ClassScheme.ECB_CLASS_NUMBER in schemes:
        return (
            "ECB encodes both a numeric class and a hazard label in one field; the "
            "hazard scheme covers only ~35% of ECB judgments, so a hazard breakdown "
            "reflects a minority of the data."
        )
    return None
