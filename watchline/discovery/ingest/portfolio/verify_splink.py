"""verify_splink.py — post-reconcile guard for Mechanism B (CONNECTED_BY_SPLINK).

Repeatable checks on the LIVE discovery KG after `pipeline --step splink` + `--step
reconcile`. Read-only (MATCH/RETURN only). Two tiers:

  HARD invariants (exit 1 on failure — the "pure win" gates):
    1. CONNECTED_BY_SPLINK edges exist            -> the splink step actually ran
    2. 0 MODEL edges link different surnames       -> model emit precision holds (registered-LLC
         edges link by owner ENTITY and legitimately span surnames -> reported as info, not failed)
    3. splink-linked pairs in different portfolios: WARN if <= SCATTER_WARN_MAX, else FAIL
         WCC can't split a splink clique, but Louvain on a component > MAX_SIZE could; a
         tiny count is recall-only (never a wrong fusion) and tolerated as a WARN, more is
         a hard FAIL that points at a real merge silently undone.

  REVIEW (printed + soft-flagged — recall-bias makes these judgement calls, not invariants):
    4. target operators consolidated (Croman/Rashad canaries) + their APPARENT_CONTROL anchor
    5. portfolio size distribution + the largest portfolios (mega-merge / connector eyeball)
    6. layer divergence — the three counts where Portfolio / Manager / OwnerGroup disagree (each
         is value a single layer can't give); WARN if any collapses to 0 (regression toward blur)

  uv run python -m watchline.discovery.ingest.portfolio.verify_splink

Queries are module constants so this file doubles as the reference .cypher.
"""
from __future__ import annotations

import sys

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE

# Canary operators: verified real RENTAL single-operators that WoW fragmented; B should consolidate.
# DIVYA RASHAD was removed: it is a co-op/condo MANAGEMENT signatory (99% co-op/condo buildings),
# correctly DROPPED from the ownership layer by the co-op/condo filter (coop_condo.py) — not a rental
# owner. CROMAN and KADDEN are verified rentals (0% co-op/condo), so they remain valid canaries.
TARGETS = ["CROMAN", "KADDEN"]
# OwnerGroup canary: these verified rental operators MUST each resolve to exactly one :OwnerGroup
# (curated overrides force-merge them). >1 = a merge regression; 0 = the group was dropped (e.g. the
# co-op/condo exclusion). A soft WARN, not a hard fail, and skipped if the layer isn't materialized.
OWNER_TARGETS = ["CROMAN", "KADDEN"]
# Portfolios bigger than this are listed for manual review (not an auto-fail: a real
# large operator legitimately exceeds it — a human decides operator vs. merge-blob).
BLOWUP_REVIEW_CEILING = 500

# The Louvain-scatter hard gate is SIZE-AWARE. A model splink pair split across portfolios whose
# owner (OwnerGroup) is <= MAX_SIZE genuinely should have stayed together — a real regression. But
# an owner group LARGER than MAX_SIZE (e.g. ERIC MOORE, ~430 bldgs via LLC merges) MUST be split by
# Louvain to honor the cap, so its scatter is size-forced and recall-only — reported as info, not
# failed. Below the cap, <= SCATTER_WARN_MAX scattered pairs is a WARN; more is a FAIL.
MAX_SIZE = 300           # mirror algorithms.MAX_SIZE (kept literal so verify stays dependency-light)
SCATTER_WARN_MAX = 2

# The hard Louvain-scatter gate applies ONLY to model (Fellegi-Sunter) edges. The other
# CONNECTED_BY_SPLINK methods — curated same-owner overrides and deterministic registered-LLC
# links — are asserted/deterministic and deliberately include groups that Louvain MUST
# size-split (a curated >MAX_SIZE operator, or a large single-entity LLC), so a pair of theirs
# landing in two portfolios is expected-by-design, not a silently-undone model merge. Those
# are reported as review info instead of failing the gate. (Method strings mirror
# splink_bridge.SPLINK_METHOD / curated_owners.CURATED_METHOD / llc_edges.LLC_METHOD; kept as
# literals so verify stays dependency-light — no splink/pandas import.)
MODEL_METHOD = "splink-fellegi-sunter"

Q_EDGES_PRESENT = "MATCH ()-[r:CONNECTED_BY_SPLINK]->() RETURN count(r) AS n"

