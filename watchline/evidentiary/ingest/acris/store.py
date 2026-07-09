"""
watchline/ingest/acris/store.py

Writes ACRIS DeedTransfer Event nodes to Neo4j from the list produced
by load.py.

Ontology mapping:
    Layer 1 (Domain):
        Event {event_type: 'DeedTransfer', source_name: 'ACRIS'}
            -- one per (documentid, bbl) pair
    Relationships:
        (Building)-[:HAS_EVENT]->(Event)
            -- silently skipped if Building does not exist in the graph

Event ID scheme:
    'DEED-{documentid}-{bbl}'
    Unique per (ACRIS document, property). A single deed can transfer
    multiple properties (multiple BBLs); each gets a separate Event node.

DeedWatch readiness:
    grantee_canonical_id is stored as NULL. A future reconciliation
    pipeline will populate this by matching grantee names to existing
    Actor nodes. The property is included now so DeedWatch can add the
    link without a schema change.

    The full event record (doc_amount, recorded_date, pct_transferred)
    is stored even though WatchlineNYC's OwnershipChange intent uses
    only docdate and grantor/grantee names. DeedWatch fraud signal
    computation requires these additional properties.

Source node:
    SRC-ACRIS-001 is created once at the start of the store run.
    Events carry source_name='ACRIS' as a property but are not linked
    via ORIGINATES_IN relationships (volume: ~1M events). That link
    can be added by a future reconciliation step if needed.
"""

import json
from datetime import datetime, timezone

from neo4j import Session

from watchline.shared.batching import BATCH_SIZE
SOURCE_ID  = "SRC-ACRIS-001"


# ---------------------------------------------------------------------------
# Source node
# ---------------------------------------------------------------------------

_SOURCE_CYPHER = """
MERGE (s:Source:WatchlineNode {source_id: $source_id})
SET s.source_name      = 'ACRIS Real Property Records',
    s.producing_agency = 'NYC Department of Finance',
    s.legal_authority  = 'NYC Admin Code §11-2105 (recording of deeds)',
    s.data_url         = 'https://data.cityofnewyork.us/City-Government/ACRIS-Real-Property-Master/bnx9-e6tj',
    s.retrieval_date   = date($today),
    s.coverage_start   = date('2010-01-01'),
    s.description      = 'NYC ACRIS deed transfer records (DEED and CORRD document types). Authoritative record of property ownership transfers filed with the city.',
    s.updated_at       = datetime($now)
"""


def _upsert_source(session: Session, now: str, today: str) -> None:
    session.run(_SOURCE_CYPHER, source_id=SOURCE_ID, now=now, today=today)
    print(f"  Source node {SOURCE_ID} ready.")


# ---------------------------------------------------------------------------
# DeedTransfer Event nodes
# ---------------------------------------------------------------------------

_EVENT_CYPHER = """
UNWIND $batch AS row
MATCH (b:Building {bbl: row.bbl})
MERGE (e:Event:WatchlineNode {event_id: row.event_id})
SET e.event_type           = 'DeedTransfer',
    e.source_name          = 'ACRIS',
    e.source_id            = row.document_id,
    e.status               = 'Recorded',
    e.raw_record           = row.raw_record,
    e.doc_type             = row.doc_type,
    e.event_date           = CASE WHEN row.docdate IS NOT NULL
                                  THEN date(row.docdate) ELSE NULL END,
    e.recorded_date        = CASE WHEN row.recorded_date IS NOT NULL
                                  THEN date(row.recorded_date) ELSE NULL END,
    e.doc_amount           = row.doc_amount,
    e.pct_transferred      = row.pct_transferred,
    e.grantor_names        = row.grantor_names,
    e.grantee_names        = row.grantee_names,
    e.grantee_canonical_id = CASE WHEN e.grantee_canonical_id IS NULL
                                  THEN NULL ELSE e.grantee_canonical_id END,
    e.document_id          = row.document_id,
    e.updated_at           = datetime($now),
    e.created_at           = CASE WHEN e.created_at IS NULL
                                  THEN datetime($now) ELSE e.created_at END
MERGE (b)-[:HAS_EVENT]->(e)
"""


def _upsert_deed_transfers(session: Session, deeds: list[dict], now: str) -> None:
    """Write DeedTransfer Event nodes and HAS_EVENT relationships in batches."""
    total_written  = 0
    total_skipped  = 0

    batch_params = [
        {
            "event_id":        f"DEED-{d['document_id']}-{d['bbl']}",
            "bbl":             d["bbl"],
            "document_id":     d["document_id"],
            "doc_type":        d["doc_type"],
            "docdate":         d["docdate"],
            "recorded_date":   d["recorded_date"],
            "doc_amount":      d["doc_amount"],
            "pct_transferred": float(d["pct_transferred"]) if d["pct_transferred"] is not None else None,
            "grantor_names":   d["grantor_names"],
            "grantee_names":   d["grantee_names"],
            "raw_record":      json.dumps({
                "document_id":    d["document_id"],
                "doc_type":       d["doc_type"],
                "docdate":        d["docdate"],
                "recorded_date":  d["recorded_date"],
                "doc_amount":     d["doc_amount"],
                "pct_transferred": float(d["pct_transferred"]) if d["pct_transferred"] is not None else None,
                "bbl":            d["bbl"],
                "grantor_names":  d["grantor_names"],
                "grantee_names":  d["grantee_names"],
            }),
        }
        for d in deeds
    ]

    batch: list[dict] = []
    for i, row in enumerate(batch_params):
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            result = session.run(_EVENT_CYPHER, batch=batch, now=now)
            summary = result.consume()
            written = summary.counters.nodes_created + summary.counters.relationships_created
            total_written += len(batch)
            batch = []
            if (i + 1) % 50_000 == 0:
                print(f"    ... {i + 1:,} rows processed")

    if batch:
        result = session.run(_EVENT_CYPHER, batch=batch, now=now)
        result.consume()
        total_written += len(batch)

    total_skipped = len(deeds) - total_written
    print(f"  {total_written:,} (document, BBL) pairs written.")
    if total_skipped:
        print(f"  {total_skipped:,} rows skipped (Building not in graph).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(session: Session, deeds: list[dict]) -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    now_iso = datetime.now(timezone.utc).isoformat()
    today   = datetime.now(timezone.utc).date().isoformat()
    print(f"Step 2 -- Writing DeedTransfer Event nodes (run={now_str})")

    print("  Upserting ACRIS Source node ...")
    _upsert_source(session, now_iso, today)

    print(f"  Writing {len(deeds):,} DeedTransfer events ...")
    _upsert_deed_transfers(session, deeds, now_iso)

    print("  Store complete.")
