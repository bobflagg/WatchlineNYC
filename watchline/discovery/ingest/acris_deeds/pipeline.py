"""
Watchline Discovery KG — ACRIS Deeds Ingestion Pipeline
watchline/discovery/ingest/acris_deeds/pipeline.py

Creates the sixth and final Event source in the DISCOVERY knowledge graph (for
now): ACRIS deed conveyances -- real property ownership transfers recorded
with the NYC Department of Finance.

What this pipeline creates:
    Event nodes (event_type='DeedTransfer', source_name='ACRIS'), keyed
    event_id = EVT-ACRIS-<documentid>.
    (Building)-[:HAS_EVENT]->(Event) edges (one per (document, bbl) pair --
    a single deed can convey multiple lots).
    Actor nodes for grantors/grantees, in a NEW identity namespace disjoint
    from the landlord Actor space (see notes/acris-identity.md for the full
    rationale -- short version: ACRIS party data is clean/structured, unlike
    hpd_litigations' respondent blob, so PARTY_TO is worth building here
    even without a bridge to landlords_with_connections).
    (Actor)-[:PARTY_TO {role}]->(Event) edges, role in {Grantor, Grantee,
    Other}.

portfolio/algorithms.py's GDS projection was updated (see
notes/acris-identity.md) to project the `:LandlordActor` secondary label
instead of `:Actor`, so the ~7.7M ACRIS actors this pipeline creates never
enter GDS clustering. That fix must exist BEFORE this pipeline's `parties`
step is first run against real data; it does as of this writing.

Document scope: real_property_master.doctype ILIKE '%DEED%' -- covers all 8
deed-conveyance subtypes present in this WoW snapshot (DEED, DEEDO, DEEDP,
CONDEED, 'DEED COR', 'DEED, LE', 'DEED, RC', 'DEED, TS'). This is a
deterministic filter on WoW's own type code, not a guess: verified these are
the only doctype values containing "DEED", and all are genuine conveyance
instruments. Excludes MTGE/SAT/ASST/etc (mortgages, satisfactions,
assignments -- financial instruments, not ownership transfers).

acris_document_control_codes (the doctype/party-role lookup table) is
broken in this WoW snapshot -- doctype and doctypedescription are NULL on
all 126 rows. party1type/party2type ARE populated there and confirm the
standard public ACRIS convention (partytype 1 = Grantor/Seller, 2 =
Grantee/Buyer for deed documents) -- but since the join key itself is
unusable, this pipeline hardcodes that convention directly rather than
joining. partytype 3 is rare (46,154 of ~12.26M deed-related party rows,
~0.4%) and its exact meaning varies by doctype in the (broken) lookup table
(seen as "LIFE ESTATE RETAINED" for one pattern) -- mapped to role='Other'
since we can't confirm it applies uniformly.

Field mapping (documentid is NOT perfectly unique in real_property_master --
4,664 documentids have 2 byte-identical rows differing only in
modifieddate/goodthroughdate, a benign incremental-extract artifact; the
`events` query dedupes via DISTINCT ON, keeping the most recently modified):
    event_date       <- COALESCE(docdate, recordedfiled). docdate is null on
                         98,274 rows (~2.6%); recordedfiled is 100% populated
                         and covers every one of those gaps exactly.
    violation_class   <- doctype (DEED, DEEDO, CONDEED, ...) -- reuses the
                         shared classification slot for the deed subtype.
    source_id         <- crfn (NYC City Register File Number). Null on ~58%
                         of rows -- CRFN is only used since ACRIS e-recording
                         began in 2003; older deeds use reelyear/reelnbr/
                         reelpage instead (kept in raw_record).
    source_record_id  <- documentid, as a string.
    legal_authority   <- constant "NY Real Property Law (ACRIS-recorded deed
                         conveyance)".
    raw_record        <- compact JSON: docamount, pcttransferred,
                         reelyear/reelnbr/reelpage (0 sentinels normalized to
                         null -- 0 means "not on the reel/page system",
                         i.e. a post-CRFN record already captured by crfn).

BBL: real_property_legals.bbl is 100% clean for every deed-doctype legals
row (0 blank, 0 invalid-format) -- verified directly. No reconstruction
needed, unlike several of the other event pipelines.

Dependency order: run AFTER buildings. `events` MUST run before `parties`
-- parties MATCHes the already-created Event by event_id and skips rows
whose Event doesn't exist (e.g. the 13 deed documents with zero legals rows,
or any doc whose only legals row didn't resolve to a Building).

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.acris_deeds.pipeline
    uv run python -m watchline.discovery.ingest.acris_deeds.pipeline --step events
    uv run python -m watchline.discovery.ingest.acris_deeds.pipeline --step parties
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE = 2000
PARTY_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NY Real Property Law (ACRIS-recorded deed conveyance)"

_ROLE_BY_PARTYTYPE = {1: "Grantor", 2: "Grantee", 3: "Other"}



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(documentid) -> str:
    return f"EVT-ACRIS-{documentid}"


def _norm(v: Optional[str]) -> str:
    return v.strip().upper() if v and v.strip() else ""


def _actor_id(name, address1, address2, city, state, zip_) -> str:
    key = "|".join(_norm(x) for x in (name, address1, address2, city, state, zip_))
    return "ACT-ACRIS-" + hashlib.sha1(key.encode("utf-8")).hexdigest()


def _bizaddr(address1, address2, city, state, zip_) -> Optional[str]:
    parts = [p.strip() for p in (address1, address2, city, state, zip_) if p and p.strip()]
    return ", ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Step 1: Event(DeedTransfer, ACRIS) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# DISTINCT ON dedupes the 4,664 documentids with byte-identical duplicate
# master rows (see module docstring) before fanning out through legals, so a
# multi-lot deed doesn't get double-counted per lot.
EVENTS_SQL = """
WITH deeds AS (
    SELECT DISTINCT ON (documentid)
        documentid, crfn, doctype, docdate, docamount, pcttransferred,
        recordedfiled, reelyear, reelnbr, reelpage
    FROM real_property_master
    WHERE doctype ILIKE '%%DEED%%'
    ORDER BY documentid, modifieddate DESC
)
SELECT d.*, trim(l.bbl) AS bbl
FROM deeds d
JOIN real_property_legals l ON l.documentid = d.documentid
"""


def _event_raw_record(row: dict) -> str:
    return json.dumps({
        "docamount":      row["docamount"],
        "pcttransferred": float(row["pcttransferred"]) if row["pcttransferred"] is not None else None,
        "reelyear":       row["reelyear"] or None,
        "reelnbr":        row["reelnbr"] or None,
        "reelpage":       row["reelpage"] or None,
    })


def _event_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="acris_events", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(EVENTS_SQL)
        batch = []
        for row in cur:
            event_date = row["docdate"] or row["recordedfiled"]
            batch.append({
                "event_id":         _event_id(row["documentid"]),
                "bbl":              row["bbl"],
                "violation_class":  row["doctype"],
                "event_date":       event_date.isoformat() if event_date else None,
                "source_id":        row["crfn"] if row["crfn"] and row["crfn"].strip() else None,
                "source_record_id": row["documentid"],
                "raw_record":       _event_raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_events(session, conn):
    """
    MERGE Event(DeedTransfer, ACRIS) nodes and HAS_EVENT edges. Building-
    first: rows whose BBL has no Building node are skipped entirely.
    Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'DeedTransfer',
        e.source_name      = 'ACRIS',
        e.source_id        = row.source_id,
        e.source_record_id = row.source_record_id,
        e.event_date        = CASE WHEN row.event_date IS NULL THEN null ELSE date(row.event_date) END,
        e.violation_class   = row.violation_class,
        e.legal_authority   = $legal_authority,
        e.raw_record        = row.raw_record,
        e.created_at        = CASE WHEN e.created_at IS NULL THEN datetime($now) ELSE e.created_at END
    MERGE (b)-[:HAS_EVENT]->(e)
    """
    now = _now()
    total = 0
    missing_bbls = set()
    for batch in _event_batches(conn):
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(cypher, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 100_000 == 0:
            print(f"    {total:,} deed/BBL rows processed ...")
    return total, len(missing_bbls)


def step_events(driver) -> None:
    print("Step 1 -- Writing Event(DeedTransfer, ACRIS) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_events(session, conn)
        print(f"  {total:,} deed/BBL rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 2: Actor nodes (ACRIS namespace) + PARTY_TO edges
# ---------------------------------------------------------------------------

# EXISTS (not JOIN) avoids fanning out over the 4,664 duplicate master rows.
PARTIES_SQL = """
SELECT p.documentid, p.partytype, p.name, p.address1, p.address2, p.city, p.state, p.zip
FROM real_property_parties p
WHERE p.partytype IN (1, 2, 3)
  AND p.name IS NOT NULL AND trim(p.name) <> ''
  AND EXISTS (
      SELECT 1 FROM real_property_master m
      WHERE m.documentid = p.documentid AND m.doctype ILIKE '%%DEED%%'
  )
