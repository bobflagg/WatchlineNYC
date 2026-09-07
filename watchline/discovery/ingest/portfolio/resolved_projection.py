"""resolved_projection.py — C5 building projection for ResolvedEntityV2 (Option B, Phase 2).

Applies the **co-op/condo exclusion at the PROJECTION layer**, not in identity (F2). Co-ops/condos are
owned by shareholders/unit-owners, not a landlord, so they are excluded from an entity's *ownership
attribution* (building_count = rental only) — but the entity is **never dropped from identity** (it is a
resolved party regardless of what it owns). This is the layered fix for the legacy conflation, where
`owner_groups` folded the co-op/condo exclusion into the grouping itself (F2: `v2_only = 428`).

A resolved entity dominated by co-op/condo buildings (>50%) is *flagged* (`coop_condo_dominated`) — a
management artifact for ownership purposes — but stays a first-class `:ResolvedEntityV2`.

Pure `project` is hermetic; the read/write are additive and read the `Building.coop_condo` flag set by
`coop_condo.py`. (Fuller C5 — source-qualified latest-observed HPD/deed claims with dates — is separate.)
"""
from __future__ import annotations


def project(total: int, rental: int) -> dict:
    """Pure: from an entity's total and rental (non-co-op/condo) building counts, the C5 attribution."""
    coop_condo = total - rental
    return {"total_building_count": total, "building_count": rental,
            "coop_condo_count": coop_condo,
            "coop_condo_dominated": total > 0 and 2 * rental < total}   # >50% co-op/condo


# building_count is RENTAL only (co-op/condo excluded from ownership attribution); total keeps the full
# footprint for the dominance flag. Mirrors owner_groups._BUILDING_COUNT, applied to the v2 layer.
_Q_PROJECTION = """
MATCH (l:Landlord)-[:IN_RESOLVED_ENTITY_V2 {run_id: $run_id}]->(e:ResolvedEntityV2)
UNWIND l.bbls AS bbl
OPTIONAL MATCH (b:Building {bbl: bbl})
WITH e, bbl, coalesce(b.coop_condo, false) AS cc
WITH e, count(DISTINCT bbl) AS total,
     count(DISTINCT CASE WHEN NOT cc THEN bbl END) AS rental
RETURN e.resolution_id AS rid, total, rental
"""


def read_projection(driver, *, database: str, run_id: str) -> list[dict]:
    """Per-entity C5 projection for a materialized run — read-only."""
    with driver.session(database=database) as s:
        rows = [r.data() for r in s.run(_Q_PROJECTION, run_id=run_id)]
    return [{"resolution_id": r["rid"], **project(r["total"], r["rental"])} for r in rows]


_WRITE = """
UNWIND $batch AS row
MATCH (e:ResolvedEntityV2 {resolution_id: row.resolution_id, run_id: $run_id})
SET e.total_building_count = row.total_building_count,
    e.building_count = row.building_count,
    e.coop_condo_dominated = row.coop_condo_dominated
"""


def write_projection(driver, *, database: str, run_id: str, batch_size: int = 5000) -> dict:
    """Stamp additive C5 projection props (building_count / total_building_count / coop_condo_dominated)
    onto each :ResolvedEntityV2 of `run_id`. Additive; never drops an entity. Returns run stats."""
    rows = read_projection(driver, database=database, run_id=run_id)
    with driver.session(database=database) as s:
        for i in range(0, len(rows), batch_size):
            s.run(_WRITE, batch=rows[i:i + batch_size], run_id=run_id)
    dominated = sum(1 for r in rows if r["coop_condo_dominated"])
    return {"run_id": run_id, "entities": len(rows), "coop_condo_dominated": dominated}
