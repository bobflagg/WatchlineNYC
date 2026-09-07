"""eval/cutover_frame.py — the two-strata adjudication frame for the Track-A cutover gate (Option B).

Emits the blinded review queue (+ private key) the owner-review tool consumes, for the §8.1 Track-A gate:

  * S1 CHANGED DECISIONS (census): every legacy `OwnerGroup` that v2 splits into >=2 `ResolvedEntityV2`
    entities -> pair(s) BETWEEN those sub-entities. Adjudicating SAME = v2 wrongly split (a false split);
    DIFFERENT = v2 correctly split (confirms R3). Tests the split/recall side. Census (79 groups is small).
  * S2 RETAINED MERGES (sample): v2 multi-member entities, over-weighting curated / large / common-name
    -> a within-entity member pair. Adjudicating DIFFERENT = a false MERGE among what v2 keeps. Estimates FM.

The blinded queue carries only names + bbls (never stratum / v2 decision); the private key records stratum,
decision_type (split|merge), and v2's implied decision, so `score.py` can compute the paired,
deployment-weighted noninferiority L = 5*FM + FS. C0 collisions are a SEPARATE inherited-risk stratum
(shared by both models) — not drawn here. Read-only (writes JSONL only).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE

SEED = 42
LARGE_MIN = 8            # v2 entities with >= this many members are over-weighted (census-included) in S2
COMMON_SURNAME_MIN = 15  # a surname borne by >= this many entities is "common" -> over-weighted in S2
N_RANDOM_RETAINED = 120  # random retained-merge entities beyond the forced (curated/large/common) ones
MAX_SPLIT_PAIRS = 3      # cap pairs per split group (most split into 2 -> 1 pair)


# --- pure stratum builders --------------------------------------------------------------------

def split_stratum(legacy: dict, v2: dict) -> list[tuple]:
    """Legacy groups split by v2. Returns ``[(owner_group_id, {resolution_id: [nodeid]}), …]`` for groups
    whose shared members fall into >=2 v2 entities."""
    leg: dict = defaultdict(lambda: defaultdict(list))
    for n in set(legacy) & set(v2):
        leg[legacy[n]][v2[n]].append(n)
    return [(og, {r: ns for r, ns in ents.items()}) for og, ents in leg.items() if len(ents) >= 2]


def split_pairs(groups: list[tuple], max_pairs: int = MAX_SPLIT_PAIRS) -> list[dict]:
    """Pairs BETWEEN v2 sub-entities within each split group (largest sub-entities first, capped)."""
    out = []
    for og, ents in groups:
        rids = sorted(ents, key=lambda r: (-len(ents[r]), r))
        cnt = 0
        for i in range(len(rids)):
            for j in range(i + 1, len(rids)):
                out.append({"stratum": "S1_split", "decision_type": "split", "v2_decision": "DIFFERENT",
                            "owner_group_id": og, "a_rid": rids[i], "a_nodes": ents[rids[i]],
                            "b_rid": rids[j], "b_nodes": ents[rids[j]]})
                cnt += 1
                if cnt >= max_pairs:
                    break
            if cnt >= max_pairs:
                break
    return out


def select_retained(ent_members: dict, ent_meta: dict, ent_surname: dict, surname_freq: dict,
                    *, seed: int = SEED, n_random: int = N_RANDOM_RETAINED,
                    large_min: int = LARGE_MIN, common_min: int = COMMON_SURNAME_MIN) -> list[str]:
    """Choose v2 entities for the retained-merge stratum: force-include curated (deterministic_core),
    large (>= large_min members), and common-surname entities; add a seeded random sample of the rest."""
    forced = {r for r in ent_members
              if ent_meta.get(r, {}).get("deterministic_core")
              or ent_meta.get(r, {}).get("member_count", 0) >= large_min
              or surname_freq.get(ent_surname.get(r), 0) >= common_min}
    rest = [r for r in ent_members if r not in forced and len(ent_members[r]) >= 2]
    random.Random(seed).shuffle(rest)
    return sorted(forced) + rest[:n_random]


def retained_pairs(selected: list[str], ent_members: dict) -> list[dict]:
    """One within-entity member pair per selected entity (the two lowest nodeids, deterministic)."""
    out = []
    for rid in selected:
        m = sorted(ent_members[rid])
        if len(m) >= 2:
            out.append({"stratum": "S2_retained_merge", "decision_type": "merge", "v2_decision": "SAME",
                        "resolution_id": rid, "a_nodes": [m[0]], "b_nodes": [m[1]]})
    return out


# --- graph read + emit ------------------------------------------------------------------------

def _read(driver, database, run_id):
    q_leg = "MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(o:OwnerGroup) RETURN l.nodeid AS n, o.owner_group_id AS g"
    q_v2 = ("MATCH (l:Landlord)-[:IN_RESOLVED_ENTITY_V2 {run_id:$run_id}]->(e:ResolvedEntityV2) "
            "RETURN l.nodeid AS n, e.resolution_id AS g, e.member_count AS mc, e.deterministic_core AS dc")
    q_node = "MATCH (l:Landlord) RETURN l.nodeid AS n, l.name AS name, l.bbls AS bbls"
    with driver.session(database=database) as s:
        legacy = {r["n"]: r["g"] for r in s.run(q_leg)}
        v2, ent_meta = {}, {}
        for r in s.run(q_v2, run_id=run_id):
            v2[r["n"]] = r["g"]
            ent_meta[r["g"]] = {"member_count": r["mc"], "deterministic_core": bool(r["dc"])}
        node = {r["n"]: {"name": r["name"], "bbls": r["bbls"] or []} for r in s.run(q_node)}
    return legacy, v2, ent_meta, node


def _anchor(nodes, node):
    """Representative name for a set of member nodeids = the member with the most bbls."""
    best = max(nodes, key=lambda n: len(node.get(n, {}).get("bbls", [])), default=None)
    return node.get(best, {}).get("name") or "(unknown)"


def _bbls(nodes, node):
    out = []
    for n in nodes:
        out += node.get(n, {}).get("bbls", [])
    return sorted(set(out))


def build(driver, *, database: str, run_id: str, out_dir: Path) -> dict:
    legacy, v2, ent_meta, node = _read(driver, database, run_id)
    ent_members: dict = defaultdict(list)
    for n, rid in v2.items():
        ent_members[rid].append(n)
    ent_surname = {rid: (_anchor(ns, node).split()[-1] if _anchor(ns, node) else "")
                   for rid, ns in ent_members.items()}
    surname_freq = Counter(ent_surname.values())

    s1 = split_pairs(split_stratum(legacy, v2))
    sel = select_retained(dict(ent_members), ent_meta, ent_surname, surname_freq)
    s2 = retained_pairs(sel, dict(ent_members))

    out_dir.mkdir(parents=True, exist_ok=True)
    queue, key = [], []
    for i, p in enumerate(s1 + s2, 1):
        pid = f"CUT-{i:04d}"
        a_nodes, b_nodes = p["a_nodes"], p["b_nodes"]
        queue.append({"pair_id": pid,
                      "a": {"ref": "A", "name": _anchor(a_nodes, node), "bbls": _bbls(a_nodes, node)},
                      "b": {"ref": "B", "name": _anchor(b_nodes, node), "bbls": _bbls(b_nodes, node)}})
        key.append({"pair_id": pid, **{k: v for k, v in p.items() if k not in ("a_nodes", "b_nodes")},
                    "run_id": run_id})
    (out_dir / "review_queue.jsonl").write_text("\n".join(json.dumps(r) for r in queue) + "\n")
    (out_dir / "cutover_key.jsonl").write_text("\n".join(json.dumps(r) for r in key) + "\n")
    return {"s1_split_pairs": len(s1), "s2_retained_pairs": len(s2), "total": len(queue),
            "out": str(out_dir)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Track-A cutover adjudication frame (S1 splits census + S2 retained merges).")
    ap.add_argument("--run-id", required=True, help="the materialized ResolvedEntityV2 run_id")
    ap.add_argument("--out", type=Path, default=Path("eval_out/cutover"))
    args = ap.parse_args()
    driver = neo4j_driver()
    try:
        info = build(driver, database=NEO4J_DISCOVERY_DATABASE, run_id=args.run_id, out_dir=args.out)
    finally:
        driver.close()
    print(f"S1 split pairs (census): {info['s1_split_pairs']}  S2 retained-merge pairs: "
          f"{info['s2_retained_pairs']}  total {info['total']} -> {info['out']}")


if __name__ == "__main__":
    main()
