"""
watchline/ingest/acris/load.py

Reads ACRIS deed transfer records from PostgreSQL and returns a list of
dicts ready for Neo4j ingestion.

Source tables:
    real_property_master   -- document metadata (date, amount, doc type)
    real_property_legals   -- property BBL for each document
    real_property_parties  -- grantors (partytype=1) and grantees (partytype=2)

Scope:
    Document types: all deed subtypes (doctype ILIKE '%DEED%') — includes DEED,
                    CORRD, DEEDO, Mdeed, and other deed variants (ADR-005).
    Date range:     all dates (no lower bound — full history)
    BBL filter:     non-null, non-zero 10-digit BBL from real_property_legals

One output row per (documentid, bbl) pair. Multiple grantors and grantees
are aggregated into pipe-separated strings per document.

Note on cross-product: a document can have N grantors and M grantees.
Joining parties naively produces N×M rows per document. The CTEs below
pre-aggregate parties per document before the main join, avoiding this.
"""

from psycopg2.extras import RealDictCursor

from .config import pg_conn

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_QUERY = """
WITH grantors AS (
    SELECT
        documentid,
        string_agg(name, ' | ' ORDER BY name) AS grantor_names
    FROM real_property_parties
    WHERE partytype = 1
      AND name IS NOT NULL
      AND name != ''
    GROUP BY documentid
),
grantees AS (
    SELECT
        documentid,
        string_agg(name, ' | ' ORDER BY name) AS grantee_names
    FROM real_property_parties
    WHERE partytype = 2
      AND name IS NOT NULL
      AND name != ''
    GROUP BY documentid
)
SELECT
    m.documentid                      AS document_id,
    m.doctype                         AS doc_type,
    m.docdate::text                   AS docdate,
    m.recordedfiled::text             AS recorded_date,
    m.docamount                       AS doc_amount,
    m.pcttransferred                  AS pct_transferred,
    l.bbl                             AS bbl,
    g1.grantor_names                  AS grantor_names,
    g2.grantee_names                  AS grantee_names
FROM real_property_master m
JOIN real_property_legals l
    ON l.documentid = m.documentid
LEFT JOIN grantors g1
    ON g1.documentid = m.documentid
LEFT JOIN grantees g2
    ON g2.documentid = m.documentid
WHERE m.doctype ILIKE '%DEED%'
  AND l.bbl IS NOT NULL
  AND l.bbl != '0000000000'
ORDER BY m.docdate, m.documentid
"""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_deeds() -> list[dict]:
    """
    Read ACRIS deed transfers from PostgreSQL.

    Returns a list of dicts, one per (document, BBL) pair:
        document_id     str       ACRIS documentid (primary key)
        doc_type        str       deed subtype (DEED, CORRD, DEEDO, MEED, etc.)
        docdate         str|None  deed date as 'YYYY-MM-DD'
        recorded_date   str|None  recording date as 'YYYY-MM-DD'
        doc_amount      int|None  sale price in dollars
        pct_transferred float|None  fraction of ownership transferred
        bbl             str       10-digit BBL from real_property_legals
        grantor_names   str|None  pipe-separated grantor names
        grantee_names   str|None  pipe-separated grantee names
    """
    conn = pg_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("  Querying ACRIS deed records (all deed subtypes, all dates)...")
            cur.execute(_QUERY)
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    result = [dict(r) for r in rows]
    print(f"  {len(result):,} (document, BBL) pairs fetched.")
    return result
