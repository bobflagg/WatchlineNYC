"""
Watchline Discovery KG — Portfolio Reconcile Pipeline
watchline/discovery/ingest/portfolio/pipeline.py

Builds the heuristic portfolio layer of the DISCOVERY knowledge graph from the
WoW `landlords_with_connections` table.

What this pipeline creates:
    Actor nodes (one per WoW landlord node), each carrying a `bbls` list.
    CONNECTED_BY_NAME / CONNECTED_BY_ADDRESS edges (weighted) between Actors.
    Portfolio nodes (one per detected cluster), rebuilt every run.
    (Actor)-[:MEMBER_OF]->(Portfolio)
    (Building)-[:IN_PORTFOLIO]->(Portfolio)
    (Actor)-[:APPARENT_CONTROL {heuristic:true, ...}]->(Building)   # flagged heuristic

Clustering is OURS (GDS WCC + recursive Louvain, see algorithms.py); we reuse
WoW's pairwise linkage but do our own grouping, so clusters differ from
`wow_portfolios` by design. Portfolio detection is INFERENCE, not fact: nothing
here asserts legal or beneficial ownership. Never emit OWNS / CONTROLS / :Owner.

Schema: the discovery graph type (../../schema/graph_type.cypher) declares every
node/relationship type and key used here. `--step schema` applies it. Because
`ALTER CURRENT GRAPH TYPE SET` REPLACES the whole graph type, that file is the
single source of truth — run `--step schema` ONCE on the empty discovery database
BEFORE the buildings pipeline. It is included in run_all defensively (re-applying
the identical canonical schema is idempotent).

Prerequisites:
    - Neo4j 2026.06+ Enterprise (graph types) with the GDS plugin installed.
    - Buildings + Actors (registrations) + Events already loaded before reconcile.
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.

Usage:
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step schema   # once, first
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step edges
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step reconcile
    uv run python -m watchline.discovery.ingest.portfolio.pipeline                 # all, in order
"""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor

from . import algorithms
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

# Discovery graph type DDL (single source of truth). watchline/discovery/schema/graph_type.cypher
GRAPH_TYPE_PATH = Path(__file__).resolve().parents[2] / "schema" / "graph_type.cypher"

ACTOR_BATCH_SIZE = 1000
EDGE_BATCH_SIZE = 5000
PORTFOLIO_PROGRESS_EVERY = 1000

METHOD = "GDS WCC+Louvain"

# --- Tuning levers (see CLAUDE.md "Portfolios & apparent control") ----------
# Weight name-based links above address-based links: shared name is stronger
# evidence of common control than a shared business address.
NAME_WEIGHT_MULTIPLIER = 1.5
ADDRESS_WEIGHT_MULTIPLIER = 1.0
# Exclude business addresses shared by more than this many landlords
# (registered-agent services, large third-party managers, law offices) — the
# fix for the A&E / "Margaret Brunn" over-clustering. Set to None to disable.
MAX_ADDR_DEGREE = 50



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _actor_id(nodeid) -> str:
    return f"ACT-LL-{nodeid}"


# ---------------------------------------------------------------------------
# Step 0: Schema (graph type)
# ---------------------------------------------------------------------------

def step_schema(driver) -> None:
    """
    Apply the discovery graph type from watchline/discovery/schema/graph_type.cypher.

    WARNING: `ALTER CURRENT GRAPH TYPE SET` replaces the entire graph type and
    all existing constraints. Keep graph_type.cypher authoritative and run this
    once on the empty discovery database before any dataset pipeline.
    """
    print("Step 0 -- Applying discovery graph type ...")
    ddl = GRAPH_TYPE_PATH.read_text().strip().rstrip(";")
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(ddl)
    print(f"  Graph type applied from {GRAPH_TYPE_PATH.name}.")


# ---------------------------------------------------------------------------
# Step 1: Actor nodes + connection edges
# ---------------------------------------------------------------------------

