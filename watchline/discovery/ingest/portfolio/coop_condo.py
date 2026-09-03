"""coop_condo.py — tag ``Building.coop_condo`` from the HPD registration contactdescription.

A co-op/condo building is owned by its shareholders / unit-owners, NOT a single landlord, so it
has no place in the ownership (OwnerGroup) layer. Worse, including it manufactures phantom "owners":
the management firm that signs a co-op/condo's HPD registration appears as the HeadOfficer across
hundreds of unrelated boards, so the owner-resolution model fuses those boards into one giant
"owner" (measured: e.g. a management officer resolving to a 231-building "portfolio" that is 99%
co-op/condo). WoW treats co-ops/condos specially for the same reason.

We classify a building as co-op/condo when **> 50% of its owner-role HPD registration contacts**
(HeadOfficer / IndividualOwner / CorporateOwner) are described ``CO-OP`` or ``CONDO``, and set
``Building.coop_condo = true``. ``owner_groups.py`` then counts only rental buildings and drops
co-op/condo-dominated groups. Read-only on Postgres (the WoW dump); the only KG write is the flag.
"""
from __future__ import annotations

# A building is co-op/condo if the majority of its owner-role registrations say so (dump: WoW's raw
# HPD). Same classifier used for the contamination audit, so the wired result matches the audit.
_COOP_CONDO_SQL = """
    SELECT g.bbl AS bbl
    FROM hpd_contacts c
    JOIN hpd_registrations_grouped_by_bbl_with_contacts g ON g.registrationid = c.registrationid
    WHERE c.type IN ('HeadOfficer','IndividualOwner','CorporateOwner')
    GROUP BY g.bbl
    HAVING avg(CASE WHEN c.contactdescription IN ('CO-OP','CONDO') THEN 1.0 ELSE 0.0 END) > 0.5
"""

# Clear any prior flag (idempotent rebuild), then set it on the classified bbls.
_CLEAR = ("MATCH (b:Building) WHERE b.coop_condo IS NOT NULL "
          "CALL (b) { SET b.coop_condo = NULL } IN TRANSACTIONS OF 10000 ROWS")
_SET = """
UNWIND $bbls AS bbl
MATCH (b:Building {bbl: bbl})
SET b.coop_condo = true
"""


def coop_condo_bbls(conn) -> list[str]:
    """The co-op/condo bbl set from the WoW dump (owner-role contactdescription plurality)."""
    cur = conn.cursor()
    cur.execute(_COOP_CONDO_SQL)
    return [str(r[0]).strip() for r in cur.fetchall()]


def tag_coop_condo(conn, driver, *, database: str, batch_size: int = 10000) -> int:
    """Set ``Building.coop_condo = true`` on every co-op/condo bbl (clearing prior flags first).
    Returns the number of buildings flagged. Buildings not matched keep no flag (= rental/other)."""
    bbls = coop_condo_bbls(conn)
    with driver.session(database=database) as s:
        s.run(_CLEAR)
        for i in range(0, len(bbls), batch_size):
            s.run(_SET, bbls=bbls[i:i + batch_size])
    return len(bbls)


if __name__ == "__main__":  # read-only count (PGDATABASE -> wow dump; writes only the flag)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE
    conn = pg_conn(); driver = neo4j_driver()
    n = tag_coop_condo(conn, driver, database=NEO4J_DISCOVERY_DATABASE)
    conn.close(); driver.close()
    print(f"Building.coop_condo set on {n:,} co-op/condo buildings")
