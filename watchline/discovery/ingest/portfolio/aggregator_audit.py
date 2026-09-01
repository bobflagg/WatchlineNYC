"""aggregator_audit.py — classify high-degree business addresses as AGGREGATOR vs OPERATOR,
using the OwnerGroup layer, to produce a precision-safe mask list for the address-edge step.

A business address shared by many distinct landlords (high degree) is either:
  * an AGGREGATOR — a management/agent megaoffice where many UNRELATED owners file (Orsid's
    156 W 56 St: 216 owners). CONNECTED_BY_ADDRESS glues them into one bogus portfolio -> MASK.
  * an OPERATOR   — one owner running many LLCs from their own office. Here the address glue is
    correct, so it must NOT be masked.

Degree alone can't tell them apart (both look like "many landlords at one address"). The
OwnerGroup layer can: count how many distinct OWNERS the filers resolve to (distinct OwnerGroups
+ each ungrouped filer as its own owner). Filers that collapse to one/few owners = an operator
(keep); filers spanning many owners = an aggregator (mask). This protects a same-owner-many-LLCs
office from being masked, which surname- or degree-only rules can't.

Read-only, Neo4j-only. Requires the OwnerGroup layer materialized (--step ownergroup). Emits the
mask list (aggregators) and the protected operator exceptions.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE

# A shared address on more distinct landlords than this is a mask candidate (matches the Splink
# AGGREGATOR_DEGREE). Below it, address glue is left alone.
MIN_DEGREE = 25
# An address whose filers resolve to <= this many distinct owners is an OPERATOR (one owner's
# LLCs) and is PROTECTED from masking, however high its raw degree.
OPERATOR_MAX_OWNERS = 2

_SUFFIX = re.compile(r",\s*[A-Z ]+\s+NY\s*$")


def _norm(addr) -> str:
    if not isinstance(addr, str):
        return ""
    return re.sub(r"\s+", " ", _SUFFIX.sub("", addr.upper().strip())).strip()


_ROWS = """
MATCH (l:Landlord) WHERE l.bizaddr IS NOT NULL
OPTIONAL MATCH (l)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
RETURN l.nodeid AS n, l.bizaddr AS addr, l.name AS name, og.owner_group_id AS og
"""


def audit(driver, *, database: str, min_degree: int = MIN_DEGREE) -> list[dict]:
    """Per high-degree address: degree (distinct filers), distinct owners (OwnerGroups + ungrouped
    filers), and kind (aggregator|operator). Sorted by degree desc."""
    with driver.session(database=database) as s:
        rows = s.run(_ROWS).data()

    filers: dict[str, set] = defaultdict(set)       # addr -> {nodeid}
    owners: dict[str, set] = defaultdict(set)       # addr -> owner keys (og id, or ('solo', nodeid))
    names: dict[str, set] = defaultdict(set)        # addr -> {landlord name}
    for r in rows:
        a = _norm(r["addr"])
        if not a:
            continue
        filers[a].add(r["n"])
        owners[a].add(r["og"] if r["og"] is not None else ("solo", r["n"]))
        if r["name"]:
            names[a].add(r["name"])

    out = []
    for a, fset in filers.items():
        deg = len(fset)
        if deg <= min_degree:
            continue
        n_owners = len(owners[a])
        out.append({
            "address": a,
            "degree": deg,
            "owners": n_owners,
            "kind": "operator" if n_owners <= OPERATOR_MAX_OWNERS else "aggregator",
            "sample": sorted(names[a])[:3],
        })
    return sorted(out, key=lambda d: d["degree"], reverse=True)


def main() -> int:
    driver = neo4j_driver()
    try:
        res = audit(driver, database=NEO4J_DISCOVERY_DATABASE)
    finally:
        driver.close()
    if not res:
        print("No OwnerGroups found — run --step ownergroup first (audit needs the ownership layer).")
        return 1

    aggr = [r for r in res if r["kind"] == "aggregator"]
    oper = [r for r in res if r["kind"] == "operator"]
    print(f"high-degree addresses (> {MIN_DEGREE} filers): {len(res)}   "
          f"-> {len(aggr)} aggregator (MASK), {len(oper)} operator (KEEP)\n")

    print(f"MASK — aggregator addresses (filers span > {OPERATOR_MAX_OWNERS} owners):")
    print(f"  {'address':<44}{'deg':>5}{'owners':>7}   sample filers")
    for r in aggr[:40]:
        print(f"  {r['address'][:43]:<44}{r['degree']:>5}{r['owners']:>7}   {', '.join(r['sample'])[:42]}")

    print(f"\nKEEP — operator exceptions (high degree but <= {OPERATOR_MAX_OWNERS} owners; do NOT mask):")
    if not oper:
        print("  (none — every high-degree address resolves to many owners)")
    for r in oper[:20]:
        print(f"  {r['address'][:43]:<44}{r['degree']:>5}{r['owners']:>7}   {', '.join(r['sample'])[:42]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
