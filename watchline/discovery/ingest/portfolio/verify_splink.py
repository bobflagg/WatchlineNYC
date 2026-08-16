"""verify_splink.py — post-reconcile guard for Mechanism B (CONNECTED_BY_SPLINK).

Repeatable checks on the LIVE discovery KG after `pipeline --step splink` + `--step
reconcile`. Read-only (MATCH/RETURN only). Two tiers:

  HARD invariants (exit 1 on failure — the "pure win" gates):
    1. CONNECTED_BY_SPLINK edges exist            -> the splink step actually ran
    2. 0 edges link different surnames            -> emit precision holds on the live graph
    3. 0 splink-linked pairs in different portfolios
         WCC can't split a splink clique, but Louvain on a component > MAX_SIZE could;
         this catches a merge that got silently undone.

  REVIEW (printed + soft-flagged — recall-bias makes these judgement calls, not invariants):
    4. target operators consolidated (Croman/Rashad canaries) + their APPARENT_CONTROL anchor
    5. portfolio size distribution + the largest portfolios (mega-merge / connector eyeball)

  uv run python -m watchline.discovery.ingest.portfolio.verify_splink

Queries are module constants so this file doubles as the reference .cypher.
"""
from __future__ import annotations

import sys

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE

# Canary operators: known real single-operators that WoW fragmented; B should consolidate.
TARGETS = ["CROMAN", "RASHAD"]
# Portfolios bigger than this are listed for manual review (not an auto-fail: a real
# large operator legitimately exceeds it — a human decides operator vs. merge-blob).
BLOWUP_REVIEW_CEILING = 500

Q_EDGES_PRESENT = "MATCH ()-[r:CONNECTED_BY_SPLINK]->() RETURN count(r) AS n"

# Surname = last whitespace token of the landlord name (persons are "FIRST LAST").
Q_CROSS_SURNAME = """
MATCH (a:Landlord)-[:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b)
  AND toUpper(split(a.name, ' ')[-1]) <> toUpper(split(b.name, ' ')[-1])
RETURN count(*) AS n, collect(DISTINCT a.name + ' <> ' + b.name)[0..8] AS examples
"""

Q_LOUVAIN_SCATTER = """
MATCH (a:Landlord)-[:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b)
MATCH (a)-[:MEMBER_OF]->(pa:Portfolio), (b)-[:MEMBER_OF]->(pb:Portfolio)
WHERE pa <> pb
RETURN count(*) AS n, collect(DISTINCT a.name)[0..8] AS examples
"""

Q_TARGET = """
MATCH (l:Landlord)-[:MEMBER_OF]->(p:Portfolio)
WHERE l.name CONTAINS $name
RETURN count(DISTINCT p) AS portfolios, count(DISTINCT l) AS nodes,
       collect(DISTINCT p.building_count) AS building_counts
"""

Q_TARGET_ANCHOR = """
MATCH (l:Landlord)-[:MEMBER_OF]->(p:Portfolio) WHERE l.name CONTAINS $name
WITH p ORDER BY p.building_count DESC LIMIT 1
MATCH (anchor:Landlord)-[:APPARENT_CONTROL]->(:Building)-[:IN_PORTFOLIO]->(p)
RETURN DISTINCT anchor.name AS anchor, count(*) AS buildings
ORDER BY buildings DESC
"""

Q_SIZE_DIST = """
MATCH (p:Portfolio)
WITH p.building_count AS bc
RETURN count(*) AS portfolios, max(bc) AS max_bldgs,
       percentileCont(bc, 0.99) AS p99,
       sum(CASE WHEN bc > 300 THEN 1 ELSE 0 END) AS over_300,
       sum(CASE WHEN bc > $ceiling THEN 1 ELSE 0 END) AS over_ceiling
"""

Q_TOP_PORTFOLIOS = """
MATCH (l:Landlord)-[:MEMBER_OF]->(p:Portfolio)
WITH p, count(DISTINCT l) AS members,
     count(DISTINCT toUpper(split(l.name, ' ')[-1])) AS surnames
RETURN p.portfolio_id AS pid, p.building_count AS bldgs, members, surnames
ORDER BY bldgs DESC LIMIT 12
"""


def main() -> int:
    driver = neo4j_driver()
    failures: list[str] = []
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        one = lambda q, **p: s.run(q, **p).single()
        rows = lambda q, **p: [r.data() for r in s.run(q, **p)]

        print("=== HARD invariants ===")

        n_edges = one(Q_EDGES_PRESENT)["n"]
        ok = n_edges > 0
        failures += [] if ok else ["no CONNECTED_BY_SPLINK edges — did --step splink run before reconcile?"]
        print(f"[{'PASS' if ok else 'FAIL'}] CONNECTED_BY_SPLINK edges present: {n_edges:,}")

        r = one(Q_CROSS_SURNAME)
        ok = r["n"] == 0
        failures += [] if ok else [f"{r['n']} CONNECTED_BY_SPLINK edges link different surnames"]
        print(f"[{'PASS' if ok else 'FAIL'}] cross-surname edges: {r['n']}  (want 0)")
        if not ok:
            for ex in r["examples"]:
                print(f"         {ex}")

        r = one(Q_LOUVAIN_SCATTER)
        ok = r["n"] == 0
        failures += [] if ok else [f"{r['n']} splink-linked pairs landed in different portfolios (Louvain scatter)"]
        print(f"[{'PASS' if ok else 'FAIL'}] splink pairs split across portfolios: {r['n']}  (want 0)")
        if not ok:
            print(f"         e.g. {r['examples']}")

        print("\n=== REVIEW (judgement — recall-biased design) ===")

        for name in TARGETS:
            t = one(Q_TARGET, name=name)
            counts = sorted((t["building_counts"] or []), reverse=True)
            flag = "" if t["portfolios"] == 1 else "  <- spans >1 portfolio; check the split is a stray, not a break"
            print(f"{name}: {t['nodes']} nodes -> {t['portfolios']} portfolio(s), buildings {counts}{flag}")
            for a in rows(Q_TARGET_ANCHOR, name=name):
                hit = "OK" if name in (a["anchor"] or "").upper() else "!! anchor is NOT the operator"
                print(f"     APPARENT_CONTROL anchor: {a['anchor']} ({a['buildings']} buildings)  [{hit}]")

        d = one(Q_SIZE_DIST, ceiling=BLOWUP_REVIEW_CEILING)
        print(f"\nportfolios {d['portfolios']:,}   max {d['max_bldgs']} bbls   "
              f"p99 {round(d['p99'] or 0)}   >300: {d['over_300']:,}   "
              f">{BLOWUP_REVIEW_CEILING}: {d['over_ceiling']:,} (review these)")
        print("largest portfolios (many distinct surnames + huge = possible over-merge blob):")
        print(f"  {'portfolio_id':<28}{'bldgs':>7}{'members':>9}{'surnames':>10}")
        for r in rows(Q_TOP_PORTFOLIOS):
            print(f"  {str(r['pid']):<28}{r['bldgs']:>7}{r['members']:>9}{r['surnames']:>10}")

    driver.close()

    print("\n=== VERDICT ===")
    if failures:
        print("FAIL — hard invariants broken:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — all hard invariants hold. Review the numbers above for blow-up / connectors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
