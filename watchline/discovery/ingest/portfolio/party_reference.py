"""party_reference.py — stable party-reference keying (Option B, Phase 2; contracts C1 + C0).

A `party_reference` is the normalized `(name, business-address)` party — the WoW
`landlords_with_connections` node grain. Its **id is a stable hash of the normalized key**, *not* the
`nodeid` (which `landlords_with_connections` regenerates each rebuild). The id is stable **only within a
normalization version**; bumping `NORMALIZATION_VERSION` is a lifecycle event (predecessor/successor
lineage), so the version is stamped into the id.

Two `nodeid`s that map to one `party_reference_id` are a **Level-0 collapse** (C0) — the base
`(name,address)` dedup, treated as a *governed* identity transformation. This module **detects the
collapse** (an indicator); it does **not** claim the collapsed rows are the same real party. Absence of a
contradiction does not establish same identity, and the collapse is irreversible. Estimating residual
collision *risk* needs source-row lineage `(registrationid, bbl, role, date)` from Postgres — the C0 eval
piece — which this graph-only unit records as a follow-on, not a claim.

Pure keying (`normalize_name`, `normalize_address`, `party_reference_id`) is hermetic; `read_party_refs`
is a read-only Neo4j pass.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .aggregator_audit import _norm as normalize_address   # single source of truth (upper, strip borough, ws)

#: Bump this when the normalization below changes — the id then changes, so a bump is a lifecycle event
#: (party-reference predecessor/successor lineage), never a silent hash drift (C1).
NORMALIZATION_VERSION = "n1"

_WS = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Conservative name normalization for the reference key: upper-case, collapse whitespace, trim
    surrounding punctuation. **Corporate suffixes are NOT stripped** (that is a resolution decision, not a
    reference-identity one) — so distinct entities like `ACME LLC` vs `ACME CORP` keep distinct keys."""
    if not name:
        return ""
    return _WS.sub(" ", name.upper().strip()).strip(" .,-")


def party_reference_id(name: str | None, bizaddr: str | None) -> str:
    """Stable, rebuild-independent id: `PR-<version>-<12-hex>` over the normalized `(name, address)`.
    Deterministic (SHA-1, not the salted built-in `hash`), so it is identical across runs and machines."""
    key = normalize_name(name) + "\x1f" + normalize_address(bizaddr)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"PR-{NORMALIZATION_VERSION}-{h}"


# --- graph read (read-only) ---------------------------------------------------------------------

_Q_LANDLORDS = "MATCH (l:Landlord) RETURN l.nodeid AS nodeid, l.name AS name, l.bizaddr AS bizaddr"


def read_party_refs(driver, *, database: str) -> dict:
    """Read every `:Landlord` and key it. Returns:

    - ``nodeid_to_prid``: ``{nodeid: party_reference_id}`` — the within-run join handle → stable id;
    - ``collapses``: ``{party_reference_id: [nodeid, …]}`` for **Level-0 collapses** (≥2 nodeids sharing a
      key) — the governed C0 dedup, reported as an indicator (not a same-identity claim);
    - ``n_nodes`` / ``n_refs``: counts.
    """
    with driver.session(database=database) as s:
        rows = [dict(r) for r in s.run(_Q_LANDLORDS)]
    nodeid_to_prid: dict = {}
    members: dict = defaultdict(list)
    for r in rows:
        pid = party_reference_id(r["name"], r["bizaddr"])
        nodeid_to_prid[r["nodeid"]] = pid
        members[pid].append(r["nodeid"])
    collapses = {pid: nids for pid, nids in members.items() if len(nids) >= 2}
    return {"nodeid_to_prid": nodeid_to_prid, "collapses": collapses,
            "n_nodes": len(rows), "n_refs": len(members)}