# Surname = last whitespace token of the landlord name (persons are "FIRST LAST"). The hard
# gate is MODEL edges only: name-anchored blocking means a model same-owner edge must share a
# surname, so a cross-surname model edge is a real precision break. The registered-LLC edges
# link by shared owner ENTITY (same DOF LLC), which legitimately spans surnames — co-officers of
# one LLC, or a surname typo the model's blocking can't bridge (ABDO ALSAID <> ABDO ALSAIDI) —
# so those are reported as info, not failed. (Curated edges are same-surname for the seeds.)
Q_CROSS_SURNAME = """
MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b) AND coalesce(r.method, '') = $model_method
  AND toUpper(split(a.name, ' ')[-1]) <> toUpper(split(b.name, ' ')[-1])
RETURN count(*) AS n, collect(DISTINCT a.name + ' <> ' + b.name)[0..8] AS examples
"""
Q_CROSS_SURNAME_ENTITY = """
MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b) AND coalesce(r.method, '') <> $model_method
  AND toUpper(split(a.name, ' ')[-1]) <> toUpper(split(b.name, ' ')[-1])
RETURN count(*) AS n, collect(DISTINCT a.name + ' <> ' + b.name)[0..6] AS examples
"""

# Model-edge scatter is the hard gate (only Fellegi-Sunter edges — see MODEL_METHOD), and only for
# owners at/under MAX_SIZE (a bigger owner group is size-forced to split — reported separately).
Q_LOUVAIN_SCATTER = """
MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b) AND coalesce(r.method, '') = $model_method
MATCH (a)-[:MEMBER_OF]->(pa:Portfolio), (b)-[:MEMBER_OF]->(pb:Portfolio)
WHERE pa <> pb
OPTIONAL MATCH (a)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH a, b, coalesce(og.building_count, 0) AS owner_bldgs
WHERE owner_bldgs <= $max_size
RETURN count(*) AS n, collect(DISTINCT a.name)[0..8] AS examples
"""

# Size-forced model scatter: the owner group exceeds MAX_SIZE, so Louvain must split it. Info only.
Q_SIZEFORCED_SCATTER = """
MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b) AND coalesce(r.method, '') = $model_method
MATCH (a)-[:MEMBER_OF]->(pa:Portfolio), (b)-[:MEMBER_OF]->(pb:Portfolio)
WHERE pa <> pb
MATCH (a)-[:IN_OWNER_GROUP]->(og:OwnerGroup) WHERE og.building_count > $max_size
RETURN count(*) AS n, collect(DISTINCT a.name)[0..8] AS examples
"""

# Asserted/deterministic (curated + registered-LLC) pairs split across portfolios — expected
# when such a group exceeds MAX_SIZE and Louvain must cut it; reported for visibility, never
# a failure.
Q_ASSERTED_SCATTER = """
MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord)
WHERE elementId(a) < elementId(b) AND coalesce(r.method, '') <> $model_method
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

# OwnerGroup canary (ownership layer). Is it materialized, and does each marquee operator
# resolve to a single :OwnerGroup?
Q_OWNER_LAYER = "MATCH (og:OwnerGroup) RETURN count(og) AS n"
Q_OWNER_TARGET = """
MATCH (l:Landlord) WHERE l.name CONTAINS $name
OPTIONAL MATCH (l)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
RETURN count(DISTINCT l) AS nodes, count(DISTINCT og) AS groups,
       collect(DISTINCT og.building_count) AS bcounts,
       collect(DISTINCT og.name)[0..3] AS anchors
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

