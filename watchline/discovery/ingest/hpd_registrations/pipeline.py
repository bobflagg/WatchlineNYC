"""
Watchline Discovery KG — HPD Registrations Ingestion Pipeline
watchline/discovery/ingest/hpd_registrations/pipeline.py

Creates the Actor layer of the DISCOVERY knowledge graph and links actors to the
buildings they are registered for.

What this pipeline creates:
    Actor nodes (one per WoW landlord identity), keyed actor_id = ACT-<nodeid>.
    (Actor)-[:REGISTERED_FOR]->(Building) edges, with registrationid +
    registration_end_date provenance.

Actor identity — the important bit:
    The canonical Actor is the WoW landlord node from `landlords_with_connections`
    (keyed by `nodeid`, i.e. a distinct (name, bizaddr) identity). This is the
    SAME identity the portfolio pipeline clusters on, so the two pipelines share
    Actor nodes. Registration→actor mapping is fully deterministic:

        wow_landlords (bbl, registrationid, name, bizaddr)
          JOIN landlords_with_connections ON (name, bizaddr)  ->  nodeid

    This join has 100% coverage (verified) and no fan-out, since (name, bizaddr)
    is unique in landlords_with_connections. No fuzzy matching is performed.

    ROLE is deferred: hpd_contacts.type carries the real role (HeadOfficer,
    Agent, IndividualOwner, …) but there is no clean key from a contact to a
    landlord `nodeid`, and reconstructing one would require fuzzy name matching
    (forbidden in the discovery layer). REGISTERED_FOR.role is therefore left null
    in v1; populating it is a future refinement requiring a deterministic
    contact-resolution step. See CLAUDE.md.

Dependency order: run AFTER the buildings pipeline. Edges MATCH the Building
first and skip rows whose BBL has no Building node (logged).

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).

Usage:
    uv run python -m watchline.discovery.ingest.hpd_registrations.pipeline
    uv run python -m watchline.discovery.ingest.hpd_registrations.pipeline --step actors
    uv run python -m watchline.discovery.ingest.hpd_registrations.pipeline --step registrations
"""

import argparse
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

ACTOR_BATCH_SIZE = 1000
EDGE_BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor_id(nodeid) -> str:
    return f"ACT-{nodeid}"


# ---------------------------------------------------------------------------
# Step 1: Actor nodes
# ---------------------------------------------------------------------------

# landlords_with_connections is already one row per distinct landlord identity
# (nodeid). It is the authoritative Actor source. `bbls` and the CONNECTED_BY_*
# edges are set by the portfolio pipeline, not here.
ACTORS_SQL = "SELECT nodeid, name, bizaddr FROM landlords_with_connections"


def _actor_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="reg_actors", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 2000
        cur.execute(ACTORS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "actor_id": _actor_id(row["nodeid"]),
                "nodeid":   row["nodeid"],
                "name":     row["name"],
                "bizaddr":  row["bizaddr"],
            })
            if len(batch) == ACTOR_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_actors(session, conn) -> int:
    cypher = """
    UNWIND $batch AS a
    MERGE (act:Actor:WatchlineNode:LandlordActor {actor_id: a.actor_id})
    SET act.nodeid     = a.nodeid,
        act.name       = a.name,
        act.bizaddr    = a.bizaddr,
        act.updated_at = datetime($now),
        act.created_at = CASE WHEN act.created_at IS NULL
                              THEN datetime($now) ELSE act.created_at END
    """
    now = _now()
    total = 0
    for batch in _actor_batches(conn):
        session.run(cypher, batch=batch, now=now)
        total += len(batch)
        if total % 10_000 == 0:
            print(f"    {total:,} actors written ...")
    return total


def step_actors(driver) -> None:
    print("Step 1 -- Writing Actor nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_actors(session, conn)
        print(f"  {total:,} Actor nodes written.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 2: REGISTERED_FOR edges
# ---------------------------------------------------------------------------

# One row per (landlord identity, building, registration). Deterministic bridge
# to nodeid via (name, bizaddr). bbl is CHAR(n) in WoW -> trim. registrationid 0
# is a sentinel with no hpd_registrations match (LEFT JOIN -> null end date).
REGISTRATIONS_SQL = """
SELECT lwc.nodeid              AS nodeid,
       trim(wl.bbl)            AS bbl,
       wl.registrationid       AS registrationid,
       r.registrationenddate   AS reg_end
FROM wow_landlords wl
JOIN landlords_with_connections lwc
  ON lwc.name = wl.name AND lwc.bizaddr = wl.bizaddr
LEFT JOIN hpd_registrations r
  ON r.registrationid = wl.registrationid
WHERE wl.bbl IS NOT NULL
ORDER BY lwc.nodeid
"""


def _registration_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="reg_edges", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 2000
        cur.execute(REGISTRATIONS_SQL)
        batch = []
        for row in cur:
            reg_end = row["reg_end"]
            batch.append({
                "actor_id":       _actor_id(row["nodeid"]),
                "bbl":            row["bbl"],
                "registrationid": row["registrationid"],
                "reg_end":        reg_end.isoformat() if reg_end else None,
            })
            if len(batch) == EDGE_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_registrations(session, conn):
    """
    MERGE REGISTERED_FOR edges. One edge per (actor, building); re-registrations
    collapse onto the same edge, keeping the latest registration_end_date.
    Skips rows whose Building node is absent (BBL not in graph); returns
    (edges_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (a:Actor {actor_id: row.actor_id})
    OPTIONAL MATCH (b:Building {bbl: row.bbl})
    FOREACH (_ IN CASE WHEN b IS NULL THEN [] ELSE [1] END |
        MERGE (a)-[r:REGISTERED_FOR]->(b)
        SET r.registrationid = row.registrationid,
            r.registration_end_date =
                CASE WHEN row.reg_end IS NULL THEN r.registration_end_date
                     WHEN r.registration_end_date IS NULL THEN date(row.reg_end)
                     WHEN date(row.reg_end) > r.registration_end_date THEN date(row.reg_end)
                     ELSE r.registration_end_date END
    )
    """
    total = 0
    missing_bbls = set()
    for batch in _registration_batches(conn):
        # Track BBLs in this batch with no Building node in a global set, so a
        # BBL recurring across many batches is only counted once (not once
        # per batch it appears in).
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(cypher, batch=batch)
        total += len(batch)
        if total % 10_000 == 0:
            print(f"    {total:,} registration rows processed ...")
    return total, len(missing_bbls)


def step_registrations(driver) -> None:
    print("Step 2 -- Writing REGISTERED_FOR edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_registrations(session, conn)
        print(f"  {total:,} registration rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node "
                  f"(expected: buildings without HPD violations are not seeded).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_actors(driver)
    step_registrations(driver)
    print("")
    print("HPD registrations ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG HPD registrations ingestion")
    parser.add_argument(
        "--step",
        choices=["actors", "registrations"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "actors":
            step_actors(driver)
        elif args.step == "registrations":
            step_registrations(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
