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
    bld.address    = CASE WHEN bld.address IS NULL THEN "Unknown" ELSE bld.address END,
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
                "address":           (row["address"] or "").strip() or "Unknown",
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


# ---------------------------------------------------------------------------
# Rent stabilization enrichment (ADR-014)
# ---------------------------------------------------------------------------

RENTSTAB_SQL = """
SELECT
    trim(r.ucbbl)  AS bbl,
    r.uc2018,
    r.uc2019,
    r.uc2020,
    r.uc2021,
    r.uc2022,
    r.uc2023,
    r.pdfsoa2023,
    p.address      AS pluto_address,
    p.unitsres     AS residential_units,
    p.yearbuilt    AS year_built,
    p.bldgclass    AS building_class,
    p.latitude,
    p.longitude
FROM rentstab_v2 r
LEFT JOIN pluto_latest p ON p.bbl = trim(r.ucbbl)
WHERE r.ucbbl IS NOT NULL
  AND LENGTH(trim(r.ucbbl)) = 10
ORDER BY r.ucbbl
"""

_MERGE_RENTSTAB = """
UNWIND $batch AS b
MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
SET bld.rs_units_2018   = b.rs_units_2018,
    bld.rs_units_2019   = b.rs_units_2019,
    bld.rs_units_2020   = b.rs_units_2020,
    bld.rs_units_2021   = b.rs_units_2021,
    bld.rs_units_2022   = b.rs_units_2022,
    bld.rs_units_2023   = b.rs_units_2023,
    bld.rs_units_current  = b.rs_units_current,
    bld.rs_units_change   = b.rs_units_change,
    bld.rs_deregulating   = b.rs_deregulating,
    bld.rs_pdfsoa_2023    = b.rs_pdfsoa_2023,
    bld.updated_at        = datetime($now),
    bld.borough           = CASE WHEN bld.borough IS NULL
                                 THEN b.borough ELSE bld.borough END,
    bld.address           = CASE WHEN bld.address IS NULL OR bld.address = ''
                                 THEN b.address ELSE bld.address END,
    bld.latitude          = CASE WHEN bld.latitude IS NULL
                                 THEN b.latitude ELSE bld.latitude END,
    bld.longitude         = CASE WHEN bld.longitude IS NULL
                                 THEN b.longitude ELSE bld.longitude END,
    bld.residential_units = CASE WHEN bld.residential_units IS NULL
                                 THEN b.residential_units
                                 ELSE bld.residential_units END,
    bld.year_built        = CASE WHEN bld.year_built IS NULL
                                 THEN b.year_built ELSE bld.year_built END,
    bld.building_class    = CASE WHEN bld.building_class IS NULL
                                 THEN b.building_class ELSE bld.building_class END,
    bld.created_at        = CASE WHEN bld.created_at IS NULL
                                 THEN datetime($now) ELSE bld.created_at END
"""


def _rentstab_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        print("  Querying rentstab_v2 + pluto_latest ...")
        cur.execute(RENTSTAB_SQL)
        batch: List[dict] = []
        for row in cur:
            bbl = row["bbl"]
            uc2018 = row["uc2018"]
            uc2023 = row["uc2023"]
            if uc2018 is not None and uc2023 is not None:
                rs_change = uc2023 - uc2018
                rs_deregulating = rs_change < 0
            else:
                rs_change = None
                rs_deregulating = False
            batch.append({
                "bbl":               bbl,
                "borough":           borough_from_bbl(bbl) or "Unknown",
                "address":           row["pluto_address"] or "",
                "latitude":          float(row["latitude"]) if row["latitude"] else None,
                "longitude":         float(row["longitude"]) if row["longitude"] else None,
                "residential_units": row["residential_units"],
                "year_built":        row["year_built"],
                "building_class":    (row["building_class"] or "").strip() or None,
                "rs_units_2018":     uc2018,
                "rs_units_2019":     row["uc2019"],
                "rs_units_2020":     row["uc2020"],
                "rs_units_2021":     row["uc2021"],
                "rs_units_2022":     row["uc2022"],
                "rs_units_2023":     uc2023,
                "rs_units_current":  uc2023,
                "rs_units_change":   rs_change,
                "rs_deregulating":   rs_deregulating,
                "rs_pdfsoa_2023":    row["pdfsoa2023"],
            })
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_rentstab(session, conn) -> tuple:
    """Enrich Building nodes with DHCR rent stabilization unit counts.

    MERGE on bbl — idempotent. PLUTO properties are not overwritten if
    already set. Returns (total_processed, deregulating_count).
    """
    now = _now()
    total = 0
    deregulating = 0
    for batch in _rentstab_batches(conn):
        session.run(_MERGE_RENTSTAB, batch=batch, now=now)
        total += len(batch)
        deregulating += sum(1 for b in batch if b["rs_deregulating"])
        if total % 10_000 == 0:
            print(f"    {total:,} buildings enriched ...")
    return total, deregulating