# LAYER DIVERGENCE (three-axis non-alignment). The Portfolio / Manager / OwnerGroup layers earn
# their place ONLY where they DISAGREE — each of these counts is the number of cases one layer
# resolves that Portfolio alone cannot. They are expected to be well above zero (measured 2026-09,
# co-op/condo-excluded OwnerGroups + linked-successor deed: 479 / 157 / 1,461 — the 157 cross-nexus
# owners rose from 86 as the deed guard's restructuring recoveries link owners across nexuses). A
# count collapsing to zero while its layer is
# materialized means the layer has aligned with Portfolio and stopped adding information — the
# "regression toward blur" WARN.
Q_COOP_CONDO = "MATCH (b:Building) WHERE b.coop_condo RETURN count(b) AS n"
Q_PF_MULTI_OWNER = """
MATCH (l:Landlord)-[:MEMBER_OF]->(p:Portfolio)
MATCH (l)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH p, count(DISTINCT og) AS ogs
RETURN sum(CASE WHEN ogs > 1 THEN 1 ELSE 0 END) AS diverge, count(p) AS total, max(ogs) AS max_v
"""
Q_OWNER_MULTI_PF = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
MATCH (l)-[:MEMBER_OF]->(p:Portfolio)
WITH og, count(DISTINCT p) AS ps
RETURN sum(CASE WHEN ps > 1 THEN 1 ELSE 0 END) AS diverge, count(og) AS total, max(ps) AS max_v
"""
Q_MANAGER_MULTI_PF = """
MATCH (b:Building)-[:MANAGED_BY]->(m:Manager)
MATCH (b)-[:IN_PORTFOLIO]->(p:Portfolio)
WITH m, count(DISTINCT p) AS ps
RETURN sum(CASE WHEN ps > 1 THEN 1 ELSE 0 END) AS diverge, count(m) AS total, max(ps) AS max_v
"""


def main() -> int:
    driver = neo4j_driver()
    failures: list[str] = []
    warnings_: list[str] = []
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        one = lambda q, **p: s.run(q, **p).single()
        rows = lambda q, **p: [r.data() for r in s.run(q, **p)]

        print("=== HARD invariants ===")

        n_edges = one(Q_EDGES_PRESENT)["n"]
        ok = n_edges > 0
        failures += [] if ok else ["no CONNECTED_BY_SPLINK edges — did --step splink run before reconcile?"]
        print(f"[{'PASS' if ok else 'FAIL'}] CONNECTED_BY_SPLINK edges present: {n_edges:,}")

        r = one(Q_CROSS_SURNAME, model_method=MODEL_METHOD)
        ok = r["n"] == 0
        failures += [] if ok else [f"{r['n']} MODEL CONNECTED_BY_SPLINK edges link different surnames"]
        print(f"[{'PASS' if ok else 'FAIL'}] model cross-surname edges: {r['n']}  (want 0)")
        if not ok:
            for ex in r["examples"]:
                print(f"         {ex}")

        es = one(Q_CROSS_SURNAME_ENTITY, model_method=MODEL_METHOD)
        print(f"[info] entity (LLC/deed/curated) cross-surname edges: {es['n']}  "
              f"(registered-LLC / ACRIS-deed link by shared owner entity/transaction, not name)")
        if es["n"]:
            print(f"         e.g. {es['examples']}")

        r = one(Q_LOUVAIN_SCATTER, model_method=MODEL_METHOD, max_size=MAX_SIZE)
        n = r["n"]
        status = "PASS" if n == 0 else ("WARN" if n <= SCATTER_WARN_MAX else "FAIL")
        if status == "FAIL":
            failures.append(f"{n} splink-linked pairs landed in different portfolios (Louvain scatter, owner <= MAX_SIZE)")
        elif status == "WARN":
            warnings_.append(f"{n} splink-linked pair(s) split across portfolios (Louvain scatter; recall-only, tolerated)")
        print(f"[{status}] model splink pairs split across portfolios (owner <= {MAX_SIZE}): {n}  "
              f"(want 0; recall-only, WARN if <= {SCATTER_WARN_MAX})")
        if n:
            print(f"         e.g. {r['examples']}")

        sf = one(Q_SIZEFORCED_SCATTER, model_method=MODEL_METHOD, max_size=MAX_SIZE)
        print(f"[info] size-forced model scatter (owner group > {MAX_SIZE}, Louvain must split): {sf['n']}  "
              f"(recall-only, not a failure)")
        if sf["n"]:
            print(f"         e.g. {sf['examples']}")

        cs = one(Q_ASSERTED_SCATTER, model_method=MODEL_METHOD)
        print(f"[info] curated/LLC/deed pairs split across portfolios: {cs['n']}  "
              f"(expected when an asserted group > MAX_SIZE; not a failure)")
        if cs["n"]:
            print(f"         e.g. {cs['examples']}")

        print("\n=== REVIEW (judgement — recall-biased design) ===")

        for name in TARGETS:
            t = one(Q_TARGET, name=name)
            counts = sorted((t["building_counts"] or []), reverse=True)
            flag = "" if t["portfolios"] == 1 else "  <- spans >1 portfolio; check the split is a stray, not a break"
            print(f"{name}: {t['nodes']} nodes -> {t['portfolios']} portfolio(s), buildings {counts}{flag}")
            for a in rows(Q_TARGET_ANCHOR, name=name):
                hit = "OK" if name in (a["anchor"] or "").upper() else "!! anchor is NOT the operator"
                print(f"     APPARENT_CONTROL anchor: {a['anchor']} ({a['buildings']} buildings)  [{hit}]")

        # OwnerGroup canary — the curated marquee operators must each be one :OwnerGroup.
        n_owner = one(Q_OWNER_LAYER)["n"]
        if n_owner == 0:
            print("\nOwnerGroup layer not materialized (run --step ownergroup); canary skipped.")
        else:
            print(f"\nOwnerGroup canary ({n_owner:,} owner groups):")
            for name in OWNER_TARGETS:
                t = one(Q_OWNER_TARGET, name=name)
                g, anchors = t["groups"], [a for a in (t["anchors"] or []) if a]
                anchor_ok = any(name in (a or "").upper() for a in anchors)
                if g == 1 and anchor_ok:
                    tag = "OK"
                elif g == 1:
                    tag = "!! single group but anchor is not the operator"
                else:
                    tag = "<- expected 1 owner group (curated); ownership-layer regression"
                    warnings_.append(f"{name} resolves to {g} OwnerGroups (curated target expects 1)")
                print(f"  {name}: {t['nodes']} nodes -> {g} owner group(s), buildings "
                      f"{sorted(t['bcounts'] or [], reverse=True)}, anchor {anchors}  [{tag}]")

        d = one(Q_SIZE_DIST, ceiling=BLOWUP_REVIEW_CEILING)
        print(f"\nportfolios {d['portfolios']:,}   max {d['max_bldgs']} bbls   "
              f"p99 {round(d['p99'] or 0)}   >300: {d['over_300']:,}   "
              f">{BLOWUP_REVIEW_CEILING}: {d['over_ceiling']:,} (review these)")
        print("largest portfolios (many distinct surnames + huge = possible over-merge blob):")
        print(f"  {'portfolio_id':<28}{'bldgs':>7}{'members':>9}{'surnames':>10}")
        for r in rows(Q_TOP_PORTFOLIOS):
            print(f"  {str(r['pid']):<28}{r['bldgs']:>7}{r['members']:>9}{r['surnames']:>10}")

        # Three-axis non-alignment: what each layer resolves that Portfolio alone cannot. Expected
        # well above zero; a collapse to zero (layer materialized) = it aligned with Portfolio (blur).
        print("\n=== LAYER DIVERGENCE (three-axis non-alignment; the layers earn their place where they disagree) ===")
        cc = one(Q_COOP_CONDO)["n"]
        print(f"[info] co-op/condo buildings flagged (excluded from OwnerGroup ownership): {cc:,}"
              + ("" if cc else "  <- 0: run --step ownergroup (tags Building.coop_condo) so counts are rental-only"))
        checks = [
            ("Portfolios holding >1 OwnerGroup   (one nexus, many owners -> OwnerGroup splits it)",
             Q_PF_MULTI_OWNER, "OwnerGroup", "ownergroup"),
            ("OwnerGroups spanning >1 Portfolio  (one owner across nexuses -> deed/splink cross-link)",
             Q_OWNER_MULTI_PF, "OwnerGroup", "ownergroup"),
            ("Managers spanning >1 Portfolio     (management is an orthogonal axis)",
             Q_MANAGER_MULTI_PF, "Manager", "managed"),
        ]
        for label, q, layer, step in checks:
            d = one(q)
            total, diverge, mx = d["total"] or 0, d["diverge"] or 0, d["max_v"] or 0
            if total == 0:
                print(f"[info] {label}\n         {layer} layer not materialized (run --step {step}); skipped.")
                continue
            print(f"[info] {label}\n         {diverge:,} of {total:,}  (max {mx})")
            if diverge == 0:
                warnings_.append(f"{layer} layer no longer diverges from Portfolio ({label.split('(')[0].strip()}) "
                                 f"— it has collapsed into the nexus and stopped adding information")

    driver.close()

    print("\n=== VERDICT ===")
    if failures:
        print("FAIL — hard invariants broken:")
        for f in failures:
            print(f"  - {f}")
        return 1
    if warnings_:
        print("PASS (with warnings) — hard invariants hold; tolerated:")
        for w in warnings_:
            print(f"  - {w}")
        print("Review the numbers above for blow-up / connectors.")
        return 0
    print("PASS — all hard invariants hold. Review the numbers above for blow-up / connectors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
