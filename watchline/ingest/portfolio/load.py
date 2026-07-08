"""
Watchline portfolio pipeline -- load stage.

Reads from PostgreSQL (wow_landlords via landlords_with_connections.sql),
writes Landlord nodes and weighted edges to Neo4j for GDS projection.

Watchline adaptations from the JustFix WoW load.py:
  - init_neo4j: no longer drops OwnershipNetwork Actor nodes. Clears only
    Landlord (intermediate) nodes and their edges. OwnershipNetwork Actors,
    IdentityAssertions, Claims, and their evidence chains are managed by
    store.py's versioned update protocol.
  - create_source_nodes: new function that creates/updates the Source node
    for HPD registrations before any Observations are written. This satisfies
    the ontology invariant that every Observation has an ORIGINATES_IN edge
    to a Source.
  - Landlord nodes are intermediate pipeline objects, not ontology nodes.
    They exist only during the GDS projection phase and are cleared after
    store.py has written the final ontology output.
"""

from pathlib import Path
import json
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor
from .config import pg_conn, neo4j_driver, NEO4J_DATABASE

SQL_PATH = Path(__file__).parent / "sql" / "landlords_with_connections.sql"
BATCH_SIZE = 1000

# ---------------------------------------------------------------------------
# Source node definition for HPD registrations
# This is the authoritative record of what the HPD registration source is
# legally empowered to assert. Corresponds to Source node in the ontology.
# ---------------------------------------------------------------------------
HPD_REGISTRATION_SOURCE = {
    "source_id": "SRC-HPD-REGISTRATIONS-001",
    "source_name": "HPD Online Building Registrations",
    "producing_agency": "NYC Department of Housing Preservation and Development",
    "legal_authority": (
        "New York City Administrative Code Section 27-2097 et seq. "
        "Requires owners of multiple dwellings to register annually with HPD, "
        "providing owner name, contact address, and managing agent information."
    ),
    "data_url": "https://data.cityofnewyork.us/Housing-Development/Registration-Contacts/feu5-w2e2",
    "description": (
        "HPD building registration data. Legally empowered to assert: the name "
        "and contact address that a building owner or managing agent self-reported "
        "to HPD at the time of registration. Does NOT assert beneficial ownership, "
        "legal control, or that the reported information is accurate. Registration "
        "is self-reported and subject to error or deliberate misrepresentation."
    ),
}


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

def fetch_landlord_rows():
    conn = pg_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Diagnostic: confirm wow_landlords has data before running the
            # full SQL so we can distinguish an empty source table from a
            # query logic problem.
            cur.execute("SELECT count(*) AS cnt FROM wow_landlords WHERE bbl IS NOT NULL")
            wl_count = cur.fetchone()["cnt"]
            print(f"  wow_landlords rows: {wl_count:,}")
            if wl_count == 0:
                print("  WARNING: wow_landlords is empty — portfolio pipeline "
                      "will produce no portfolios. Run the JustFix ETL first.")
                return []

            print("  Running landlords_with_connections.sql ...")
            cur.execute(SQL_PATH.read_text())
            rows = cur.fetchall()
        conn.commit()

        # Diagnostic: report how many rows have actual edge data
        with_name = sum(1 for r in rows if r.get("name_match_info"))
        with_addr = sum(1 for r in rows if r.get("bizaddr_match_info"))
        print(f"  {len(rows):,} landlord groups fetched.")
        print(f"  {with_name:,} have name-based edges.")
        print(f"  {with_addr:,} have address-based edges.")
        if with_name == 0 and with_addr == 0:
            print("  WARNING: no edges found. Check high_volume_addresses "
                  "threshold and matching conditions in landlords_with_connections.sql.")
        return rows
    finally:
        conn.close()


def _parse_match_info(value):
    """Return a list of {nodeid, weight} dicts regardless of psycopg2 delivery format."""
    if value is None:
        return []
    if isinstance(value, str):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# Neo4j initialisation
# ---------------------------------------------------------------------------

def create_source_nodes(session):
    """
    Create or update the Source node for HPD registrations.
    Must be called before any Observation nodes are written.
    Source nodes are permanent -- they are never deleted between runs.
    """
    print("  Creating/updating HPD Registration Source node ...")
    now = datetime.now(timezone.utc).isoformat()
    session.run(
        """
        MERGE (s:Source:WatchlineNode {source_id: $source_id})
        SET s.source_name      = $source_name,
            s.producing_agency = $producing_agency,
            s.legal_authority  = $legal_authority,
            s.data_url         = $data_url,
            s.description      = $description,
            s.retrieval_date   = date($retrieval_date),
            s.updated_at       = datetime($updated_at),
            s.created_at       = CASE WHEN s.created_at IS NULL
                                      THEN datetime($updated_at)
                                      ELSE s.created_at END
        """,
        retrieval_date=datetime.now(timezone.utc).date().isoformat(),
        updated_at=now,
        **HPD_REGISTRATION_SOURCE,
    )


