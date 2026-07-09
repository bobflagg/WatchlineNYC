"""
Entry point for the Watchline portfolio pipeline.

Usage:
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline            # run all steps
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step init
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step load
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step project
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step wcc
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step store
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step reconcile
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step cleanup

Step ordering:
    init -> load -> store runs the portfolio detection pipeline.
    reconcile is run separately, after Building nodes have been ingested
    by the HPD violations pipeline or another building ingestion pipeline.
    It is safe to re-run reconcile at any time.

Watchline adaptation of JustFix WoW pipeline.py:
  - Removed --step louvain (Louvain is internal to the store step)
  - store step writes OwnershipNetwork Actors + ontology nodes, not Portfolio nodes
  - Intermediate Landlord nodes are cleared at the end of the store step
  - Source nodes are created before load (in load.run())
  - reconcile step creates BeneficialControl Relationship nodes after
    Building nodes exist (deferred from store step, Charter Principle 12)
"""

import argparse

from .config import NEO4J_DATABASE, neo4j_driver
from .algorithms import cleanup_projections, make_gds, project_graph, run as algo_run
from .load import run as load_run
from .store import run as store_run, reconcile_beneficial_control


def step_init(driver):
    from .load import create_source_nodes, init_neo4j
    with driver.session(database=NEO4J_DATABASE) as session:
        print("Step 1 -- Initialising Neo4j ...")
        create_source_nodes(session)
        init_neo4j(session)
        print("  Done.")


def step_load():
    load_run()


def step_project(gds):
    print("Step 5 -- Projecting GDS graph ...")
    cleanup_projections(gds)
    G = project_graph(gds)
    print(f"  {G.node_count():,} nodes, {G.relationship_count():,} relationships.")
    G.drop()
    print("  Projection dropped.")


def step_wcc(driver, gds):
    from .algorithms import _run_wcc, _get_bbl_counts
    print("Step 5 -- Projecting GDS graph ...")
    cleanup_projections(gds)
    G = project_graph(gds)
    print(f"  {G.node_count():,} nodes, {G.relationship_count():,} relationships.")
    with driver.session(database=NEO4J_DATABASE) as session:
        bbl_counts = _get_bbl_counts(session)
        print("  Running WCC ...")
        components = _run_wcc(gds, G)
        print(f"  {len(components):,} components found.")
    G.drop()


def step_store(driver, gds):
    with driver.session(database=NEO4J_DATABASE) as session:
        G, portfolios = algo_run(gds, session)
        try:
            store_run(session, portfolios)
        finally:
            G.drop()


def step_reconcile(driver):
    """
    Create BeneficialControl Relationship nodes linking Building nodes to
    OwnershipNetwork Actors. Run after building ingestion is complete.
    """
    with driver.session(database=NEO4J_DATABASE) as session:
        reconcile_beneficial_control(session)


def step_cleanup(gds):
    print("Cleanup -- dropping GDS projections ...")
    cleanup_projections(gds)
    print("  Done.")


def run_all(driver, gds):
    load_run()

    with driver.session(database=NEO4J_DATABASE) as session:
        G, portfolios = algo_run(gds, session)
        try:
            store_run(session, portfolios)
        finally:
            G.drop()

    # Reconcile runs separately after building ingestion; not included in run_all
    print("Note: run --step reconcile after building ingestion to create")
    print("      BeneficialControl Relationship nodes.")


def main():
    parser = argparse.ArgumentParser(description="Watchline portfolio pipeline")
    parser.add_argument(
        "--step",
        choices=["init", "load", "project", "wcc", "store", "reconcile", "cleanup"],
        help="Run a single pipeline step (omit to run all steps)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    gds = make_gds()

    try:
        if args.step is None:
            run_all(driver, gds)
        elif args.step == "init":
            step_init(driver)
        elif args.step == "load":
            step_load()
        elif args.step == "project":
            step_project(gds)
        elif args.step == "wcc":
            step_wcc(driver, gds)
        elif args.step == "store":
            step_store(driver, gds)
        elif args.step == "reconcile":
            step_reconcile(driver)
        elif args.step == "cleanup":
            step_cleanup(gds)
    finally:
        gds.close()
        driver.close()


if __name__ == "__main__":
    main()
