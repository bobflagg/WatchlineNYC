"""
Watchline Evidentiary DOF Ownership/Assessment/Zoning Ingestion Pipeline
watchline/evidentiary/ingest/pluto_dof/pipeline.py

Enriches existing Building nodes with DOF ownername/ownertype/assessland/
assesstot/exempttot/zonedist1/landmark/histdist from pluto_latest.

Unlike other evidentiary source pipelines, this creates no Event nodes and no
Observation nodes -- same convention as rentstab. DOF ownership/assessment/
zoning data is a Building property, not a discrete event. It DOES create a
Source node (unlike discovery's pluto_dof, whose docstring explicitly omits
one because "that is an evidentiary-layer epistemic concept" -- see
notes/evidentiary-ingestion-plan.md task 2).

What this pipeline does:
  - Creates a Source node describing NYC DOF PLUTO as the producing agency,
    with an explicit epistemic-scope statement
  - Adds dof_* properties to existing Building nodes via MERGE (delegates to
    the shared substrate's load_dof_ownership(), same function discovery's
    pluto_dof calls, pointed at the evidentiary database instead)

See watchline/shared/buildings.py load_dof_ownership() for the full field
mapping and verified data-shape notes (ownername coverage, ownertype
blank-vs-coded distribution, etc.) -- not re-verified here, same source
query as the discovery-side pipeline.

This is deliberately raw-fact enrichment only: it does not compare
dof_ownername against any resolved Actor's display_name, and it does not
flag discrepancies. That comparison is an interpretive act and belongs in
its own Rule (Charter: claims are produced by named, versioned Rules, not
computed ad hoc in ingestion), using this field as one of its inputs --
see CLAUDE.md's OwnershipNameDiscrepancy note. Not built yet.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Evidentiary graph type applied (`make evidentiary-schema`) -- dof_*
      fields must already be declared on the Building element type.
    - Buildings pipeline already run (this MERGEs onto existing Building
      nodes; it will also create a minimal one for any bbl not already
      present, same as load_rentstab).

Usage:
    uv run python -m watchline.evidentiary.ingest.pluto_dof.pipeline
    uv run python -m watchline.evidentiary.ingest.pluto_dof.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.pluto_dof.pipeline --step enrich
"""

import argparse
from datetime import datetime, timezone

from watchline.shared.buildings import load_dof_ownership
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

DOF_PLUTO_SOURCE = {
    "source_id":        "SRC-DOF-PLUTO-001",
    "source_name":      "NYC DOF PLUTO",
    "producing_agency": "NYC Department of Finance (DOF)",
    "legal_authority": (
        "NYC Department of Finance maintains the Primary Land Use Tax Lot "
        "Output (PLUTO) dataset as the tax roll of record for real property "
        "in New York City, under the authority of the NYC Charter and the "
        "Administrative Code provisions governing real property assessment."
    ),
    "data_url": "https://www.nyc.gov/site/planning/data-maps/open-data/dwn-pluto-mappluto.page",
    "description": (
        "Owner-of-record name, assessed land/total value, exempt value, "
        "primary zoning district, and landmark/historic-district status per "
        "tax lot, from DOF's PLUTO snapshot. Legally empowered to assert: "
        "DOF's recorded owner-of-record name and assessed value as of the "
        "PLUTO snapshot date. Does NOT assert beneficial ownership, does "
        "NOT assert that the named owner is a natural person rather than an "
        "LLC or other entity, and does NOT assert current market value "
        "(assessed value is a tax-roll figure, not a market appraisal)."
    ),
}


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

def create_source_node(session) -> None:
    now   = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    session.run(
        """
        MERGE (s:Source:WatchlineNode {source_id: $source_id})
        SET s.source_name      = $source_name,
            s.producing_agency = $producing_agency,
            s.legal_authority  = $legal_authority,
            s.data_url         = $data_url,
            s.description      = $description,
            s.retrieval_date   = date($today),
            s.updated_at       = datetime($now),
            s.created_at       = CASE WHEN s.created_at IS NULL
                                     THEN datetime($now)
                                     ELSE s.created_at END
        """,
        today=today,
        now=now,
        **DOF_PLUTO_SOURCE,
    )
    print(f"  Source node created/updated: {DOF_PLUTO_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Enrich Building nodes (delegates to shared substrate)
# ---------------------------------------------------------------------------

def enrich_buildings(session, conn) -> int:
    """Enrich Building nodes with DOF data via shared substrate. Returns total_processed."""
    return load_dof_ownership(session, conn)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating DOF PLUTO Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_enrich(driver):
    print("Step 2 -- Enriching Building nodes with DOF ownership/assessment/zoning data ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = enrich_buildings(session, conn)
        print(f"  {total:,} Building nodes enriched with DOF ownership/assessment/zoning data.")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_enrich(driver)
    print("")
    print("DOF ownership/assessment/zoning ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Watchline evidentiary DOF ownership/assessment/zoning ingestion"
    )
    parser.add_argument(
        "--step",
        choices=["source", "enrich"],
        help="Run a single step (omit to run all steps)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "enrich":
            step_enrich(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