def _aggregator_addresses(conn) -> set:
    """Business addresses shared by more than MAX_ADDR_DEGREE landlords."""
    if MAX_ADDR_DEGREE is None:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bizaddr FROM landlords_with_connections "
            "WHERE bizaddr IS NOT NULL "
            "GROUP BY bizaddr HAVING count(*) > %s",
            (MAX_ADDR_DEGREE,),
        )
        aggregators = {r[0] for r in cur}
    print(f"  {len(aggregators):,} aggregator business addresses excluded "
          f"(> {MAX_ADDR_DEGREE} landlords).")
    return aggregators


def _actor_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="lwc_actors", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 2000
        cur.execute(
            "SELECT nodeid, name, bizaddr, bbls FROM landlords_with_connections"
        )
        batch = []
        for row in cur:
            batch.append({
                "actor_id": _actor_id(row["nodeid"]),
                "nodeid":   row["nodeid"],
                "name":     row["name"],
                "bizaddr":  row["bizaddr"],
                # bbls is a Postgres text[]; psycopg2 returns a Python list.
                "bbls":     row["bbls"] or [],
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
        act.bbls       = a.bbls,
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


def _edge_batches(conn, aggregators: set) -> Iterator[tuple]:
    """
    Yield ('NAME'|'ADDRESS', [ {src, dst, weight}, ... ]) batches parsed from
    the name_match_info / bizaddr_match_info JSON columns.

    Undirected MERGE on the actor pair dedupes reciprocal rows, so we do not
    canonicalize direction here.
    """
    with conn.cursor(name="lwc_edges", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 2000
        cur.execute(
            "SELECT nodeid, bizaddr, name_match_info, bizaddr_match_info "
            "FROM landlords_with_connections"
        )
        name_batch, addr_batch = [], []
        for row in cur:
            src = _actor_id(row["nodeid"])

            for m in (row["name_match_info"] or []):
                name_batch.append({
                    "src": src,
                    "dst": _actor_id(m["nodeid"]),
                    "weight": float(m["weight"]) * NAME_WEIGHT_MULTIPLIER,
                })
                if len(name_batch) == EDGE_BATCH_SIZE:
                    yield ("NAME", name_batch)
                    name_batch = []

            # Skip address edges anchored on an aggregator address.
            if row["bizaddr"] not in aggregators:
                for m in (row["bizaddr_match_info"] or []):
                    addr_batch.append({
                        "src": src,
                        "dst": _actor_id(m["nodeid"]),
                        "weight": float(m["weight"]) * ADDRESS_WEIGHT_MULTIPLIER,
                    })
                    if len(addr_batch) == EDGE_BATCH_SIZE:
                        yield ("ADDRESS", addr_batch)
                        addr_batch = []

        if name_batch:
            yield ("NAME", name_batch)
        if addr_batch:
            yield ("ADDRESS", addr_batch)


_EDGE_CYPHER = {
    "NAME": """
    UNWIND $batch AS e
    MATCH (a:Actor {actor_id: e.src})
    MATCH (b:Actor {actor_id: e.dst})
    MERGE (a)-[r:CONNECTED_BY_NAME]-(b)
    SET r.weight = CASE WHEN r.weight IS NULL OR e.weight > r.weight
                        THEN e.weight ELSE r.weight END
    """,
    "ADDRESS": """
    UNWIND $batch AS e
    MATCH (a:Actor {actor_id: e.src})
    MATCH (b:Actor {actor_id: e.dst})
    MERGE (a)-[r:CONNECTED_BY_ADDRESS]-(b)
    SET r.weight = CASE WHEN r.weight IS NULL OR e.weight > r.weight
                        THEN e.weight ELSE r.weight END
    """,
}


def load_edges(session, conn) -> int:
    aggregators = _aggregator_addresses(conn)
    total = 0
    for kind, batch in _edge_batches(conn, aggregators):
        session.run(_EDGE_CYPHER[kind], batch=batch)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"    {total:,} connection edges written ...")
    return total


def step_edges(driver) -> None:
    print("Step 1 -- Actors + connection edges from landlords_with_connections ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            n_actors = load_actors(session, conn)
            print(f"  {n_actors:,} Actor nodes written.")
            n_edges = load_edges(session, conn)
            print(f"  {n_edges:,} connection edges written.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 2: Reconcile — GDS clustering + Portfolio materialization
# ---------------------------------------------------------------------------

# Portfolios are fully derived; drop and rebuild every run.
_CLEANUP = [
    "MATCH ()-[r:APPARENT_CONTROL]->() "
    "CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS",
    "MATCH (p:Portfolio) "
    "CALL (p) { DETACH DELETE p } IN TRANSACTIONS OF 5000 ROWS",
]

# Anchor = member actor with the most BBLs (proxy for the portfolio's principal;
# role-based anchor selection would require joining hpd_contacts — see CLAUDE.md).
_MATERIALIZE = """
MATCH (a:Actor) WHERE id(a) IN $ids
WITH a ORDER BY size(a.bbls) DESC
WITH collect(a) AS members, collect(a)[0] AS anchor
CREATE (p:Portfolio:WatchlineNode {portfolio_id: $pid})
SET p.run_id       = $run_id,
    p.method       = $method,
    p.generated_at = datetime($now),
    p.member_count = size(members)
WITH p, members, anchor
UNWIND members AS m
MERGE (m)-[:MEMBER_OF]->(p)
WITH p, anchor, members
UNWIND members AS m2
UNWIND m2.bbls AS bbl
WITH p, anchor, collect(DISTINCT bbl) AS bbls
MATCH (b:Building) WHERE b.bbl IN bbls
MERGE (b)-[:IN_PORTFOLIO]->(p)
MERGE (anchor)-[ac:APPARENT_CONTROL]->(b)
SET ac.heuristic    = true,
    ac.method       = $method,
    ac.run_id       = $run_id,
    ac.generated_at = datetime($now)
WITH p, count(DISTINCT b) AS bc, sum(coalesce(b.residential_units, 0)) AS units
SET p.building_count = bc, p.residential_units = units
RETURN bc AS building_count
"""


def step_reconcile(driver) -> None:
    print("Step 2 -- Reconcile: GDS clustering + Portfolio materialization ...")
    run_id = _run_id()
    now = _now()

    with driver.session(database=NEO4J_DATABASE) as session:
        print("  Clearing previous portfolios ...")
        for stmt in _CLEANUP:
            session.run(stmt)

        gds = algorithms.make_gds()
        G = None
        try:
            G, portfolios = algorithms.run(gds, session)

            print(f"  Materializing portfolios (run_id={run_id}) ...")
            written = 0
            for pf_id, node_ids in portfolios:
                pid = f"PF-{run_id}-{pf_id}"
                session.run(
                    _MATERIALIZE,
                    ids=list(node_ids),
                    pid=pid,
                    run_id=run_id,
                    method=METHOD,
                    now=now,
                )
                written += 1
                if written % PORTFOLIO_PROGRESS_EVERY == 0:
                    print(f"    {written:,} portfolios materialized ...")
            print(f"  {written:,} portfolios written.")
        finally:
            if G is not None:
                G.drop()
            algorithms.cleanup_projections(gds)
            gds.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_schema(driver)      # idempotent; also run standalone first on empty DB
    step_edges(driver)
    step_reconcile(driver)
    print("")
    print("Portfolio reconcile complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG portfolio reconcile")
    parser.add_argument(
        "--step",
        choices=["schema", "edges", "reconcile"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "schema":
            step_schema(driver)
        elif args.step == "edges":
            step_edges(driver)
        elif args.step == "reconcile":
            step_reconcile(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
