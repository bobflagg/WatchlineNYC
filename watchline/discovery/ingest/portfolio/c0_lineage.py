"""c0_lineage.py — Level-0 (C0) source-row lineage + residual collision-risk (Option B, Phase 2).

C0 governs the base `(name, address)` dedup (`party_reference`). This module **retains the contributing
HPD source rows** for a party reference and bounds the **residual collision risk**. Read-only.

What is and isn't detectable (honest, per review):
- A Level-0 **collapse** (≥2 landlord nodes → one `party_reference_id`) is same-key *by construction*
  (nodes differ only in normalized-away formatting — borough suffix, case, whitespace), so a collapse
  carries no attribute contradiction to find. The keying is not over-collapsing.
- The genuine risk — two **different people** sharing an exact name+address — sits *inside* a single
  reference and is **not** decidable from HPD fields (no discriminating identifier). **Absence of a
  contradiction does not establish same identity.** So C0 residual risk is bounded and reported, and the
  contributing rows are retained for **human sampling** (eval `§8.1` C0 protected stratum), not auto-judged.
"""
from __future__ import annotations

from collections import defaultdict


def collapse_summary(collapses: dict, node_bbls: dict) -> dict:
    """Pure: bound the C0 collapse population — ``{collapses, nodes, buildings_affected}``. ``collapses``:
    ``{party_reference_id: [nodeid, …]}`` (≥2); ``node_bbls``: ``{nodeid: [bbl]}``."""
    nodes = sum(len(v) for v in collapses.values())
    bbls: set = set()
    for nids in collapses.values():
        for n in nids:
            bbls.update(node_bbls.get(n, []))
    return {"collapses": len(collapses), "nodes": nodes, "buildings_affected": len(bbls)}


# Retained lineage: the HPD registration contact rows on a party reference's buildings. Kept so a human
# adjudicator can inspect whether a reference's records evidence more than one real party (the residual
# ambiguity above); this is the C1/C0 lineage requirement, not an automated verdict.
_LINEAGE_SQL = """
    SELECT g.bbl AS bbl, c.registrationid AS registrationid, c.type AS role,
           coalesce(c.corporationname, trim(concat_ws(' ', c.firstname, c.lastname))) AS name,
           trim(concat_ws(' ', c.businesshousenumber, c.businessstreetname, c.businessapartment)) AS addr
    FROM hpd_contacts c
    JOIN hpd_registrations_grouped_by_bbl_with_contacts g ON g.registrationid = c.registrationid
    WHERE g.bbl = ANY(%s::text[])
    ORDER BY g.bbl, c.type
"""


def read_contact_lineage(pg_conn, bbls: list[str]) -> list[dict]:
    """Retain the HPD registration-contact source rows (registrationid, bbl, role, name, addr) for `bbls`."""
    want = [str(b).strip() for b in bbls]
    cur = pg_conn.cursor()
    cur.execute(_LINEAGE_SQL, (want,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
