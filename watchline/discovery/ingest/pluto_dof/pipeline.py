"""
Watchline Discovery — DOF Ownership / Assessment / Zoning Enrichment
watchline/discovery/ingest/pluto_dof/pipeline.py

Thin wrapper that calls load_dof_ownership() from the shared substrate
module, targeting the discovery database. No Source node is created here --
that is an evidentiary-layer epistemic concept (same convention rentstab
follows).

Adds ownername/ownertype/assessland/assesstot/exempttot/zonedist1/landmark/
histdist to existing Building nodes from pluto_latest -- see
watchline/shared/buildings.py load_dof_ownership() for the full field
mapping and verified data-shape notes (ownername coverage, ownertype
blank-vs-coded distribution, etc.).

This is deliberately raw-fact enrichment only: it does not compare
dof_ownername against any HPD-registered actor name, and it does not flag
discrepancies. That comparison is an interpretive act (Charter: claims are
produced by named, versioned Rules, not computed ad hoc in the discovery
substrate) and belongs in the evidentiary layer as its own Rule, using this
field as one of its inputs.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`) --
      dof_ownername/dof_ownertype/dof_assessland/dof_assesstot/
      dof_exempttot/dof_zonedist1/dof_landmark/dof_histdist were added to
      the Building element type alongside this pipeline; re-apply the
      schema before running this if it hasn't been re-applied since.
    - Buildings pipeline already run (this MERGEs onto existing Building
      nodes; it will also create a minimal one for any bbl not already
      present, same as load_rentstab).

Usage:
    uv run python -m watchline.discovery.ingest.pluto_dof.pipeline
"""

from watchline.shared.buildings import load_dof_ownership
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def main():
    print("Enriching discovery Building nodes with DOF ownership/assessment/zoning data ...")
    driver = neo4j_driver()
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DISCOVERY_DATABASE) as session:
            total = load_dof_ownership(session, conn)
        print(f"  {total:,} Building nodes enriched.")
    finally:
        conn.close()
        driver.close()


if __name__ == "__main__":
    main()
