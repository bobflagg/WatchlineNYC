"""
Watchline Discovery KG — ACRIS Mortgages Ingestion Pipeline
watchline/discovery/ingest/acris_mortgages/pipeline.py

Extends the ACRIS Event source acris_deeds already created in the DISCOVERY
knowledge graph. acris_deeds covers ownership transfers (doctype ILIKE
'%DEED%') and deliberately excludes MTGE/SAT/ASST as "financial instruments,
not ownership transfers." This pipeline ingests exactly those three doctypes
-- the debt side of the ACRIS record: who lent against a building, whether
that debt was later assigned to a different lender, and whether it was
satisfied (paid off). This is the money-trail complement to the deed graph:
a beneficial owner who never appears as a deed grantee/grantor can still
surface here as a mortgagor, or as the counterparty a lender's debt was
quietly assigned to.

What this pipeline creates:
    Event nodes, keyed event_id = EVT-ACRIS-<documentid> -- the SAME
    namespace acris_deeds uses for DeedTransfer events. This is safe, not
    accidental: documentid is real_property_master's own row key, shared
    across every doctype in that table (a DEED row and an MTGE row are
    different rows with different documentid values -- verified directly,
    see "Document identity" below). event_type is one of:
        Mortgage             (doctype = 'MTGE')
        MortgageAssignment   (doctype = 'ASST')
        MortgageSatisfaction (doctype = 'SAT')
    source_name = 'ACRIS' for all three, matching acris_deeds.
    (Building)-[:HAS_EVENT]->(Event) edges via real_property_legals, same
    Building-first skip pattern as every other event pipeline.
    Actor nodes in the EXACT SAME ACT-ACRIS-{sha1} namespace acris_deeds
    uses (identical SHA-1-of-normalized-(name,address) key). This is
    deliberate and load-bearing: _actor_id() below MUST stay byte-identical
    to acris_deeds._actor_id, or the same real-world party recorded on a
    deed and later on a mortgage will resolve to two different Actor nodes
    instead of one. No fuzzy matching is introduced -- this is the same
    exact-match MERGE acris_deeds already relies on, just shared across two
    pipelines by construction.
    (Actor)-[:PARTY_TO {role}]->(Event) edges, role in {Mortgagor,
    Mortgagee, Assignor, Assignee, Other}.
    (Event)-[:REFERENCES {ref_type}]->(Event) edges chaining a later
    instrument back to the one it modifies (e.g. a MortgageSatisfaction
    back to the Mortgage it satisfies, or a MortgageAssignment back to the
    Mortgage or prior Assignment it reassigns). This is a NEW element type
    -- added to discovery/schema/graph_type.cypher alongside this pipeline
    -- and the first Event-to-Event edge in the discovery graph.

Document identity (verified directly against real_property_master, doctype
IN ('MTGE','ASST','SAT')):
    MTGE: 4,212,004 rows / 4,208,816 distinct documentid
    ASST: 2,205,247 rows / 2,204,036 distinct documentid
    SAT:  2,623,400 rows / 2,621,910 distinct documentid
The small gap in each (0.03-0.08%) is the same benign duplicate-row
artifact acris_deeds documented for deeds (byte-identical re-extract rows
differing only in modifieddate/goodthroughdate) -- handled the same way,
DISTINCT ON (documentid) ORDER BY modifieddate DESC.

Party roles per doctype (real_property_parties.partytype -> role). As with
acris_deeds, acris_document_control_codes cannot be joined for this (doctype
and doctypedescription are NULL on all 126 rows in this WoW snapshot) so the
mapping is hardcoded from the standard ACRIS convention, cross-checked
directly against this data:
    MTGE: partytype 1 = Mortgagor (Borrower), 2 = Mortgagee (Lender).
          Verified counts: 6,818,656 rows at partytype 1, 4,642,903 at
          partytype 2, 3 at partytype 3 (mapped to 'Other', same treatment
          acris_deeds gives its rare partytype-3 rows).
    ASST: partytype 1 = Assignor (old lender), 2 = Assignee (new lender).
          Verified counts: 2,721,873 at partytype 1, 2,517,560 at 2.
    SAT:  partytype 1 = Mortgagor (Borrower), 2 = Mortgagee (Lender) -- the
          SAME convention as MTGE, not a Releasor/Releasee pairing. This
          was not assumed: empirically confirmed by resolving a 3,000-row
          SAT sample back to its referenced Mortgage (via the same
          docid/crfn resolution step 3 uses) and comparing party names.
          Of 9,998 resolved (SAT, Mortgage) pairs, SAT partytype-1's name
          matched the Mortgage's partytype-1 (Mortgagor) name in 4,405
          cases, versus only 38 matching the Mortgage's partytype-2
          (Mortgagee) name -- a ~116:1 ratio confirming SAT keeps the
          Mortgagor/Mortgagee party ordering rather than reversing it.
          Verified counts: 3,960,701 at partytype 1, 3,362,127 at 2.

BBL: real_property_legals.bbl is clean for every joined MTGE/ASST/SAT row
(0 malformed among 10,577,192 joined rows, verified directly) -- no
reconstruction needed, same as acris_deeds. Coverage against the full
master table is NOT 100% (some documents have no legals row at all -- a
blanket instrument recorded without a lot-level legal description, or a
non-real-property filing that ended up in this table): MTGE 4,208,815 /
4,892,192 master rows have >=1 legals row (86%), ASST 2,204,033 / 2,766,441
(80%), SAT 2,621,907 / 2,918,566 (90%). Rows without a legals/BBL match are
skipped in step 1 (Building-first pattern) -- their Event node is simply
never created, which step 2 and step 3 then also skip via their own
Event-first MATCHes.

Reference resolution (step 3, real_property_references): a reference is
recorded as EITHER referencebydocid (a direct real_property_master.documentid
value) OR referencebycrfn (a CRFN to resolve against
real_property_master.crfn) -- never reliably both. Measured on a 5,000-doc
SAT sample: of 7,851 total reference rows, only 22 had a usable
referencebydocid, but 6,542 had a usable referencebycrfn, of which 6,540
resolved to a real_property_master row. So the docid path is close to
useless alone -- the query below tries docid first and falls back to the
crfn join, which is what actually recovers ~83% of references at this
sample size. The remaining ~16% are pre-CRFN filings (reelyear/reelnbr/
reelpage only, no CRFN) -- these are NOT resolved into REFERENCES edges,
same category of gap as acris_deeds leaving reel data in raw_record only
rather than joining on it.
Performance and correctness note on the crfn fallback: checked
pg_indexes directly -- real_property_master has indexes on documentid,
doctype, docamount, and docdate, but NONE on crfn. Every crfn resolution
in step 3 is therefore a sequential-scan-driven lookup; a naive attempt to
run the equivalent join across ALL MTGE/ASST/SAT documents at once timed
out in the exploratory session that produced this pipeline, and only
completed at a few-thousand-document sample scale. Add an index on
real_property_master(crfn) before running step 3 at full scale.
Separately, crfn's uniqueness within real_property_master was NOT
verified -- a COUNT(*) vs COUNT(DISTINCT crfn) check also timed out before
it could return, so whether the same crfn can legitimately appear on more
than one documentid row is an open question, not a confirmed fact. The
query below does not assume uniqueness: it resolves the crfn fallback
through a LATERAL subquery with ORDER BY documentid LIMIT 1, so a
duplicate crfn deterministically picks one match rather than fanning out
into multiple REFERENCES edges from the same source event.

Dependency order: run AFTER buildings and AFTER acris_deeds' `events` step
(a small number of ASST/SAT documents reference a DEED document -- 3 of
5,000 in the ASST sample -- and step 3's MATCH on the target Event will
only find those if acris_deeds has already run). Within this module:
events -> parties -> references, in that order. references additionally
requires the graph_type.cypher REFERENCES element type to already be
applied (`ALTER CURRENT GRAPH TYPE SET`, portfolio pipeline `--step
schema`) -- it was added alongside this pipeline, not before.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied, INCLUDING the REFERENCES element type
      added to discovery/schema/graph_type.cypher for this pipeline.
    - Buildings pipeline already run.
    - acris_deeds `events` step already run (for cross-doctype references).

Usage:
    uv run python -m watchline.discovery.ingest.acris_mortgages.pipeline
    uv run python -m watchline.discovery.ingest.acris_mortgages.pipeline --step events
    uv run python -m watchline.discovery.ingest.acris_mortgages.pipeline --step parties
    uv run python -m watchline.discovery.ingest.acris_mortgages.pipeline --step references
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE     = 2000
PARTY_BATCH_SIZE     = 2000
REFERENCE_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NY Real Property Law (ACRIS-recorded mortgage instrument)"

DOCTYPES = ("MTGE", "ASST", "SAT")

_EVENT_TYPE_BY_DOCTYPE = {
    "MTGE": "Mortgage",
    "ASST": "MortgageAssignment",
    "SAT":  "MortgageSatisfaction",
}

# See module docstring "Party roles per doctype" for how each of these was
# verified. SAT deliberately reuses the MTGE mapping (empirically confirmed,
# not assumed). partytype 3 has no entry for any doctype here -- it's
# treated as 'Other' via .get() below, same as acris_deeds' rare partytype 3.
_ROLE_BY_DOCTYPE_PARTYTYPE = {
    ("MTGE", 1): "Mortgagor",
    ("MTGE", 2): "Mortgagee",
    ("ASST", 1): "Assignor",
    ("ASST", 2): "Assignee",
    ("SAT",  1): "Mortgagor",
    ("SAT",  2): "Mortgagee",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(documentid) -> str:
    # Deliberately identical to acris_deeds._event_id -- same documentid
    # space, see module docstring "Document identity".
    return f"EVT-ACRIS-{documentid}"


def _norm(v: Optional[str]) -> str:
    return v.strip().upper() if v and v.strip() else ""


def _actor_id(name, address1, address2, city, state, zip_) -> str:
    # MUST stay byte-identical to acris_deeds._actor_id -- see module
    # docstring. Duplicated rather than imported because every pipeline
    # module in this codebase is self-contained (see hpd_litigations,
    # hpd_registrations, acris_deeds); the invariant is enforced by
    # comment + code review, not by shared code.
    key = "|".join(_norm(x) for x in (name, address1, address2, city, state, zip_))
    return "ACT-ACRIS-" + hashlib.sha1(key.encode("utf-8")).hexdigest()


def _bizaddr(address1, address2, city, state, zip_) -> Optional[str]:
    parts = [p.strip() for p in (address1, address2, city, state, zip_) if p and p.strip()]
    return ", ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Step 1: Event(Mortgage|MortgageAssignment|MortgageSatisfaction, ACRIS)
#         nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# Same DISTINCT ON dedup acris_deeds uses, same reason (see module docstring
# "Document identity"). doctype IN (...) replaces deeds' ILIKE '%DEED%'.
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
        "docamount":      row["docamount"],
        "pcttransferred": float(row["pcttransferred"]) if row["pcttransferred"] is not None else None,
        "reelyear":       row["reelyear"] or None,
        "reelnbr":        row["reelnbr"] or None,
        "reelpage":       row["reelpage"] or None,
    })


def _event_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="acris_mtge_events", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(EVENTS_SQL, {"doctypes": DOCTYPES})
        batch = []
        for row in cur:
            event_date = row["docdate"] or row["recordedfiled"]
            batch.append({
                "event_id":         _event_id(row["documentid"]),
                "event_type":       _EVENT_TYPE_BY_DOCTYPE[row["doctype"]],
                "bbl":              row["bbl"],
                "violation_class":  row["doctype"],
                "event_date":       event_date.isoformat() if event_date else None,
                "source_id":        row["crfn"] if row["crfn"] and row["crfn"].strip() else None,
                "source_record_id": row["documentid"],
                "raw_record":       _event_raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_events(session, conn):
    """
    MERGE Event nodes (Mortgage/MortgageAssignment/MortgageSatisfaction,
    ACRIS) and HAS_EVENT edges. Building-first: rows whose BBL has no
    Building node are skipped entirely. Returns (events_written,
    skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = row.event_type,
        e.source_name      = 'ACRIS',
        e.source_id        = row.source_id,
        e.source_record_id = row.source_record_id,
        e.event_date        = CASE WHEN row.event_date IS NULL THEN null ELSE date(row.event_date) END,
        e.violation_class   = row.violation_class,
        e.legal_authority   = $legal_authority,
        e.raw_record        = row.raw_record,
        e.created_at        = CASE WHEN e.created_at IS NULL THEN datetime($now) ELSE e.created_at END
    MERGE (b)-[:HAS_EVENT]->(e)
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

        session.run(cypher, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 100_000 == 0:
            print(f"    {total:,} mortgage-instrument/BBL rows processed ...")
    return total, len(missing_bbls)


def step_events(driver) -> None:
    print("Step 1 -- Writing Event(Mortgage/MortgageAssignment/MortgageSatisfaction, ACRIS) nodes + HAS_EVENT edges ...")
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
# Step 2: Actor nodes (ACRIS namespace, shared with acris_deeds) + PARTY_TO
# ---------------------------------------------------------------------------

# EXISTS (not JOIN) avoids fanning out over the small number of duplicate
# master rows, same reason as acris_deeds. The scalar subquery for doctype
# is a cheap point lookup by documentid, used only to pick the right role
# mapping -- it does not fan out the party row set.
PARTIES_SQL = """
SELECT
    p.documentid, p.partytype, p.name, p.address1, p.address2, p.city, p.state, p.zip,
    (SELECT m.doctype FROM real_property_master m
     WHERE m.documentid = p.documentid LIMIT 1) AS doctype
FROM real_property_parties p
WHERE p.partytype IN (1, 2, 3)
  AND p.name IS NOT NULL AND trim(p.name) <> ''
  AND EXISTS (
      SELECT 1 FROM real_property_master m
      WHERE m.documentid = p.documentid AND m.doctype IN %(doctypes)s
  )
"""


def _party_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="acris_mtge_parties", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(PARTIES_SQL, {"doctypes": DOCTYPES})
        batch = []
        for row in cur:
            role = _ROLE_BY_DOCTYPE_PARTYTYPE.get((row["doctype"], row["partytype"]), "Other")
            batch.append({
                "event_id": _event_id(row["documentid"]),
                "actor_id": _actor_id(row["name"], row["address1"], row["address2"], row["city"], row["state"], row["zip"]),
                "name":     row["name"].strip(),
                "bizaddr":  _bizaddr(row["address1"], row["address2"], row["city"], row["state"], row["zip"]),
                "role":     role,
            })
            if len(batch) == PARTY_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_parties(session, conn):
    """
    MERGE Actor nodes (ACRIS namespace, origin='ACRIS' -- same namespace
    and same Actor nodes acris_deeds writes to) and PARTY_TO edges.
    Event-first: rows whose Event wasn't created in step_events (no valid
    Building match) are skipped entirely. Returns (party_rows_written,
    skipped_missing_event).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (e:Event {event_id: row.event_id})
    MERGE (a:Actor:WatchlineNode {actor_id: row.actor_id})
    SET a.name       = row.name,
        a.bizaddr    = row.bizaddr,
        a.origin     = 'ACRIS',
        a.updated_at = datetime($now),
        a.created_at = CASE WHEN a.created_at IS NULL THEN datetime($now) ELSE a.created_at END
    MERGE (a)-[r:PARTY_TO]->(e)
    SET r.role = row.role
    """
    now = _now()
    total = 0
    missing_events = set()
    for batch in _party_batches(conn):
        event_ids = {row["event_id"] for row in batch}
        matched = session.run(
            "UNWIND $ids AS id MATCH (e:Event {event_id: id}) RETURN collect(id) AS matched",
            ids=list(event_ids),
        ).single()["matched"]
        missing_events.update(event_ids - set(matched))

        session.run(cypher, batch=batch, now=now)
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} party rows processed ...")
    return total, len(missing_events)


def step_parties(driver) -> None:
    print("Step 2 -- Writing Actor (ACRIS) nodes + PARTY_TO edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_parties(session, conn)
        print(f"  {total:,} party rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct mortgage documents had no Event node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 3: REFERENCES edges (Event -> Event)
# ---------------------------------------------------------------------------

# See module docstring "Reference resolution" for the measured docid-vs-crfn
# recovery rates and the "Performance and correctness note" for why the
# crfn fallback goes through a LATERAL ... LIMIT 1 rather than a plain
# LEFT JOIN: crfn's uniqueness within real_property_master was not
# verified, so this guarantees a deterministic single match instead of
# risking a fan-out into duplicate/spurious REFERENCES edges if a crfn
# value turns out to repeat across documentid rows.
# source_docs restricts the FROM side to the doctypes this pipeline
# ingests; the TO side is deliberately unrestricted -- the Cypher MATCH in
# load_references silently drops any reference whose target documentid
# isn't an ingested Event (e.g. references to AGMT/PAT, which neither
# acris_deeds nor this pipeline ingests).
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
    with conn.cursor(name="acris_mtge_references", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
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
    a row is written only if BOTH the source and target Event already
    exist (see module docstring -- this is deliberately MATCH, never
    MERGE, on either side). Returns (edges_written, skipped_missing_event).
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
        if total % 100_000 == 0:
            print(f"    {total:,} reference rows processed ...")
    return total, len(missing_events)


def step_references(driver) -> None:
    print("Step 3 -- Writing REFERENCES edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_references(session, conn)
        print(f"  {total:,} reference rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct event_ids referenced by a reference row did not "
                  f"exist in the graph (edge skipped -- either an un-ingested doctype, a "
                  f"pre-CRFN reference, or acris_deeds hasn't run yet).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_events(driver)
    step_parties(driver)
    step_references(driver)
    print("")
    print("ACRIS mortgages ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG ACRIS mortgages ingestion")
    parser.add_argument(
        "--step",
        choices=["events", "parties", "references"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
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
