"""ACRIS deed and mortgage chains. Phase 4 Tier 3.

`trace_ownership_chain(bbl)` walks a building's ACRIS record — deeds, mortgages,
and the `REFERENCES` links between a mortgage and its satisfaction or assignment —
to show the transaction history and whether each mortgage is still outstanding.

Two facts from the graph shape it (validated live):

* **ACRIS events carry no status field.** Whether a mortgage is outstanding is
  derived from whether a `MortgageSatisfaction` *references* it, not read from a
  column (P4-5).
* **`REFERENCES` is stored in both directions** between related documents
  (`ref_type` ∈ {CRFN, DOCID}), so it is matched **undirected**.

Type I — every element is a directly-sourced ACRIS record.
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged

__all__ = ["trace_ownership_chain", "TRACE_OWNERSHIP_CHAIN_DESCRIPTION"]

#: Hard cap on events returned; the total is always reported alongside.
_MAX_EVENTS = 60

TRACE_OWNERSHIP_CHAIN_DESCRIPTION = (
    "Trace a building's ACRIS deed and mortgage history by BBL: transfers and "
    "mortgages in date order, and for each mortgage whether it is still "
    "outstanding or has been satisfied (paid off) or assigned. Use for 'trace the "
    "ownership/mortgage history', 'when was it last sold', 'is the mortgage still "
    "outstanding'. Takes a 10-digit BBL."
)

_CHAIN_CYPHER = (
    "MATCH (b:Building {bbl: $bbl}) "
    "OPTIONAL MATCH (b)-[:HAS_EVENT]->(e:Event) WHERE e.source_name = 'ACRIS' "
    "OPTIONAL MATCH (e)-[:REFERENCES]-(ref:Event) "
    "  WHERE e.event_type = 'Mortgage' "
    "  AND ref.event_type IN ['MortgageSatisfaction', 'MortgageAssignment'] "
    "WITH b, e, collect(DISTINCT {event_type: ref.event_type, event_id: ref.event_id, "
    "  event_date: toString(ref.event_date)}) AS refs "
    "ORDER BY e.event_date "
    "WITH b, collect(CASE WHEN e IS NULL THEN NULL ELSE {"
    "  event_id: e.event_id, event_type: e.event_type, "
    "  event_date: toString(e.event_date), doc_type: e.violation_class, refs: refs} "
    "END) AS all_events "
    "RETURN b.bbl AS bbl, [ev IN all_events WHERE ev IS NOT NULL] AS events"
)


def _annotate(event: dict[str, Any]) -> dict[str, Any]:
    """Add an outstanding/satisfied status to a mortgage from its references."""
    if event["event_type"] != "Mortgage":
        return event
    refs = event.get("refs") or []
    satisfied = any(r["event_type"] == "MortgageSatisfaction" for r in refs)
    assigned = any(r["event_type"] == "MortgageAssignment" for r in refs)
    event["outstanding"] = not satisfied
    event["status"] = "satisfied" if satisfied else "outstanding"
    event["assigned"] = assigned
    return event


@tagged(["Building", "HAS_EVENT", "Event", "REFERENCES"])
def trace_ownership_chain(bbl: str) -> dict[str, Any]:
    """Return a building's ACRIS deed/mortgage chain in date order. Type I.

    Deeds and mortgages are returned separately, each mortgage annotated with its
    ``outstanding`` status (derived from a referencing ``MortgageSatisfaction``,
    since ACRIS events carry no status field). Capped at :data:`_MAX_EVENTS` with
    the true totals reported.
    """
    import re

    if not isinstance(bbl, str) or not re.match(r"^[1-5][0-9]{9}$", bbl.strip()):
        return {"found": False, "bbl": bbl if isinstance(bbl, str) else repr(bbl),
                "reason": "Not a valid BBL (10 digits, borough 1-5)."}
    row = read(_CHAIN_CYPHER, {"bbl": bbl.strip()}).single
    if row is None:
        return {"found": False, "bbl": bbl.strip(),
                "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}

    events = [_annotate(dict(e)) for e in row["events"]]
    deeds = [e for e in events if e["event_type"] == "DeedTransfer"]
    mortgages = [e for e in events if e["event_type"] == "Mortgage"]
    outstanding = [m for m in mortgages if m["outstanding"]]

    return {
        "found": True, "bbl": row["bbl"],
        "summary": {
            "total_acris_events": len(events),
            "deed_count": len(deeds),
            "mortgage_count": len(mortgages),
            "outstanding_mortgage_count": len(outstanding),
            "latest_deed_date": deeds[-1]["event_date"] if deeds else None,
        },
        "deeds": deeds[:_MAX_EVENTS],
        "mortgages": mortgages[:_MAX_EVENTS],
        "truncated": len(deeds) > _MAX_EVENTS or len(mortgages) > _MAX_EVENTS,
    }
