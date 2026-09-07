"""shadow_compare.py — shadow comparison of ResolvedEntityV2 vs the legacy OwnerGroup layer.

Read-only (Option B, Phase 4). Compares the v2 identity partition against the legacy `OwnerGroup`
partition at the landlord-node level. The **expected** relationship (F1/R3): v2 uses a strict *subset* of
legacy's edges (identity = fellegi + audited curated; legacy also fused registered-llc + deed), so v2 must
be a **refinement** of legacy — legacy groups *split* into ≥1 v2 entity, and **no** v2 entity spans ≥2
legacy groups (that would be a v2 merge legacy didn't make → investigate). Nodes legacy grouped but v2
drops are the owner-association-only members (registered-llc/deed) correctly excluded from identity.

The v2 side reads a materialized `:ResolvedEntityV2` run when given `run_id`, else computes it on-the-fly
from the resolver — so this harness works before the parallel materialization is written.
"""
from __future__ import annotations

from collections import defaultdict

from . import resolved_entity as R


def compare_partitions(v2: dict, legacy: dict) -> dict:
    """Pure: compare two ``{nodeid: group_id}`` partitions. Reports coverage, the refinement counts, and
    the containment invariant (v2 must not merge across legacy groups)."""
    v2n, legn = set(v2), set(legacy)
    both = v2n & legn
    leg_to_v2: dict = defaultdict(set)
    v2_to_leg: dict = defaultdict(set)
    for n in both:
        leg_to_v2[legacy[n]].add(v2[n])
        v2_to_leg[v2[n]].add(legacy[n])
    legacy_split = sum(1 for gs in leg_to_v2.values() if len(gs) >= 2)
    v2_cross = sum(1 for gs in v2_to_leg.values() if len(gs) >= 2)
    # examples of the anomaly (v2 merging across legacy groups) — should be empty
    cross_examples = [rid for rid, gs in v2_to_leg.items() if len(gs) >= 2][:8]
    return {
        "v2_nodes": len(v2n), "legacy_nodes": len(legn), "shared_nodes": len(both),
        "v2_only_nodes": len(v2n - legn), "legacy_only_nodes": len(legn - v2n),
        "legacy_groups_over_shared": len(leg_to_v2),
        "legacy_groups_split_in_v2": legacy_split,
        "v2_entities_spanning_legacy_groups": v2_cross,   # invariant: expect 0
        "v2_cross_examples": cross_examples,
        "left_identity_nodes": len(legn - v2n),           # legacy-grouped, not in v2 = association-only
    }


_Q_LEGACY = ("MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup) "
             "RETURN l.nodeid AS nodeid, og.owner_group_id AS gid")
_Q_V2 = ("MATCH (l:Landlord)-[:IN_RESOLVED_ENTITY_V2 {run_id:$run_id}]->(e:ResolvedEntityV2) "
         "RETURN l.nodeid AS nodeid, e.resolution_id AS gid")


def read_legacy(driver, *, database: str) -> dict:
    with driver.session(database=database) as s:
        return {r["nodeid"]: r["gid"] for r in s.run(_Q_LEGACY)}


def read_v2(driver, *, database: str, run_id: str | None = None) -> dict:
    """Materialized run (`run_id`) if given, else compute the v2 partition on-the-fly (read-only)."""
    if run_id:
        with driver.session(database=database) as s:
            return {r["nodeid"]: r["gid"] for r in s.run(_Q_V2, run_id=run_id)}
    part = R.resolve_graph(driver, database=database)["partition"]
    # keep only multi-member entities, to match the legacy layer (singletons implied)
    counts: dict = defaultdict(int)
    for rid in part.values():
        counts[rid] += 1
    return {n: rid for n, rid in part.items() if counts[rid] >= 2}


def shadow_report(driver, *, database: str, run_id: str | None = None) -> dict:
    """Full read-only shadow comparison; `run_id=None` computes v2 on-the-fly."""
    return compare_partitions(read_v2(driver, database=database, run_id=run_id),
                              read_legacy(driver, database=database))
