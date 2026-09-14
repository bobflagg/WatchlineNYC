"""eval/manifest.py — shared frame-manifest helpers.

`snapshot_D()` derives the protocol §8 snapshot date `D` (the source-data vintage)
from the graph's ingest-currency ceiling — NOT from a build timestamp. Both
`sample.py` (accuracy frame) and `cutover_frame.py` (Track-A cutover frame) use it,
so the two `frame_manifest.json` files carry a consistent, unambiguous `D`.

Rationale: `date.today()` is the BUILD date, not the data vintage. The graph can be
built/sampled days after its last source ingest (it was: the 08-17 ingest fed both the
09-05 accuracy frame and the 09-07 cutover run), so `D` must come from the data, not the
clock. See specs/eval-protocol.md §8 ("Fix a snapshot date D … note it in the paper").
"""
from __future__ import annotations

import subprocess


def git_sha() -> str:
    """Short HEAD sha, or 'unknown' if git is unavailable."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def snapshot_D(driver, database: str) -> dict:
    """Protocol §8 snapshot date D, derived from the graph ingest-currency ceiling.

    D = the date of the latest write across ingested source rows (buildings + events).
    Returns the ``snapshot_D`` block to embed in a frame manifest.
    """
    q = (
        "CALL () { MATCH (b:Building) RETURN max(b.updated_at) AS bu, max(b.created_at) AS bc, count(*) AS n } "
        "CALL () { MATCH (e:Event) RETURN max(e.created_at) AS ec } "
        "RETURN bu, bc, n, ec"
    )
    with driver.session(database=database) as s:
        r = s.run(q).single()
    bu = str(r["bu"]) if r["bu"] is not None else None
    bc = str(r["bc"]) if r["bc"] is not None else None
    ec = str(r["ec"]) if r["ec"] is not None else None
    ceiling = max([x for x in (bu, ec) if x], default=None)   # ISO8601 strings sort chronologically
    return {
        "as_of_date": ceiling[:10] if ceiling else None,
        "meaning": (
            "Protocol §8 snapshot date D — the source-data vintage both systems' decisions and all "
            "adjudication evidence are evaluated as of. Derived from the graph ingest-currency ceiling, "
            "not a build timestamp."
        ),
        "evidence": {
            "max_building_updated_at": bu,
            "max_building_created_at": bc,
            "max_event_created_at": ec,
            "buildings": r["n"],
            "snapshot_marker_node": "none (D derived from ingest-currency ceilings)",
        },
    }
