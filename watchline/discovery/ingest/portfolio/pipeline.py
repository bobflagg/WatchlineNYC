"""
Watchline Discovery KG — Portfolio Reconcile Pipeline
watchline/discovery/ingest/portfolio/pipeline.py
 
Builds the heuristic portfolio layer of the DISCOVERY knowledge graph from the
WoW `landlords_with_connections` table.
 
What this pipeline creates:
    Actor nodes (one per WoW landlord node), each carrying a `bbls` list.
    CONNECTED_BY_NAME / CONNECTED_BY_ADDRESS edges (weighted) between Actors.
    CONNECTED_BY_SPLINK edges (weighted) between Actors the Splink resolution puts
        under one owner — Mechanism B, the `splink` step (see splink_bridge.py).
    Portfolio nodes (one per detected cluster), rebuilt every run.
    (Actor)-[:MEMBER_OF]->(Portfolio)
    (Building)-[:IN_PORTFOLIO]->(Portfolio)
    (Actor)-[:APPARENT_CONTROL {heuristic:true, ...}]->(Building)   # flagged heuristic

Clustering is OURS (GDS WCC + recursive Louvain, see algorithms.py); we reuse
WoW's pairwise linkage — plus the Splink same-owner links, which de-fragment operators
WoW's name/address matching split (Croman's typo'd offices -> one portfolio) — but do
our own grouping, so clusters differ from `wow_portfolios` by design. Because the Splink
links only ADD edges, WCC components only merge, never split: an existing WoW portfolio
(e.g. an agent-linked shell operation) is preserved. Portfolio detection is INFERENCE,
not fact: nothing here asserts legal or beneficial ownership. Never emit OWNS / CONTROLS.
 
Schema: the discovery graph type (../../schema/graph_type.cypher) declares every
node/relationship type and key used here. `--step schema` applies it. Because
`ALTER CURRENT GRAPH TYPE SET` REPLACES the whole graph type, that file is the
single source of truth — run `--step schema` ONCE on the empty discovery database
BEFORE the buildings pipeline. It is included in run_all defensively (re-applying
the identical canonical schema is idempotent).
 
Actor identity is shared with hpd_registrations/pipeline.py, keyed on the same
actor_id (= ACT-LL-<nodeid>) and MERGEd, not CREATEd, by both pipelines — either
can run first. hpd_registrations only ever creates the bare :Actor:WatchlineNode
identity; this pipeline is the sole owner of the :Landlord label, which it adds
via SET (not baked into the MERGE pattern) so the same write matches a node
regardless of which labels it already carries, and adds :Landlord + sets `bbls`
together in that one statement — required so a :Landlord node is never observed
without `bbls` (the discovery graph type declares `bbls NOT NULL` for that
label). PATCH (two rounds):
  1. An earlier version MERGEd on `:Actor:WatchlineNode:LandlordActor` directly,
     which only matches a node that already has all three labels — once
     hpd_registrations stopped pre-attaching the landlord label, that pattern
     no longer matched the node hpd_registrations had already created, so this
     pipeline tried to CREATE a second node with the same actor_id and hit the
     actor_id uniqueness constraint. Fixed by moving the label onto a separate
     SET (still in the same statement/transaction as `bbls`).
  2. Renamed the label from :LandlordActor to :Landlord (flat single-noun,
     consistent with Building / Actor / Event / Portfolio), matching the same
     rename in graph_type.cypher. This rename is safe to run standalone only
     against a fresh/empty discovery database — if it's ever applied to a
     database that already has :LandlordActor-labeled data, that existing data
     needs a one-time relabel migration first (SET n:Landlord, REMOVE
     n:LandlordActor), or the tightened relationship constraints in
     graph_type.cypher will reject the old edges. Not this pipeline's concern
     when starting from empty, but flagged here since this file is the one
     that would otherwise silently start writing an undeclared label again.
 
Prerequisites:
    - Neo4j 2026.06+ Enterprise (graph types) with the GDS plugin installed.
    - Buildings + Actors (registrations) + Events already loaded before reconcile.
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
 
Usage (the `splink` step and a full run need the `ingest` extra: `uv run --extra ingest`):
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step schema   # once, first
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step edges
    uv run --extra ingest python -m ...portfolio.pipeline --step splink            # before reconcile
    uv run python -m watchline.discovery.ingest.portfolio.pipeline --step reconcile
    uv run --extra ingest python -m ...portfolio.pipeline                          # all, in order
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
# Single source of truth for business-address normalization, shared with the OwnerGroup-aware
# aggregator_audit so the mask and its verification key addresses identically.
from watchline.discovery.ingest.portfolio.aggregator_audit import _norm as _norm_bizaddr
 
 
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
 
NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE
 
# Discovery graph type DDL (single source of truth). watchline/discovery/schema/graph_type.cypher
GRAPH_TYPE_PATH = Path(__file__).resolve().parents[2] / "schema" / "graph_type.cypher"
 
# Standalone performance indexes -- NOT part of the graph type (ALTER CURRENT
# GRAPH TYPE SET has no syntax for declaring one). Applied separately, after
# the graph type, by step_schema(). watchline/discovery/schema/indexes.cypher
INDEXES_PATH = Path(__file__).resolve().parents[2] / "schema" / "indexes.cypher"
 
ACTOR_BATCH_SIZE = 1000
EDGE_BATCH_SIZE = 5000
PORTFOLIO_PROGRESS_EVERY = 1000
 
METHOD = "GDS WCC+Louvain"
SPLINK_METHOD = "splink-fellegi-sunter"   # provenance on CONNECTED_BY_SPLINK edges
 
# --- Tuning levers (see CLAUDE.md "Portfolios & apparent control") ----------
# Weight name-based links above address-based links: shared name is stronger
# evidence of common control than a shared business address.
NAME_WEIGHT_MULTIPLIER = 1.5
ADDRESS_WEIGHT_MULTIPLIER = 1.0
# Exclude business addresses shared by more than this many DISTINCT landlords
# (registered-agent services, large third-party managers, law offices) — the fix for the A&E /
# "Margaret Brunn" over-clustering, and for the Orsid-style management-nexus over-merge. Lowered
# 50 -> 25 to match the Splink AGGREGATOR_DEGREE; and the count is now on the NORMALIZED address
# (see _aggregator_addresses) so a megaoffice can't split across format variants and slip under
# the threshold (Orsid's 156 W 56 St = 216 landlords did exactly that at 50/raw). The
# OwnerGroup-aware aggregator_audit verifies this mask hits only true aggregators (0 operator
# exceptions — a same-owner-many-LLCs office would be spared). Set to None to disable.
MAX_ADDR_DEGREE = 25
 
 
 
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
 
 
def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
 
 
def _actor_id(nodeid) -> str:
    return f"ACT-LL-{nodeid}"
 
 
# ---------------------------------------------------------------------------
# Step 0: Schema (graph type)
# ---------------------------------------------------------------------------
 
def _cypher_statements(path: Path):
    """
    Split a .cypher file into individual ';'-terminated statements, skipping
    empty chunks (blank lines, or a statement left fully commented out for later
    -- see indexes.cypher's composite-index example).

    Strips ``//`` line comments BEFORE splitting on ';': a comment may itself
    contain a ';' (e.g. indexes.cypher's "...in the background; it just isn't
    used"), and splitting the raw text would turn the comment's tail into a
    spurious, unparseable statement. graph_type.cypher is applied whole-file by
    step_schema (not through this splitter), so its inline comments are untouched.
    """
    text = "\n".join(
        line.split("//", 1)[0] for line in path.read_text().splitlines()
    )
    for chunk in text.split(";"):
        if chunk.strip():
            yield chunk.strip()
 
 
def step_schema(driver) -> None:
    """
    Apply the discovery graph type from watchline/discovery/schema/graph_type.cypher,
    then the standalone performance indexes from
    watchline/discovery/schema/indexes.cypher.
 
    WARNING: `ALTER CURRENT GRAPH TYPE SET` replaces the entire graph type and
    all existing constraints. Keep graph_type.cypher authoritative and run this
    once on the empty discovery database before any dataset pipeline.
 
    Indexes are a separate DDL category from the graph type -- the ALTER above
    doesn't create or touch them, and creating/re-creating an index doesn't
    require re-applying the graph type either. Each statement in
    indexes.cypher is its own `CREATE INDEX ... IF NOT EXISTS`, so this half
    of the step is safe to re-run on its own too. Index population is online
    and non-blocking -- a freshly-created index on a large label won't be
    usable by the query planner until it reaches ONLINE (check via `SHOW
    INDEXES YIELD name, state, populationPercent`); this step only issues the
    CREATE, it doesn't wait for population to finish.
    """
    print("Step 0 -- Applying discovery graph type ...")
    ddl = GRAPH_TYPE_PATH.read_text().strip().rstrip(";")
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(ddl)
    print(f"  Graph type applied from {GRAPH_TYPE_PATH.name}.")
 
    print("Step 0b -- Applying discovery indexes ...")
    index_statements = list(_cypher_statements(INDEXES_PATH))
    with driver.session(database=NEO4J_DATABASE) as session:
        for stmt in index_statements:
            session.run(stmt)
    print(f"  {len(index_statements)} index statement(s) applied from {INDEXES_PATH.name}.")
 
 
# ---------------------------------------------------------------------------
# Step 1: Actor nodes + connection edges
# ---------------------------------------------------------------------------
 
def _aggregator_addresses(conn) -> set:
    """NORMALIZED business addresses shared by more than MAX_ADDR_DEGREE distinct landlords —
    registered-agent / management megaoffices. Grouping on the normalized address (not the raw
    string) is what makes the mask effective: raw-string grouping lets one office split across
    format variants (', MANHATTAN NY' present/absent, whitespace) so each variant stays under the
    threshold and evades masking. Returns the set of normalized aggregator addresses; _edge_batches
    masks any landlord whose bizaddr normalizes into it."""
    if MAX_ADDR_DEGREE is None:
        return set()
    from collections import Counter
    with conn.cursor() as cur:
        cur.execute("SELECT bizaddr FROM landlords_with_connections WHERE bizaddr IS NOT NULL")
        counts = Counter(_norm_bizaddr(r[0]) for r in cur)   # one lwc row == one distinct landlord
    aggregators = {a for a, n in counts.items() if a and n > MAX_ADDR_DEGREE}
    print(f"  {len(aggregators):,} aggregator business addresses excluded "
          f"(> {MAX_ADDR_DEGREE} landlords, normalized).")
    return aggregators


def _aggregator_nodes(conn, aggregators: set) -> set:
    """lwc nodeids whose NORMALIZED business address is an aggregator. Address edges are masked on
    EITHER endpoint being one of these — a landlord at a private-looking address VARIANT (e.g.
    "575 FIFTH AVENUE 9FK", degree 1) must not fuzzy-match back INTO the masked megaoffice and
    re-bridge it. Masking only the aggregator SRC left exactly that hole (the 575 Fifth blob)."""
    if not aggregators:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT nodeid, bizaddr FROM landlords_with_connections WHERE bizaddr IS NOT NULL")
        return {r[0] for r in cur if _norm_bizaddr(r[1]) in aggregators}
 
 
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
    # PATCH: MERGE only on labels guaranteed to already exist on the node
    # (hpd_registrations/pipeline.py may have created it first, with just
    # :Actor:WatchlineNode). Add :Landlord via SET instead of baking it into
    # the MERGE pattern — SET succeeds whether or not the node already
    # carries the label, whereas MERGE requires an exact label-set match and
    # would otherwise try to CREATE a duplicate node and collide with the
    # actor_id uniqueness constraint. :Landlord and bbls are still added in
    # this one statement/transaction, so a :Landlord node is never observed
    # without bbls (required by the discovery graph type).
    cypher = """
    UNWIND $batch AS a
    MERGE (act:Actor:WatchlineNode {actor_id: a.actor_id})
    SET act:Landlord,
        act.nodeid     = a.nodeid,
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
 
 
def _edge_batches(conn, agg_nodes: set) -> Iterator[tuple]:
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
 
            # Skip an address edge if EITHER endpoint is an aggregator landlord — masking only the
            # src let unmasked address variants re-bridge the megaoffice (see _aggregator_nodes).
            src_is_agg = row["nodeid"] in agg_nodes
            for m in (row["bizaddr_match_info"] or []):
                if src_is_agg or m["nodeid"] in agg_nodes:
                    continue
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
    "SPLINK": """
    UNWIND $batch AS e
    MATCH (a:Actor {actor_id: e.src})
    MATCH (b:Actor {actor_id: e.dst})
    MERGE (a)-[r:CONNECTED_BY_SPLINK]-(b)
    SET r.weight = e.weight, r.method = e.method
    """,
}
 
 
# Drop name/address links before rebuilding. Formerly these were pure MERGE (deterministic +
# additive, so a re-run was a no-op), but the aggregator mask now REMOVES address edges — without
# this drop, edges masked in a new build would linger from a prior unmasked build (the Orsid blob
# survived exactly this way). Dropping name too keeps the edge set an exact function of the code.
_EDGE_CLEANUP = [
    "MATCH ()-[r:CONNECTED_BY_ADDRESS]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS",
    "MATCH ()-[r:CONNECTED_BY_NAME]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS",
]


def load_edges(session, conn) -> int:
    for stmt in _EDGE_CLEANUP:
        session.run(stmt)
    aggregators = _aggregator_addresses(conn)
    agg_nodes = _aggregator_nodes(conn, aggregators)
    by_kind = {"NAME": 0, "ADDRESS": 0}
    for kind, batch in _edge_batches(conn, agg_nodes):
        session.run(_EDGE_CYPHER[kind], batch=batch)
        by_kind[kind] += len(batch)
        total = by_kind["NAME"] + by_kind["ADDRESS"]
        if total % 50_000 == 0:
            print(f"    {total:,} connection edges written ...")
    # Split reported so the aggregator mask is visible: address edges anchored on the excluded
    # megaoffices are skipped, so this count drops sharply when the mask is active.
    print(f"    {by_kind['NAME']:,} name + {by_kind['ADDRESS']:,} address edge rows written "
          f"(address edges on the {len(aggregators):,} aggregator addresses skipped).")
    return by_kind["NAME"] + by_kind["ADDRESS"]
 
 
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
# Step 1b: Splink same-owner edges (Mechanism B)
# ---------------------------------------------------------------------------

# CONNECTED_BY_SPLINK is fully derived from a stochastic resolution, so drop and
# rebuild it every run (the name/address links are deterministic and just MERGE).
_SPLINK_CLEANUP = ("MATCH ()-[r:CONNECTED_BY_SPLINK]->() "
                   "CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS")


def _load_edge_frame(session, edges, method: str) -> int:
    """MERGE one [src, dst, weight] frame as CONNECTED_BY_SPLINK, stamping `method`."""
    cypher = _EDGE_CYPHER["SPLINK"]
    total, batch = 0, []
    for src, dst, weight in edges.itertuples(index=False):
        batch.append({"src": _actor_id(int(src)), "dst": _actor_id(int(dst)),
                      "weight": float(weight), "method": method})
        if len(batch) == EDGE_BATCH_SIZE:
            session.run(cypher, batch=batch); total += len(batch); batch = []
    if batch:
        session.run(cypher, batch=batch); total += len(batch)
    return total


def load_splink_edges(session, conn) -> int:
    """Resolve owners with Splink and MERGE CONNECTED_BY_SPLINK between the Actor nodes
    that resolve to one owner (Mechanism B, see splink_bridge). De-fragments WoW's
    name/address clusters — Croman's typo'd offices collapse into one portfolio — without
    touching what WoW already links (edges only add, so components only merge). Then adds
    a handful of human-verified `curated_owners` cliques for the residual the model can't
    reach (same rare name, no shared corp/address — e.g. Croman's ROCKSOLID remnant),
    stamped with a distinct `method` for provenance. Requires the `ingest` extra (splink);
    imported lazily so schema/edges/reconcile do not."""
    from . import splink_bridge, curated_owners, llc_edges

    print("  Resolving owners with Splink (full-population linkage; ~1 min) ...")
    model_edges = splink_bridge.splink_edges(conn)
    curated = curated_owners.curated_edges(conn)
    llc = llc_edges.llc_edges(conn)                 # deterministic same-registered-owner links
    session.run(_SPLINK_CLEANUP)

    n_model = _load_edge_frame(session, model_edges, SPLINK_METHOD)
    n_curated = _load_edge_frame(session, curated, curated_owners.CURATED_METHOD)
    n_llc = _load_edge_frame(session, llc, llc_edges.LLC_METHOD)
    print(f"    {n_model:,} model + {n_curated:,} curated + {n_llc:,} registered-LLC "
          f"CONNECTED_BY_SPLINK edges")
    return n_model + n_curated + n_llc


def step_splink(driver) -> None:
    print("Step 1b -- CONNECTED_BY_SPLINK edges from the Splink owner resolution ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            n = load_splink_edges(session, conn)
            print(f"  {n:,} CONNECTED_BY_SPLINK edges written.")
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
 
def step_managed(driver) -> None:
    """Build the MANAGEMENT layer: (:Building)-[:MANAGED_BY]->(:Manager) from the disclosed
    HPD managing-agent role (portfolio/managed_by.py). Independent of the ownership/portfolio
    layers — a direct extract + light normalize + group-by, no Splink/WCC/Louvain. Needs the
    `ingest` extra (pandas); imported lazily so schema/edges/reconcile do not. Requires
    :Manager/MANAGED_BY to be declared first (run --step schema)."""
    from . import managed_by

    print("Step 3 -- MANAGED_BY: disclosed managing agent -> :Manager (management layer) ...")
    conn = pg_conn()
    try:
        n = managed_by.load_managed_by(driver, conn, database=NEO4J_DATABASE)
        print(f"  {n:,} MANAGED_BY edges written.")
    finally:
        conn.close()


def step_ownergroup(driver) -> None:
    """Build the OWNERSHIP layer: (:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup) — the owner-identity
    partition (portfolio/owner_groups.py) = the connected components of the CONNECTED_BY_SPLINK
    edges the `splink` step already wrote (model + curated + registered-LLC). A fast Neo4j-only
    pass — no Postgres, no re-run of the resolution. Requires --step splink (edges) and --step
    schema (:OwnerGroup/IN_OWNER_GROUP declared) to have run first."""
    from . import owner_groups

    print("Step 3b -- IN_OWNER_GROUP: owner-identity components -> :OwnerGroup (ownership layer) ...")
    n = owner_groups.load_owner_groups(driver, database=NEO4J_DATABASE)
    print(f"  {n:,} IN_OWNER_GROUP edges written (multi-member owner groups).")


def run_all(driver) -> None:
    step_schema(driver)      # idempotent; also run standalone first on empty DB
    step_edges(driver)
    step_splink(driver)      # CONNECTED_BY_SPLINK before reconcile projects it
    step_reconcile(driver)
    step_managed(driver)     # management layer — independent of the portfolio reconcile
    step_ownergroup(driver)  # ownership layer — independent of the portfolio reconcile
    print("")
    print("Portfolio reconcile complete.")
 
 
def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG portfolio reconcile")
    parser.add_argument(
        "--step",
        choices=["schema", "edges", "splink", "reconcile", "managed", "ownergroup"],
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
        elif args.step == "splink":
            step_splink(driver)
        elif args.step == "reconcile":
            step_reconcile(driver)
        elif args.step == "managed":
            step_managed(driver)
        elif args.step == "ownergroup":
            step_ownergroup(driver)
    finally:
        driver.close()
 
 
if __name__ == "__main__":
    main()