# ---------------------------------------------------------------------------
# DOF ownership / assessment / zoning enrichment
# ---------------------------------------------------------------------------
#
# pluto_latest already backs the core Building substrate (address, units,
# year built, class -- see PLUTO_SQL above), but ownername/ownertype/
# assessland/assesstot/exempttot/zonedist1/landmark/histdist were never
# pulled in. These are additive properties this function is the only writer
# of, so (unlike load_rentstab, which has to defer to whichever pipeline set
# the shared core fields first) there's no "don't overwrite if already set"
# logic needed here -- just SET directly.
#
# Verified directly against pluto_latest (858,602 rows):
#   ownername   857,931 populated (99.9%). Free text -- individuals
#               ("TERRY JEU"), LLCs ("KPS ROCKAWAY LLC"), trusts, etc.
#               Passed through verbatim, including any source formatting
#               quirks (e.g. a sampled trust name has a stray embedded
#               space: "...IRREVOCABLE TRUS T") -- not corrected here.
#   ownertype   6 distinct values. Overwhelmingly blank (823,249 of
#               858,602, ~95.9%) -- blank means private/unspecified
#               ownership, not a data gap, and is normalized to null rather
#               than stored as a literal space character. The remaining 5
#               codes (C, M, O, P, X) were NOT decoded here -- their precise
#               DOF PLUTO data-dictionary meanings were not independently
#               verified in this session, so they are passed through
#               verbatim rather than asserted. Consult DCP's PLUTO data
#               dictionary before building any logic that branches on them.
#   assessland / assesstot / exempttot   858,244 populated (99.96%),
#               populated together (same assessment-roll row).
#   zonedist1   856,769 populated (99.79%).
#   landmark    only 1,490 populated (0.17%) -- rare by construction, not a
#               data quality problem. Verified only 3 values occur:
#               'INDIVIDUAL LANDMARK', 'INDIVIDUAL AND INTERIOR LANDMARK',
#               'INTERIOR LANDMARK'.
#   histdist    31,723 populated (3.7%) -- historic district name text.

DOF_OWNERSHIP_SQL = """
SELECT
    trim(bbl)        AS bbl,
    ownername        AS ownername,
    ownertype        AS ownertype,
    assessland       AS assessland,
    assesstot        AS assesstot,
    exempttot        AS exempttot,
    trim(zonedist1)  AS zonedist1,
    landmark         AS landmark,
    histdist         AS histdist
FROM pluto_latest
WHERE bbl IS NOT NULL AND trim(bbl) <> ''
"""

_MERGE_DOF_OWNERSHIP = """
UNWIND $batch AS b
MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
SET bld.dof_ownername  = b.dof_ownername,
    bld.dof_ownertype  = b.dof_ownertype,
    bld.dof_assessland = b.dof_assessland,
    bld.dof_assesstot  = b.dof_assesstot,
    bld.dof_exempttot  = b.dof_exempttot,
    bld.dof_zonedist1  = b.dof_zonedist1,
    bld.dof_landmark   = b.dof_landmark,
    bld.dof_histdist   = b.dof_histdist,
    bld.updated_at     = datetime($now),
    bld.created_at     = CASE WHEN bld.created_at IS NULL
                              THEN datetime($now) ELSE bld.created_at END
"""


def _dof_ownership_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="pluto_dof_ownership", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(DOF_OWNERSHIP_SQL)
        batch: List[dict] = []
        for row in cur:
            batch.append({
                "bbl":            row["bbl"],
                "dof_ownername":  (row["ownername"] or "").strip() or None,
                "dof_ownertype":  (row["ownertype"] or "").strip() or None,
                "dof_assessland": row["assessland"],
                "dof_assesstot":  row["assesstot"],
                "dof_exempttot":  row["exempttot"],
                "dof_zonedist1":  (row["zonedist1"] or "").strip() or None,
                "dof_landmark":   (row["landmark"] or "").strip() or None,
                "dof_histdist":   (row["histdist"] or "").strip() or None,
            })
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_dof_ownership(session, conn) -> int:
    """Enrich Building nodes with DOF ownership/assessment/zoning data from
    pluto_latest (ownername, ownertype, assessland, assesstot, exempttot,
    zonedist1, landmark, histdist).

    MERGE on bbl — idempotent. Returns total_processed.
    """
    now = _now()
    total = 0
    for batch in _dof_ownership_batches(conn):
        session.run(_MERGE_DOF_OWNERSHIP, batch=batch, now=now)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"    {total:,} buildings enriched ...")
    return total
