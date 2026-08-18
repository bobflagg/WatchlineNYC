"""
Watchline Discovery — Rent Stabilization Enrichment
watchline/discovery/ingest/rentstab/pipeline.py

Thin wrapper that calls load_rentstab() from the shared substrate module,
targeting the discovery database. No Source node is created here — that
is an evidentiary-layer epistemic concept.

Usage:
    uv run python -m watchline.discovery.ingest.rentstab.pipeline
"""

from watchline.shared.buildings import load_rentstab
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def main():
    print("Enriching discovery Building nodes with rent stabilization data ...")
    driver = neo4j_driver()
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DISCOVERY_DATABASE) as session:
            total, deregulating = load_rentstab(session, conn)
        print(f"  {total:,} Building nodes enriched.")
        print(f"  {deregulating:,} buildings flagged rs_deregulating=true.")
    finally:
        conn.close()
        driver.close()


if __name__ == "__main__":
    main()
