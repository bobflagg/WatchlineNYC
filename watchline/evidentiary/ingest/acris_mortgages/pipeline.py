"""
Watchline Evidentiary — ACRIS Mortgages Ingestion Pipeline
watchline/evidentiary/ingest/acris_mortgages/pipeline.py

Ingests the ACRIS money-trail doctypes -- MTGE (mortgage), ASST (mortgage
assignment), SAT (mortgage satisfaction) -- into the evidentiary graph.
Structurally mirrors discovery/ingest/acris_mortgages/pipeline.py's 3-step
shape (events / parties-or-strings / references) and reuses its verified
SQL, DOCTYPES/_EVENT_TYPE_BY_DOCTYPE/_ROLE_BY_DOCTYPE_PARTYTYPE constants,
and the LATERAL-join crfn-resolution fix in REFERENCES_SQL -- see that
module's docstring for the full verified data-shape notes (document
identity, party-role-per-doctype verification including the SAT
Mortgagor/Mortgagee-not-Releasor/Releasee empirical check, BBL coverage,
and the reference docid-vs-crfn recovery rates). Not re-verified here except
where this session re-checked doc counts and the crfn index (both confirmed
current, see notes/evidentiary-ingestion-plan.md task 4 and
notes/updates-to-wow-db.md).

Two design decisions this pipeline deliberately makes differently from its
evidentiary ACRIS deed sibling (evidentiary/ingest/acris/{pipeline,load,store}.py)
-- both made explicitly in notes/evidentiary-ingestion-plan.md task 4, not
by accident:

1. Event id scheme: EVT-ACRIS-{documentid}, matching discovery exactly
   (Reconciliation Principle 2), NOT evidentiary deed's DEED-{documentid}-{bbl}
   scheme. documentid is real_property_master's own row key and a MTGE/ASST/SAT
   row never shares a documentid with a DEED row (verified in discovery's
   session), so there is no ID collision within this graph -- deed events use
   the "DEED-" prefix, these use "EVT-ACRIS-", disjoint namespaces regardless.

   CONSEQUENCE within evidentiary specifically (does not affect discovery,
   where both pipelines use EVT-ACRIS-{documentid}): a small number of ASST/SAT
   documents reference a DEED document (3 of 5,000 in discovery's ASST sample
   -- negligible volume). In THIS graph, evidentiary's deed Events are keyed
   DEED-{documentid}-{bbl}, not EVT-ACRIS-{documentid}, so step 3's MATCH on
   'EVT-ACRIS-{deed_documentid}' will never find them -- these references are
   silently skipped (counted in the references-step skip total), same
   graceful-degradation path already used for un-ingested doctypes like
   AGMT/PAT. This is the accepted, documented cost of NOT fixing the existing
   deed event_id inconsistency (explicitly out of scope for this plan) while
   still giving mortgages the internally-consistent scheme going forward.

2. Actor/party modeling: pipe-joined name strings on the Event
   (mortgagor_names/mortgagee_names for Mortgage and MortgageSatisfaction
   event types; assignor_names/assignee_names for MortgageAssignment),
   NOT Actor nodes + PARTY_TO edges. Matches the existing evidentiary ACRIS
   deed convention (grantor_names/grantee_names as plain strings, resolution
   deferred) rather than discovery's real Actor nodes -- see plan task 4's
   recommendation: lowest effort, consistent with the sibling pipeline, avoids
   building a one-off resolution path for mortgages when deeds haven't gotten
   one yet (both to be revisited together if/when a "DeedWatch" reconciliation
   pipeline is built). SAT reuses the MTGE mortgagor/mortgagee field names
   (not a separate releasor/releasee pair) -- discovery empirically confirmed
   SAT keeps the MTGE party ordering (~116:1 name-match ratio), so extending
   that convention to evidentiary's field names is not a new assumption.
   partytype 3 (3 rows total across all of MTGE, per discovery's docstring) is
   not aggregated into either slot -- same negligible-volume omission
   evidentiary's own grantor/grantee deed aggregation already makes for deed
   partytype 3.

Everything else follows the DOMINANT evidentiary Event-source convention
(hpd_violations / hpd_litigations / hpd_complaints), not the ACRIS deed
outlier: a Source node, one Observation node per document
(OBS-ACRIS-{documentid}), and ORIGINATES_IN edges from both Event and
Observation to the Source. The deed pipeline's docstring explicitly notes it
skips Observations "volume: ~1M events" without further justification; this
pipeline does not repeat that omission, per the general shape rule in
notes/evidentiary-ingestion-plan.md ("Evidentiary pipeline shape" section,
point 2) confirmed by reading hpd_violations, acris (deed), AND rentstab.
Also unlike deed's source_id = document_id, this pipeline uses source_id =
the Source node's own source_id (a foreign key), matching hpd_violations/
hpd_litigations/hpd_complaints -- documentid instead lives in
source_record_id, and crfn gets its own distinctly-named property.

Building linking: MATCH-only, skip-and-count (no minimal Building-stub
creation), same as the evidentiary ACRIS deed sibling's _EVENT_CYPHER -- the
most directly relevant evidentiary precedent for this data family. By the
time this runs (after evidentiary-buildings and evidentiary-hpd in the
Makefile dependency order), the ~444K Buildings from HPD ingestion already
cover the overwhelming majority of BBLs seen in ACRIS records.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Evidentiary graph type applied (`make evidentiary-schema`), including
      the (:Event)-[:REFERENCES]->(:Event) element type added to
      scripts/01_schema.cypher alongside this pipeline -- required before
      step 3. Event's other new top-level properties here (crfn, doc_type,
      doc_amount, pct_transferred, recorded_date, reel_year/nbr/page,
      mortgagor_names/mortgagee_names, assignor_names/assignee_names) do NOT
      need a schema declaration -- Event is open-schema beyond its declared
      core, same as every other evidentiary Event pipeline.
    - Buildings and HPD violations pipelines already run.
    - real_property_master(crfn) index present (confirmed 2026-07-16; see
      notes/updates-to-wow-db.md) -- step 3's crfn fallback is a sequential
      scan without it and will not complete in practical time at full scale.
    - Reference resolution (step 3) additionally benefits from evidentiary's
      OWN acris (deed) `events` step having already run, for the small
      number of ASST/SAT->DEED cross-references that CAN resolve (see design
      decision 1 above for why most still won't).

Usage:
    uv run python -m watchline.evidentiary.ingest.acris_mortgages.pipeline
    uv run python -m watchline.evidentiary.ingest.acris_mortgages.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.acris_mortgages.pipeline --step events
    uv run python -m watchline.evidentiary.ingest.acris_mortgages.pipeline --step parties
    uv run python -m watchline.evidentiary.ingest.acris_mortgages.pipeline --step references
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from psycopg2.extras import RealDictCursor

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

EVENT_BATCH_SIZE     = BATCH_SIZE
PARTY_BATCH_SIZE     = BATCH_SIZE
REFERENCE_BATCH_SIZE = BATCH_SIZE

LEGAL_AUTHORITY = "NY Real Property Law (ACRIS-recorded mortgage instrument)"

DOCTYPES = ("MTGE", "ASST", "SAT")

_EVENT_TYPE_BY_DOCTYPE = {
    "MTGE": "Mortgage",
    "ASST": "MortgageAssignment",
    "SAT":  "MortgageSatisfaction",
}

ACRIS_MORTGAGES_SOURCE = {
    "source_id":        "SRC-ACRIS-MORTGAGES-001",
    "source_name":      "ACRIS Mortgage Instruments",
    "producing_agency": "NYC Department of Finance (Automated City Register Information System)",
    "legal_authority": (
        "NY Real Property Law (recording of mortgage instruments); "
        "NYC Admin Code Section 11-2105 (ACRIS recording)."
    ),
    "data_url": (
        "https://data.cityofnewyork.us/City-Government/"
        "ACRIS-Real-Property-Master/bnx9-e6tj"
    ),
    "description": (
        "ACRIS mortgage instruments recorded against NYC real property: "
        "mortgages (MTGE), mortgage assignments (ASST), and mortgage "
        "satisfactions (SAT). Legally empowered to assert: that a mortgage "
        "instrument of the given type was recorded against a property on a "
        "given date, the parties named on that instrument, and the recorded "
        "document amount. Does NOT assert beneficial ownership of the "
        "underlying property, does NOT assert that a named party is a "
        "natural person rather than an entity, and does NOT assert that a "
        "mortgage still encumbers the property absent a matching "
        "MortgageSatisfaction event."
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(documentid) -> str:
    return f"EVT-ACRIS-{documentid}"


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

def create_source_node(session) -> None:
    now   = _now()
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
        **ACRIS_MORTGAGES_SOURCE,
    )
    print(f"  Source node created/updated: {ACRIS_MORTGAGES_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Event(Mortgage|MortgageAssignment|MortgageSatisfaction, ACRIS)
#         nodes + Observation nodes + HAS_EVENT/ORIGINATES_IN edges
# ---------------------------------------------------------------------------

# Identical to discovery's EVENTS_SQL (see that module's docstring "Document
# identity" for the verified DISTINCT ON dedup rationale).
EVENTS_SQL = """
WITH instruments AS (
    SELECT DISTINCT ON (documentid)
        documentid, crfn, doctype, docdate, docamount, pcttransferred,
        recordedfiled, reelyear, reelnbr, reelpage
    FROM real_property_master
    WHERE doctype IN %(doctypes)s
    ORDER BY documentid, modifieddate DESC
)
SELECT i.*, trim(l.bbl) AS bbl
FROM instruments i
JOIN real_property_legals l ON l.documentid = i.documentid
"""


def _event_raw_record(row: dict) -> str:
    return json.dumps({
        "documentid":     row["documentid"],
        "crfn":           row["crfn"],
        "doctype":        row["doctype"],
        "docamount":      row["docamount"],
        "pcttransferred": float(row["pcttransferred"]) if row["pcttransferred"] is not None else None,
        "reelyear":       row["reelyear"] or None,
        "reelnbr":        row["reelnbr"] or None,
        "reelpage":       row["reelpage"] or None,
    })


def _event_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="ev_acris_mtge_events", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(EVENTS_SQL, {"doctypes": DOCTYPES})
        batch = []
        for row in cur:
            event_date = row["docdate"] or row["recordedfiled"]
            batch.append({
                "event_id":         _event_id(row["documentid"]),
                "event_type":       _EVENT_TYPE_BY_DOCTYPE[row["doctype"]],
                "bbl":              row["bbl"],
                "source_record_id": str(row["documentid"]),
                "crfn":             row["crfn"] if row["crfn"] and row["crfn"].strip() else None,
                "doc_type":         row["doctype"],
                "event_date":       event_date.isoformat() if event_date else None,
                "recorded_date":    row["recordedfiled"].isoformat() if row["recordedfiled"] else None,
                "doc_amount":       row["docamount"],
                "pct_transferred":  float(row["pcttransferred"]) if row["pcttransferred"] is not None else None,
                "reel_year":        row["reelyear"] or None,
                "reel_nbr":         row["reelnbr"] or None,
                "reel_page":        row["reelpage"] or None,
                "raw_record":       _event_raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_events(session, conn):
    """
    MERGE Event + Observation nodes, both ORIGINATES_IN the Source.
    Building-first, MATCH-only (no stub creation) -- see module docstring.
    Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = row.event_type,
        e.source_name      = 'ACRIS',
        e.source_id        = $source_id,
        e.source_record_id = row.source_record_id,
        e.status             = 'Recorded',
        e.crfn              = row.crfn,
        e.doc_type          = row.doc_type,
        e.event_date        = CASE WHEN row.event_date IS NOT NULL THEN date(row.event_date) ELSE null END,
        e.recorded_date      = CASE WHEN row.recorded_date IS NOT NULL THEN date(row.recorded_date) ELSE null END,
        e.doc_amount         = row.doc_amount,
        e.pct_transferred    = row.pct_transferred,
        e.reel_year          = row.reel_year,
        e.reel_nbr           = row.reel_nbr,
        e.reel_page          = row.reel_page,
        e.legal_authority   = $legal_authority,
        e.raw_record        = row.raw_record,
        e.created_at        = CASE WHEN e.created_at IS NULL THEN datetime($now) ELSE e.created_at END
    MERGE (b)-[:HAS_EVENT]->(e)
    WITH e, row
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-ACRIS-' + row.source_record_id
    })
    SET obs.source_id        = $source_id,
        obs.raw_content      = row.raw_record,
        obs.source_record_id = row.source_record_id,
        obs.ingested_at      = CASE WHEN obs.ingested_at IS NULL
                                    THEN datetime($now) ELSE obs.ingested_at END
    MERGE (obs)-[:ORIGINATES_IN]->(s)
    MERGE (e)-[:ORIGINATES_IN]->(s)
    """
    now = _now()
    total = 0
    missing_bbls = set()
    for batch in _event_batches(conn):
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(
            cypher,
            batch=batch,
            now=now,
            source_id=ACRIS_MORTGAGES_SOURCE["source_id"],
            legal_authority=LEGAL_AUTHORITY,
        )
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} mortgage-instrument/BBL rows processed ...")
    return total, len(missing_bbls)


def step_events(driver) -> None:
    print("Step 2 -- Writing Event(Mortgage/MortgageAssignment/MortgageSatisfaction, ACRIS) "
          "+ Observation nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_events(session, conn)
        print(f"  {total:,} mortgage-instrument/BBL rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 3: mortgagor_names/mortgagee_names or assignor_names/assignee_names
#         (pipe-joined party strings, written onto the existing Event)
# ---------------------------------------------------------------------------

# Aggregates partytype 1/2 names per document, restricted to our 3 doctypes --
# same shape as evidentiary's own ACRIS deed grantor/grantee CTEs. partytype 3
# (negligible volume, see module docstring) is not aggregated into either slot.
PARTY_STRINGS_SQL = """
WITH doc_types AS (
    SELECT documentid, doctype FROM real_property_master WHERE doctype IN %(doctypes)s
),
party1 AS (
    SELECT p.documentid, string_agg(p.name, ' | ' ORDER BY p.name) AS names
    FROM real_property_parties p
    JOIN doc_types d ON d.documentid = p.documentid
    WHERE p.partytype = 1 AND p.name IS NOT NULL AND trim(p.name) <> ''
    GROUP BY p.documentid
),
party2 AS (
    SELECT p.documentid, string_agg(p.name, ' | ' ORDER BY p.name) AS names
    FROM real_property_parties p
    JOIN doc_types d ON d.documentid = p.documentid
    WHERE p.partytype = 2 AND p.name IS NOT NULL AND trim(p.name) <> ''
    GROUP BY p.documentid
)
SELECT d.documentid, d.doctype, party1.names AS party1_names, party2.names AS party2_names
FROM doc_types d
LEFT JOIN party1 ON party1.documentid = d.documentid
LEFT JOIN party2 ON party2.documentid = d.documentid
WHERE party1.names IS NOT NULL OR party2.names IS NOT NULL
"""


def _party_string_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="ev_acris_mtge_party_strings", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(PARTY_STRINGS_SQL, {"doctypes": DOCTYPES})
        batch = []
        for row in cur:
            is_assignment = row["doctype"] == "ASST"
            batch.append({
                "event_id":        _event_id(row["documentid"]),
                "mortgagor_names": None if is_assignment else row["party1_names"],
                "mortgagee_names": None if is_assignment else row["party2_names"],
                "assignor_names":  row["party1_names"] if is_assignment else None,
                "assignee_names":  row["party2_names"] if is_assignment else None,
            })
            if len(batch) == PARTY_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_party_strings(session, conn):
    """
    SET mortgagor_names/mortgagee_names (Mortgage, MortgageSatisfaction) or
    assignor_names/assignee_names (MortgageAssignment) onto the existing
    Event. Event-first: rows whose Event wasn't created in step_events (no
    valid Building match) are skipped entirely. Returns (rows_written,
    skipped_missing_event).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (e:Event {event_id: row.event_id})
    SET e.mortgagor_names = row.mortgagor_names,
        e.mortgagee_names = row.mortgagee_names,
        e.assignor_names  = row.assignor_names,
        e.assignee_names  = row.assignee_names
    """
    total = 0
    missing_events = set()
    for batch in _party_string_batches(conn):
        event_ids = {row["event_id"] for row in batch}
        matched = session.run(
            "UNWIND $ids AS id MATCH (e:Event {event_id: id}) RETURN collect(id) AS matched",
            ids=list(event_ids),
        ).single()["matched"]
        missing_events.update(event_ids - set(matched))

        session.run(cypher, batch=batch)
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} party-string rows processed ...")
    return total, len(missing_events)


def step_parties(driver) -> None:
    print("Step 3 -- Writing mortgagor/mortgagee/assignor/assignee name strings onto Events ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_party_strings(session, conn)
        print(f"  {total:,} party-string rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct mortgage documents had no Event node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 4: REFERENCES edges (Event -> Event)
# ---------------------------------------------------------------------------

# Identical to discovery's REFERENCES_SQL -- see that module's docstring
# "Reference resolution" and "Performance and correctness note" for the
# measured docid-vs-crfn recovery rates and why the crfn fallback goes
# through a LATERAL ... LIMIT 1 rather than a plain LEFT JOIN.
REFERENCES_SQL = """
WITH source_docs AS (
    SELECT documentid FROM real_property_master WHERE doctype IN %(doctypes)s
),
refs AS (
    SELECT r.documentid                          AS from_docid,
           NULLIF(trim(r.referencebydocid), '')   AS docid_ref,
           NULLIF(trim(r.referencebycrfn), '')    AS crfn_ref
    FROM real_property_references r
    JOIN source_docs s ON s.documentid = r.documentid
)
SELECT DISTINCT
    refs.from_docid,
    COALESCE(refs.docid_ref, m2.documentid) AS to_docid,
    CASE WHEN refs.docid_ref IS NOT NULL THEN 'DOCID' ELSE 'CRFN' END AS ref_type
