"""
scripts/test_connections.py

Test connections to both Neo4j KGs and Postgres using shared helpers.

Usage:
    uv run python scripts/test_connections.py
"""

from watchline.shared.connections import (
    neo4j_driver, pg_conn,
    NEO4J_EVIDENTIARY_DATABASE, NEO4J_DISCOVERY_DATABASE,
)

print("\n── Neo4j")
driver = neo4j_driver()
for db in [NEO4J_EVIDENTIARY_DATABASE, NEO4J_DISCOVERY_DATABASE]:
    try:
        with driver.session(database=db) as s:
            n = s.run("MATCH (b:Building) RETURN count(b) AS n").single()["n"]
        print(f"  OK  {db}: {n:,} Building nodes")
    except Exception as e:
        print(f"  FAIL {db}: {e}")
driver.close()

print("\n── Postgres")
try:
    conn = pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT current_database(), inet_server_port()")
    db, port = cur.fetchone()
    conn.close()
    print(f"  OK  db={db} port={port}")
except Exception as e:
    print(f"  FAIL {e}")

print()
