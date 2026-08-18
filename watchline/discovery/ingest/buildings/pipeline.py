"""
Watchline Discovery KG — Buildings Ingestion Pipeline
watchline/discovery/ingest/buildings/pipeline.py

Creates the Building layer of the DISCOVERY knowledge graph.

Coverage strategy:
    PLUTO (`pluto_latest`) is the authoritative NYC tax-lot dataset and is loaded
    in full (~858K lots) as the building substrate, enriched with address, unit
    count, year built, building class, and coordinates. Loading the complete lot
    set — rather than only buildings that happen to have violations — means the
    REGISTERED_FOR / HAS_EVENT edges from every downstream pipeline actually land.

    A small number of registration BBLs are absent from PLUTO (~1,032, malformed
    or condo BBLs); `--step backfill` seeds those as minimal Building nodes so
    hpd_registrations coverage is complete.

Run FIRST, before hpd_registrations and the event pipelines.

Prerequisites:
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.

Usage:
    uv run python -m watchline.discovery.ingest.buildings.pipeline
    uv run python -m watchline.discovery.ingest.buildings.pipeline --step pluto
    uv run python -m watchline.discovery.ingest.buildings.pipeline --step backfill
"""

import argparse

from watchline.shared.buildings import load_pluto, load_backfill
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE


def step_pluto(driver) -> None:
    print("Step 1 -- Writing Building nodes from pluto_latest ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_pluto(session, conn)
        print(f"  {total:,} PLUTO Building nodes written.")
    finally:
        conn.close()


def step_backfill(driver) -> None:
    print("Step 2 -- Backfilling registration BBLs missing from PLUTO ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_backfill(session, conn)
        print(f"  {total:,} minimal Building nodes backfilled.")
    finally:
        conn.close()


def run_all(driver) -> None:
    step_pluto(driver)
    step_backfill(driver)
    print("")
    print("Buildings ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG buildings ingestion")
    parser.add_argument(
        "--step",
        choices=["pluto", "backfill"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "pluto":
            step_pluto(driver)
        elif args.step == "backfill":
            step_backfill(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