"""


def _party_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="acris_parties", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(PARTIES_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id": _event_id(row["documentid"]),
                "actor_id": _actor_id(row["name"], row["address1"], row["address2"], row["city"], row["state"], row["zip"]),
                "name":     row["name"].strip(),
                "bizaddr":  _bizaddr(row["address1"], row["address2"], row["city"], row["state"], row["zip"]),
                "role":     _ROLE_BY_PARTYTYPE[row["partytype"]],
            })
            if len(batch) == PARTY_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_parties(session, conn):
    """
    MERGE Actor nodes (ACRIS namespace, origin='ACRIS') and PARTY_TO edges.
    Event-first: rows whose Event wasn't created in step_events (no valid
    Building match) are skipped entirely -- no Actor/PARTY_TO orphaned to a
    nonexistent Event. Returns (party_rows_written, skipped_missing_event).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (e:Event {event_id: row.event_id})
    MERGE (a:Actor:WatchlineNode {actor_id: row.actor_id})
    SET a.name       = row.name,
        a.bizaddr    = row.bizaddr,
        a.origin     = 'ACRIS',
        a.updated_at = datetime($now),
        a.created_at = CASE WHEN a.created_at IS NULL THEN datetime($now) ELSE a.created_at END
    MERGE (a)-[r:PARTY_TO]->(e)
    SET r.role = row.role
    """
    now = _now()
    total = 0
    missing_events = set()
    for batch in _party_batches(conn):
        event_ids = {row["event_id"] for row in batch}
        matched = session.run(
            "UNWIND $ids AS id MATCH (e:Event {event_id: id}) RETURN collect(id) AS matched",
            ids=list(event_ids),
        ).single()["matched"]
        missing_events.update(event_ids - set(matched))

        session.run(cypher, batch=batch, now=now)
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} party rows processed ...")
    return total, len(missing_events)


def step_parties(driver) -> None:
    print("Step 2 -- Writing Actor (ACRIS) nodes + PARTY_TO edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_parties(session, conn)
        print(f"  {total:,} party rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct deed documents had no Event node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_events(driver)
    step_parties(driver)
    print("")
    print("ACRIS deeds ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG ACRIS deeds ingestion")
    parser.add_argument(
        "--step",
        choices=["events", "parties"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "events":
            step_events(driver)
        elif args.step == "parties":
            step_parties(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
