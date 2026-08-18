"""
Watchline Discovery KG — Marshal Evictions Ingestion Pipeline
watchline/discovery/ingest/marshal_evictions/pipeline.py

Creates a fifth Event source in the DISCOVERY knowledge graph: NYC Marshal
eviction executions (the physical carrying-out of a warrant of eviction).

Built ahead of oca_evictions: OCA's own BBL-bridge tables
(oca_addresses_with_bbl, oca_evictions_bldgs, oca_evictions_monthly) are
currently empty (0 rows) in this WoW snapshot, and no other OCA table
carries a bbl/bin/street address -- only city/state/postalcode, too coarse
to deterministically resolve to a Building. marshal_evictions_all, by
contrast, carries `bbl` directly and is fully buildable now. See CLAUDE.md /
conversation notes for the oca_evictions blocker; revisit once WoW backfills
those bridge tables.

What this pipeline creates:
    Event nodes (event_type='Eviction', source_name='Marshal'), keyed
    event_id = EVT-MARSHAL-<courtindexnumber>-<docketnumber>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: marshalfirstname/marshallastname identify the enforcement
officer (a government marshal), not a landlord/tenant party to the case --
kept in raw_record only, not a PARTY_TO candidate. There is also no
respondent/petitioner name in this table at all.

Field mapping (`marshal_evictions_all`, ~112K rows). Key: `uniqueid` is
null on 94% of rows (105,478 / 111,995) and unusable. `docketnumber` alone
has fan-out (98,140 distinct over 111,995 rows). The composite
(courtindexnumber, docketnumber) IS globally unique (verified: 111,995
distinct pairs = row count, no duplicates), so event_id is built from both:
    event_date       <- executeddate (0 nulls -- the date of physical
                         eviction execution, and by definition every row in
                         this table represents a completed execution).
    status            <- evictionlegalpossession, passed through verbatim
                         despite being messy in the source (POSSESSION /
                         EVICTION / 'P' / 'EAST' / UNSPECIFIED -- 'EAST'
                         looks like an upstream data-entry error; not our
                         job to guess-correct it).
    violation_class   <- residentialcommercialind, normalized only for the
                         two known single-letter abbreviations actually
                         present ('R'->'RESIDENTIAL', 'C'->'COMMERCIAL');
                         anything else passes through verbatim. Deterministic
                         lookup, not fuzzy matching.
    source_id         <- courtindexnumber, the originating housing-court
                         case id (cross-references oca_index.indexnumberid
                         by format, even though oca_evictions isn't built
                         yet -- still valid provenance).
    source_record_id  <- docketnumber (the marshal's own record number;
                         global uniqueness comes from event_id's composite
                         key, not from this field alone).
    legal_authority   <- constant "NYRPAPL Art. 7 (Marshal execution of
                         warrant of eviction)".
    raw_record        <- compact JSON: ejectment, evictionaptnum,
                         evictionaddress, marshalfirstname, marshallastname.
                         lat/lon/geo/district fields are dropped -- they
                         duplicate the linked Building's own PLUTO-sourced
                         properties.

BBL: no reconstruction possible -- this table has no boro/block/lot columns
at all, only bbl (and a free-text evictionaddress that would require
geocoding to resolve, which is out of scope / forbidden here). ~10.7K rows
(10,667 blank + 7 with the '0' sentinel) have no usable bbl and simply fail
to MATCH a Building, same as any other unmatched row.

Dependency order: run AFTER the buildings pipeline.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.marshal_evictions.pipeline
"""

import argparse

from watchline.shared.marshal_evictions import load_marshal_evictions
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE


def step_evictions(driver) -> None:
    print("Step 1 -- Writing Event(Eviction, Marshal) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_marshal_evictions(session, conn)
        print(f"  {total:,} eviction rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


def run_all(driver) -> None:
    step_evictions(driver)
    print("")
    print("Marshal evictions ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG marshal evictions ingestion")
    parser.add_argument(
        "--step",
        choices=["evictions"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "evictions":
            step_evictions(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