FROM refs
LEFT JOIN LATERAL (
    SELECT m.documentid
    FROM real_property_master m
    WHERE m.crfn = refs.crfn_ref
    ORDER BY m.documentid
    LIMIT 1
) m2 ON refs.docid_ref IS NULL AND refs.crfn_ref IS NOT NULL
WHERE COALESCE(refs.docid_ref, m2.documentid) IS NOT NULL
  AND COALESCE(refs.docid_ref, m2.documentid) <> refs.from_docid
"""


def _reference_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="ev_acris_mtge_references", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(REFERENCES_SQL, {"doctypes": DOCTYPES})
        batch = []
        for row in cur:
            batch.append({
                "from_event_id": _event_id(row["from_docid"]),
                "to_event_id":   _event_id(row["to_docid"]),
                "ref_type":      row["ref_type"],
            })
            if len(batch) == REFERENCE_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_references(session, conn):
    """
    MERGE (Event)-[:REFERENCES {ref_type}]->(Event) edges. Both-ends-first:
    a row is written only if BOTH the source and target Event already exist
    (MATCH, never MERGE, on either side -- see module docstring "design
    decision 1" for why the ASST/SAT->DEED skip rate is expected to be
    higher here than on the discovery side). Returns (edges_written,
    skipped_missing_event).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (from:Event {event_id: row.from_event_id})
    MATCH (to:Event {event_id: row.to_event_id})
    MERGE (from)-[rel:REFERENCES]->(to)
    SET rel.ref_type = row.ref_type
    """
    total = 0
    missing_events = set()
    for batch in _reference_batches(conn):
        event_ids = {row["from_event_id"] for row in batch} | {row["to_event_id"] for row in batch}
        matched = session.run(
            "UNWIND $ids AS id MATCH (e:Event {event_id: id}) RETURN collect(id) AS matched",
            ids=list(event_ids),
        ).single()["matched"]
        missing_events.update(event_ids - set(matched))

        session.run(cypher, batch=batch)
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} reference rows processed ...")
    return total, len(missing_events)


def step_references(driver) -> None:
    print("Step 4 -- Writing REFERENCES edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_references(session, conn)
        print(f"  {total:,} reference rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct event_ids referenced by a reference row did not "
                  f"exist in the graph (edge skipped -- an un-ingested doctype, a pre-CRFN "
                  f"reference, a DEED target under evidentiary's different deed event_id "
                  f"scheme, or evidentiary's own acris/deed events haven't run yet).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    create_source_wrapper(driver)
    step_events(driver)
    step_parties(driver)
    step_references(driver)
    print("")
    print("ACRIS mortgages ingestion complete.")


def create_source_wrapper(driver) -> None:
    print("Step 1 -- Creating/updating ACRIS Mortgages Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def main():
    parser = argparse.ArgumentParser(description="Watchline evidentiary ACRIS mortgages ingestion")
    parser.add_argument(
        "--step",
        choices=["source", "events", "parties", "references"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            create_source_wrapper(driver)
        elif args.step == "events":
            step_events(driver)
        elif args.step == "parties":
            step_parties(driver)
        elif args.step == "references":
            step_references(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
