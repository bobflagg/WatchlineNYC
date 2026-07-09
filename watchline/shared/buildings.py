"""
watchline/shared/buildings.py

Canonical PLUTO-first Building node ingestion shared by both KGs.

Both the evidentiary and discovery graphs call load_pluto() and load_backfill()
from their own thin pipeline wrappers that supply the correct Neo4j session.

Coverage strategy: pluto_latest (~858K lots) is the authoritative substrate.
Registration BBLs missing from PLUTO are backfilled as minimal nodes so that
every hpd_registrations row has a landing node.

Borough is always derived from the BBL first digit (ADR-002); source-table
borough strings are never used.
"""

from datetime import datetime, timezone
from typing import Iterator, List

from psycopg2.extras import RealDictCursor

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.bbl import borough_from_bbl


PLUTO_SQL = """
SELECT
    trim(bbl)        AS bbl,
    address          AS address,
    latitude         AS latitude,
    longitude        AS longitude,
    unitsres         AS residential_units,
    yearbuilt        AS year_built,
    trim(bldgclass)  AS building_class
FROM pluto_latest
WHERE bbl IS NOT NULL AND trim(bbl) <> ''
"""

BACKFILL_SQL = """
SELECT DISTINCT trim(r.bbl) AS bbl
FROM hpd_registrations r
WHERE r.bbl IS NOT NULL AND trim(r.bbl) <> ''
  AND NOT EXISTS (
      SELECT 1 FROM pluto_latest p WHERE trim(p.bbl) = trim(r.bbl)
  )
"""

_MERGE_PLUTO = """
UNWIND $batch AS b
MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
SET bld.address           = b.address,
    bld.borough           = b.borough,
    bld.latitude          = b.latitude,
    bld.longitude         = b.longitude,
    bld.residential_units = b.residential_units,
    bld.year_built        = b.year_built,
    bld.building_class    = b.building_class,
    bld.updated_at        = datetime($now),
    bld.created_at        = CASE WHEN bld.created_at IS NULL
                                 THEN datetime($now) ELSE bld.created_at END
"""

_MERGE_BACKFILL = """
UNWIND $batch AS b
MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
SET bld.borough    = b.borough,
    bld.updated_at = datetime($now),
    bld.created_at = CASE WHEN bld.created_at IS NULL
                          THEN datetime($now) ELSE bld.created_at END
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pluto_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="pluto_buildings", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(PLUTO_SQL)
        batch: List[dict] = []
        for row in cur:
            bbl = row["bbl"]
            yb = row["year_built"]
            bc = (row["building_class"] or "").strip() or None
            batch.append({
                "bbl":               bbl,
                "address":           (row["address"] or "").strip() or None,
                "borough":           borough_from_bbl(bbl),
                "latitude":          float(row["latitude"]) if row["latitude"] is not None else None,
                "longitude":         float(row["longitude"]) if row["longitude"] is not None else None,
                "residential_units": row["residential_units"],
                "year_built":        yb if yb else None,
                "building_class":    bc,
            })
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def _backfill_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="backfill_buildings", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(BACKFILL_SQL)
        batch: List[dict] = []
        for row in cur:
            bbl = row["bbl"]
            batch.append({"bbl": bbl, "borough": borough_from_bbl(bbl)})
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_pluto(session, conn) -> int:
    """Write Building nodes from pluto_latest. MERGE on bbl — idempotent."""
    now = _now()
    total = 0
    for batch in _pluto_batches(conn):
        session.run(_MERGE_PLUTO, batch=batch, now=now)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"    {total:,} buildings written ...")
    return total


def load_backfill(session, conn) -> int:
    """Minimal Building nodes for registration BBLs absent from PLUTO."""
    now = _now()
    total = 0
    for batch in _backfill_batches(conn):
        session.run(_MERGE_BACKFILL, batch=batch, now=now)
        total += len(batch)
    return total
