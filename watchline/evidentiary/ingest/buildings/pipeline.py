"""
Watchline Evidentiary KG — Buildings Ingestion Pipeline
watchline/evidentiary/ingest/buildings/pipeline.py

Creates the Building substrate layer in the EVIDENTIARY knowledge graph using
the shared PLUTO-first ingestion module (watchline.shared.buildings).

Coverage: full pluto_latest (~858K lots) plus backfill of registration BBLs
absent from PLUTO. This supersedes the violations-derived building creation that
was previously embedded in each event pipeline (ADR-001 resolution).

Run FIRST, before any event ingestion pipeline.

Prerequisites:
    - Reads WoW (`wow`, port 5434).
    - Evidentiary KG constraints applied (evidentiary-schema Makefile target).

Usage:
    uv run python -m watchline.evidentiary.ingest.buildings.pipeline
    uv run python -m watchline.evidentiary.ingest.buildings.pipeline --step pluto
    uv run python -m watchline.evidentiary.ingest.buildings.pipeline --step backfill
"""

import argparse

from watchline.shared.buildings import load_pluto, load_backfill
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE


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
    parser = argparse.ArgumentParser(description="Watchline evidentiary KG buildings ingestion")
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
