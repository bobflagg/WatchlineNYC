"""
watchline/shared/marshal_evictions.py

Canonical marshal eviction Event ingestion shared by both KGs.

Marshal evictions are domain facts (physical warrant executions), not
epistemic overlays. Both discovery and evidentiary graphs carry them.

event_id scheme: EVT-MARSHAL-{courtindexnumber}-{docketnumber}
(composite key verified globally-unique: 111,995 distinct pairs = row count)
"""

import json
from datetime import datetime, timezone
from typing import Iterator, List

from psycopg2.extras import RealDictCursor

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE


LEGAL_AUTHORITY = "NY RPAPL Art. 7 (Marshal execution of warrant of eviction)"

_PROPERTY_TYPE_NORMALIZE = {"R": "RESIDENTIAL", "C": "COMMERCIAL"}

EVICTIONS_SQL = """
SELECT
    courtindexnumber,
    docketnumber,
    trim(bbl)                    AS bbl,
    residentialcommercialind,
    evictionlegalpossession,
    executeddate,
    ejectment,
    evictionaptnum,
    evictionaddress,
    marshalfirstname,
    marshallastname
FROM marshal_evictions_all
"""

_MERGE_EVICTIONS = """
UNWIND $batch AS row
MATCH (b:Building {bbl: row.bbl})
MERGE (e:Event:WatchlineNode {event_id: row.event_id})
SET e.event_type       = 'Eviction',
    e.source_name      = 'Marshal',
    e.source_id        = row.source_id,
    e.source_record_id = row.source_record_id,
    e.event_date       = CASE WHEN row.event_date IS NULL THEN null
                              ELSE date(row.event_date) END,
    e.status           = row.status,
    e.violation_class  = row.violation_class,
    e.legal_authority  = $legal_authority,
    e.raw_record       = row.raw_record,
    e.created_at       = CASE WHEN e.created_at IS NULL
                              THEN datetime($now) ELSE e.created_at END
MERGE (b)-[:HAS_EVENT]->(e)
"""


def _property_type(v):
    if not v:
        return None
    return _PROPERTY_TYPE_NORMALIZE.get(v.strip().upper(), v.strip())


def _raw_record(row: dict) -> str:
    return json.dumps({
        "ejectment":        row["ejectment"],
        "evictionaptnum":   row["evictionaptnum"],
        "evictionaddress":  row["evictionaddress"],
        "marshalfirstname": row["marshalfirstname"],
        "marshallastname":  row["marshallastname"],
    })


def _eviction_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="marshal_evictions", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(EVICTIONS_SQL)
        batch: List[dict] = []
        for row in cur:
            courtindex = row["courtindexnumber"]
            docket = row["docketnumber"]
            batch.append({
                "event_id":         f"EVT-MARSHAL-{courtindex}-{docket}",
                "bbl":              row["bbl"],
                "violation_class":  _property_type(row["residentialcommercialind"]),
                "status":           row["evictionlegalpossession"],
                "event_date":       row["executeddate"].isoformat() if row["executeddate"] else None,
                "source_id":        courtindex,
                "source_record_id": docket,
                "raw_record":       _raw_record(row),
            })
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_marshal_evictions(session, conn) -> tuple:
    """MERGE Event(Eviction, Marshal) nodes and HAS_EVENT edges.

    Building-first: rows whose BBL has no Building node are skipped (no
    orphan Event nodes). Returns (total_processed, missing_bbl_count).
    """
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    missing_bbls: set = set()

    for batch in _eviction_batches(conn):
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(_MERGE_EVICTIONS, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 20_000 == 0:
            print(f"    {total:,} eviction rows processed ...")

    return total, len(missing_bbls)
