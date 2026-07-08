"""
Watchline agents pipeline -- load stage.

Reads managing agent contacts from wow_bldgs.allcontacts (JSONB column),
normalises names and addresses, and returns a deduplicated list of
(canonical_agent_key, display_name, business_address, [bbls]) tuples
ready for Neo4j writes.

Source: wow_bldgs.allcontacts, filtered to title='Agent'.
Contact role vocabulary in allcontacts:
    Agent       -- the managing agent (the target of this pipeline)
    HeadOfficer -- the legally responsible person
    Officer     -- secondary officer
    SiteManager -- on-site manager (subordinate to Agent; excluded here)
    Corporation -- corporate owner name

Only contacts with title='Agent' and a non-null address are ingested.
Multiple Agent contacts per building are all ingested; a building with
two managing agents will produce two ManagedBy Relationship nodes.
"""

import re
import uuid
from collections import defaultdict

from psycopg2.extras import RealDictCursor

from .config import pg_conn

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

AGENT_QUERY = """
SELECT
    b.bbl,
    contact->>'title'                   AS contact_role,
    contact->>'value'                   AS raw_name,
    contact->'address'->>'housenumber'  AS biz_housenumber,
    contact->'address'->>'streetname'   AS biz_streetname,
    contact->'address'->>'apartment'    AS biz_apartment,
    contact->'address'->>'city'         AS biz_city,
    contact->'address'->>'state'        AS biz_state,
    contact->'address'->>'zip'          AS biz_zip
FROM wow_bldgs b,
     jsonb_array_elements(b.allcontacts) AS contact
WHERE contact->>'title' = 'Agent'
  AND contact->'address' IS NOT NULL
  AND jsonb_typeof(contact->'address') = 'object'
  AND contact->'address'->>'housenumber' IS NOT NULL
  AND contact->'address'->>'streetname'  IS NOT NULL
  AND b.bbl IS NOT NULL
ORDER BY b.bbl
"""


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm_name(raw: str | None) -> str:
    """
    Normalise a contact name for deduplication.
    - Uppercase
    - Collapse whitespace
    - Strip leading/trailing punctuation artifacts
    """
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.upper().strip().strip(","))


def _norm_address(housenumber: str, streetname: str,
                  apartment: str | None, zipcode: str | None) -> str:
    """
    Produce a canonical address string used as the deduplication key.
    Format: '{HOUSENUMBER} {STREETNAME} APT {APT} {ZIP}'
    Apartment and ZIP are optional; omitted when null.

    Note: this is a lightweight normalisation. Geosupport-level
    standardisation (as used by JustFix) would be more robust but
    requires an external geocoder dependency. This is sufficient for
    first-pass deduplication; a future version should use Geosupport.
    """
    parts = [housenumber.upper().strip(), streetname.upper().strip()]
    if apartment and apartment.strip():
        parts.append(f"APT {apartment.upper().strip()}")
    if zipcode and zipcode.strip():
        parts.append(zipcode.strip())
    return " ".join(parts)


def _agent_key(norm_name: str, norm_address: str) -> str:
    """
    Deduplication key for a managing agent.
    Agents with the same normalised name AND address are the same entity.
    Name-only or address-only matches are not treated as the same agent —
    this avoids collapsing different management companies that happen to
    share a common name fragment.
    """
    return f"{norm_name}||{norm_address}"


def _canonical_id(agent_key: str) -> str:
    """
    Stable canonical_id for a ManagingAgent Actor.
    Uses UUID5 (name-based) so the same agent always gets the same ID,
    making the pipeline idempotent across runs.
    Namespace: DNS (arbitrary but fixed).
    """
    return f"MGT-{uuid.uuid5(uuid.NAMESPACE_DNS, agent_key)}"


def _display_name(names: list[str]) -> str:
    """
    Choose the most frequent non-empty name variant as the display name.
    Ties broken by longest name (usually the most complete form).
    """
    if not names:
        return "Unknown"
    from collections import Counter
    counts = Counter(n for n in names if n)
    if not counts:
        return "Unknown"
    max_count = max(counts.values())
    candidates = [n for n, c in counts.items() if c == max_count]
    return max(candidates, key=len)


# ---------------------------------------------------------------------------
# Fetch and deduplicate
# ---------------------------------------------------------------------------

def fetch_agents() -> list[dict]:
    """
    Read all Agent contacts from wow_bldgs, normalise, deduplicate,
    and return a list of agent dicts ready for Neo4j ingestion.

    Each dict:
        canonical_id    str       stable ID derived from name+address
        display_name    str       most frequent name variant
        norm_name       str       normalised name (for IdentityObservation)
        norm_address    str       normalised address string
        biz_housenumber str
        biz_streetname  str
        biz_apartment   str | None
        biz_zip         str | None
        bbls            list[str] all buildings linked to this agent
        raw_names       list[str] all raw name variants seen
    """
    conn = pg_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("  Querying wow_bldgs.allcontacts for Agent contacts ...")
            cur.execute(AGENT_QUERY)
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    print(f"  {len(rows):,} Agent contact rows fetched.")

    # Group by deduplication key
    agents: dict[str, dict] = {}

    for row in rows:
        norm_name = _norm_name(row["raw_name"])
        norm_addr = _norm_address(
            row["biz_housenumber"] or "",
            row["biz_streetname"]  or "",
            row["biz_apartment"],
            row["biz_zip"],
        )

        if not norm_name and not norm_addr:
            continue  # Skip entirely empty contacts

        key        = _agent_key(norm_name, norm_addr)
        canon_id   = _canonical_id(key)
        bbl        = row["bbl"].strip() if row["bbl"] else None

        if canon_id not in agents:
            agents[canon_id] = {
                "canonical_id":    canon_id,
                "norm_name":       norm_name,
                "norm_address":    norm_addr,
                "biz_housenumber": (row["biz_housenumber"] or "").upper().strip(),
                "biz_streetname":  (row["biz_streetname"]  or "").upper().strip(),
                "biz_apartment":   (row["biz_apartment"]   or "").upper().strip() or None,
                "biz_zip":         (row["biz_zip"]         or "").strip() or None,
                "bbls":            [],
                "raw_names":       [],
            }

        if bbl:
            agents[canon_id]["bbls"].append(bbl)
        agents[canon_id]["raw_names"].append(row["raw_name"] or "")

    # Resolve display names and deduplicate BBL lists
    result = []
    for agent in agents.values():
        agent["display_name"] = _display_name(agent["raw_names"])
        agent["bbls"]         = sorted(set(agent["bbls"]))
        result.append(agent)

    print(f"  {len(result):,} unique managing agents after deduplication.")
    return result
