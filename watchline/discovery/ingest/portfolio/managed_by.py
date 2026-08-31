"""managed_by.py — the MANAGEMENT layer: (:Building)-[:MANAGED_BY]->(:Manager).

The management nexus is a SELF-DISCLOSED, non-adversarial signal — nothing like the
beneficial-ownership problem. HPD registration records a managing **Agent** (a company
name + office address) on ~136k buildings, because the law requires a corporate/out-of-
state owner to designate one. So finding "who manages this building" is a direct
**extract → light-normalize → group-by**, NOT owner resolution: no Splink, no WCC, no
Louvain (the identity-component check showed 0 owner components exceed MAX_SIZE, so the
clustering machinery is for the ownership layer, not this one). A big manager's book is a
legitimate single group you want kept WHOLE — the opposite of what Louvain would do.

Why not reuse the address nexus: the current `Portfolio` captures management only by
accident (owners listing their manager's office as their own business address), which
conflates the manager's many *different owners* into one blob. Extracting the Agent role
directly gives the same footprint (Orsid: 231 buildings) as a clean hub-and-spoke, and
correctly labeled management rather than ownership.

The only resolution here is LIGHT and honest: manager names vary by corporate-form and
geographic suffixes, spacing, and typos (ORSID NY / ORSID REALTY CORP / ORSID NEW YORK;
AKAM ASSOCIATES INC / AKAM ASSOCATES). ``norm_manager`` strips the generic suffixes and
keeps the distinctive brand tokens. It is intentionally simple — a small residual tail
(concatenations like ORSIDNY, typo'd brand tokens) is left un-merged rather than risking
over-merge of two different managers who share a common word; tighten later if needed.

Neo4j-free extraction (returns a DataFrame); ``load_managed_by`` does the KG write. New
label/rel (:Manager / MANAGED_BY) — declare them in the graph type before loading.
"""
from __future__ import annotations

import re

import pandas as pd

# Provenance on the derived Manager nodes / MANAGED_BY edges. Higher reliability than the
# inferred ownership layer (the agent is disclosed), but still a normalized grouping.
MANAGER_METHOD = "hpd-managing-agent"

# Generic tokens dropped to reduce a manager name to its distinctive brand. Corporate forms,
# NYC-geographic qualifiers, and management descriptors — the parts that vary across a single
# manager's filings while the brand (ORSID, AKAM, FIRSTSERVICE) stays put.
_GENERIC = frozenset("""
INC LLC LLP LP CORP CORPORATION CO COMPANY COMPANIES
NY NYC USA US NEW YORK
REALTY REALTORS REAL ESTATE MANAGEMENT MGMT MGT PROPERTIES PROPERTY
RESIDENTIAL COMMERCIAL ASSOCIATES ASSOCIATION SERVICES SERVICE ORGANIZATION
GROUP ENTERPRISES ENTERPRISE HOLDINGS HOLDING PARTNERS PARTNERSHIP APARTMENT APARTMENTS
THE OF AND AT
""".split())


def norm_manager(name) -> str | None:
    """Canonical manager key: uppercase, strip punctuation, drop generic/geo/form tokens,
    keep the distinctive brand tokens. Falls back to the full collapsed name when stripping
    would leave nothing (a name made only of generic words)."""
    if not isinstance(name, str) or not name.strip():
        return None
    s = re.sub(r"[^A-Z0-9 ]", " ", name.upper())          # drop punctuation (& , . ' -)
    toks = [t for t in s.split() if t and t not in _GENERIC]
    key = " ".join(toks)
    if len(key) < 3:                                       # only generics left -> keep full name
        key = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", name.upper())).strip()
    return key or None


# Latest registration per building, its managing Agent (company name + office address).
AGENT_SQL = """
WITH latest AS (
  SELECT DISTINCT ON (btrim(bbl)) btrim(bbl) AS bbl, registrationid
  FROM hpd_registrations
  ORDER BY btrim(bbl), lastregistrationdate DESC NULLS LAST
)
SELECT DISTINCT ON (l.bbl)
       l.bbl                                                             AS bbl,
       upper(btrim(c.corporationname))                                  AS agent_name,
       upper(btrim(concat_ws(' ', c.businesshousenumber, c.businessstreetname))) AS agent_addr
FROM latest l
JOIN hpd_contacts c ON c.registrationid = l.registrationid
WHERE c.type = 'Agent'
  AND c.corporationname IS NOT NULL AND length(btrim(c.corporationname)) > 3
ORDER BY l.bbl, length(btrim(c.corporationname)) DESC
"""


def extract_managed_by(conn) -> pd.DataFrame:
    """One row per building with a managing agent: ``[bbl, manager_id, manager_name,
    manager_addr]``. ``manager_id`` is the normalized key; ``manager_name`` is the most
    common raw agent name in that key group (a readable label)."""
    df = pd.read_sql(AGENT_SQL, conn)
    df["manager_id"] = df["agent_name"].map(norm_manager)
    df = df[df["manager_id"].notna()].copy()

    # Display label = the most frequent raw agent name per key.
    label = (df.groupby(["manager_id", "agent_name"]).size().rename("n").reset_index()
               .sort_values("n", ascending=False)
               .drop_duplicates("manager_id").set_index("manager_id")["agent_name"])
    df["manager_name"] = df["manager_id"].map(label)
    df = df.rename(columns={"agent_addr": "manager_addr"})
    return df[["bbl", "manager_id", "manager_name", "manager_addr"]].reset_index(drop=True)


def manager_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Managers ranked by building count (the management nexuses)."""
    return (df.groupby(["manager_id", "manager_name"])["bbl"].nunique()
              .rename("buildings").reset_index().sort_values("buildings", ascending=False))


# --- KG write (declare :Manager / MANAGED_BY in the graph type before running) ----------
_CLEANUP = [
    "MATCH ()-[r:MANAGED_BY]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS",
    "MATCH (m:Manager) CALL (m) { DETACH DELETE m } IN TRANSACTIONS OF 5000 ROWS",
]
_LOAD = """
UNWIND $batch AS row
MERGE (m:Manager:WatchlineNode {manager_id: row.manager_id})
  ON CREATE SET m.name = row.manager_name, m.method = $method, m.generated_at = datetime()
MATCH (b:Building {bbl: row.bbl})
MERGE (b)-[:MANAGED_BY]->(m)
"""
_COUNT = """
MATCH (m:Manager)<-[:MANAGED_BY]-(b:Building)
WITH m, count(DISTINCT b) AS n SET m.building_count = n
"""


def load_managed_by(driver, conn, *, database: str, batch_size: int = 5000) -> int:
    """Rebuild the management layer: drop existing :Manager/MANAGED_BY, then write fresh."""
    df = extract_managed_by(conn)
    rows = df.to_dict("records")
    with driver.session(database=database) as s:
        for stmt in _CLEANUP:
            s.run(stmt)
        for i in range(0, len(rows), batch_size):
            s.run(_LOAD, batch=rows[i:i + batch_size], method=MANAGER_METHOD)
        s.run(_COUNT)
    return len(rows)


if __name__ == "__main__":  # read-only summary (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    df = extract_managed_by(conn)
    conn.close()
    s = manager_summary(df)
    print(f"buildings with a managing agent: {df['bbl'].nunique():,}")
    print(f"distinct managers: {len(s):,}")
    print("\ntop managers by building count:")
    print(s.head(15).to_string(index=False))
    orsid = s[s["manager_id"].str.contains("ORSID", na=False)]
    print(f"\nORSID -> {int(orsid['buildings'].sum())} buildings across "
          f"{len(orsid)} key(s): {orsid['manager_id'].tolist()}")