def init_neo4j(session):
    """
    Prepare Neo4j for a pipeline run.

    Clears intermediate Landlord nodes only. OwnershipNetwork Actors,
    IdentityAssertions, IdentityObservations, Claims, Evidence, and
    Relationship nodes are NOT cleared -- they are managed by the versioned
    update protocol in store.py.

    Source nodes are permanent and are created/updated by create_source_nodes().
    """
    print("  Clearing intermediate Landlord nodes from previous run ...")
    session.run("MATCH (n:Landlord) DETACH DELETE n")

    print("  Ensuring constraints exist ...")
    session.run(
        "CREATE CONSTRAINT landlord_nodeid IF NOT EXISTS "
        "FOR (n:Landlord) REQUIRE n.nodeid IS UNIQUE"
    )


# ---------------------------------------------------------------------------
# Node loading
# ---------------------------------------------------------------------------

def load_nodes(session, rows):
    cypher = """
        UNWIND $batch AS row
        MERGE (l:Landlord {nodeid: row.nodeid})
        SET l.name    = row.name,
            l.bizAddr = row.bizAddr,
            l.bbls    = row.bbls
    """
    total = _write_batches(session, cypher, _node_params(rows))
    print(f"  {total:,} Landlord nodes written.")


def _node_params(rows):
    for row in rows:
        yield {
            "nodeid":   row["nodeid"],
            "name":     row["name"] or row["bizaddr"] or "",
            "bizAddr":  row["bizaddr"],
            "bbls":     list(row["bbls"]),
        }


# ---------------------------------------------------------------------------
# Relationship loading
# ---------------------------------------------------------------------------

def load_relationships(session, rows):
    name_edges, addr_edges = _collect_edges(rows)

    _write_batches(
        session,
        _edge_cypher("CONNECTED_BY_NAME"),
        iter(name_edges),
    )
    _write_batches(
        session,
        _edge_cypher("CONNECTED_BY_ADDRESS"),
        iter(addr_edges),
    )
    print(f"  {len(name_edges):,} CONNECTED_BY_NAME relationships written.")
    print(f"  {len(addr_edges):,} CONNECTED_BY_ADDRESS relationships written.")


def _collect_edges(rows):
    """
    Build deduplicated edge lists from the match_info columns.
    Only emit an edge when source nodeid < target nodeid so each pair
    appears exactly once.
    """
    name_edges = []
    addr_edges = []

    for row in rows:
        nodeid = row["nodeid"]

        for match in _parse_match_info(row["name_match_info"]):
            if nodeid < match["nodeid"]:
                name_edges.append({
                    "source": nodeid,
                    "target": int(match["nodeid"]),
                    "weight": float(match["weight"]),
                })

        for match in _parse_match_info(row["bizaddr_match_info"]):
            if nodeid < match["nodeid"]:
                addr_edges.append({
                    "source": nodeid,
                    "target": int(match["nodeid"]),
                    "weight": float(match["weight"]),
                })

    return name_edges, addr_edges


def _edge_cypher(rel_type):
    return f"""
        UNWIND $batch AS row
        MATCH (a:Landlord {{nodeid: row.source}})
        MATCH (b:Landlord {{nodeid: row.target}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r.weight = row.weight
    """


# ---------------------------------------------------------------------------
# Shared batch writer
# ---------------------------------------------------------------------------

def _write_batches(session, cypher, param_iter):
    """Write params to Neo4j in fixed-size batches; return total rows written."""
    total = 0
    batch = []
    for params in param_iter:
        batch.append(params)
        if len(batch) == BATCH_SIZE:
            session.run(cypher, batch=batch)
            total += len(batch)
            batch = []
    if batch:
        session.run(cypher, batch=batch)
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    print("Step 1 -- Querying PostgreSQL")
    rows = fetch_landlord_rows()

    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            print("Step 2 -- Initializing Neo4j")
            create_source_nodes(session)
            init_neo4j(session)

            print("Step 3 -- Loading Landlord nodes")
            load_nodes(session, rows)

            print("Step 4 -- Loading relationships")
            load_relationships(session, rows)
    finally:
        driver.close()

    print("load complete.")
