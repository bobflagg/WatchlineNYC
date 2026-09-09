"""eval/frame_qa.py — LEAD-FACING triage over the cutover frame (NOT for the blinded reviewer).

Reads `cutover_key.jsonl` (which carries v2's decision + the legacy owner_group / v2 resolution_id) plus
`review_queue.jsonl` (the A/B anchor names), joins them, consults the graph for the connecting mechanism and
blob shape, and classifies every pair so the project lead knows **where to spend judgment** and **what to
personally trace** before the frame is scored.

**Blinding boundary — do NOT feed this into owner-review.** Its output is derived from v2's own decision
(`v2_decision`, the split/merge structure), so consulting it while adjudicating would make the gate circular
(validating v2 against v2). It lives on the WatchlineNYC side, reads the private key, and emits to
`eval_out/cutover/frame_qa.jsonl` — a QA artifact, never imported into the blinded tool.

Buckets, by descending priority:
  * **RED_FLAG_MERGE / RED_FLAG_SPLIT** — v2 did something the invariant says it shouldn't: merged
    dissimilar-surname nodes, held a merged entity together with a *non-identity* edge, or split two nodes
    that a *direct identity* edge connects. Trace these by hand.
  * **name_similar_split** — S1 split of same/typo-surname nodes: a possible real same-owner v2 wrongly split
    (the F4 `registered-llc-id` recall misses, or a typo/HDFC that should be SAME). Needs careful review.
  * **routine_blob_split** — S1 split of dissimilar-surname nodes connected only via relationship edges
    (registered-llc/deed), often transitive through a bridge: the OG-110/OG-1073 pattern, expected DIFFERENT.
  * **routine_merge** — S2 retained merge, surname-consistent, held by an identity method: expected SAME.
"""
from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher

_IDENTITY_METHODS = frozenset({"splink-fellegi-sunter", "curated-same-owner"})
_TYPO_RATIO = 0.85     # normalized-surname similarity at/above this (but not equal) reads as a typo variant


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _surname(name: str) -> str:
    toks = (name or "").strip().split()
    return _norm(toks[-1]) if toks else ""


def surname_relation(a_name: str, b_name: str) -> str:
    """'same' | 'typo' | 'different' — the identity-relevant relation between two anchor names' surnames."""
    sa, sb = _surname(a_name), _surname(b_name)
    if not sa or not sb:
        return "different"
    if sa == sb:
        return "same"
    return "typo" if SequenceMatcher(None, sa, sb).ratio() >= _TYPO_RATIO else "different"


def name_ratio(a_name: str, b_name: str) -> float:
    return round(SequenceMatcher(None, _norm(a_name), _norm(b_name)).ratio(), 3)


def classify(f: dict) -> dict:
    """Pure: bucket + priority (3=highest) + flags from a pair's assembled facts. `f` keys:
    stratum, surname_relation; S1: path_methods (list), path_hops (int); S2: entity_surname_count,
    entity_methods (list)."""
    flags: list[str] = []
    rel = f.get("surname_relation", "different")

    if f["stratum"] == "S2_retained_merge":
        methods = set(f.get("entity_methods") or [])
        # v2 entities are identity-only components by construction, and the pipeline also writes redundant
        # registered-llc CONNECTED_BY_SPLINK edges that merely CO-EXIST among members — so the presence of a
        # non-identity edge is NOT a breach. The real canary is an entity with NO identity edge at all.
        identity_present = bool(methods & _IDENTITY_METHODS)
        if (f.get("entity_member_count") or 1) > 1 and not identity_present:
            return {"bucket": "RED_FLAG_MERGE", "priority": 3,
                    "flags": ["merge-not-identity-connected:" + (",".join(sorted(methods)) or "none")]}
        # Suspicious-but-not-a-breach: an uncurated entity spanning surnames, or dissimilar anchor names.
        if (f.get("entity_surname_count") or 1) > 1 and "curated-same-owner" not in methods:
            flags.append("merge-spans-surnames")
        if rel == "different":
            flags.append("merge-dissimilar-anchor-names")
        if flags:
            return {"bucket": "review_merge", "priority": 2, "flags": flags}
        return {"bucket": "routine_merge", "priority": 1, "flags": []}

    # S1_split — endpoints are two *different* v2 entities; the path lives in the legacy edge set.
    methods = set(f.get("path_methods") or [])
    has_relationship = bool(methods - _IDENTITY_METHODS)       # registered-llc / deed on the path
    if rel in ("same", "typo"):
        return {"bucket": "name_similar_split", "priority": 2, "flags": [f"split-of-{rel}-surname"]}
    if methods and not has_relationship:
        # an all-identity path between two nodes v2 put in *different* entities — shouldn't happen cleanly.
        return {"bucket": "RED_FLAG_SPLIT", "priority": 3, "flags": ["direct-identity-path-but-split"]}
    return {"bucket": "routine_blob_split", "priority": 0,
            "flags": ["transitive-bridge"] if (f.get("path_hops") or 0) >= 2 else []}


# ---- graph reads (read-only) ------------------------------------------------------------------------

_OG_STATS = """
UNWIND $gids AS gid
MATCH (og:OwnerGroup {owner_group_id: gid})<-[:IN_OWNER_GROUP]-(l:Landlord)
RETURN gid AS gid, count(l) AS size,
       count(DISTINCT toUpper(split(l.name,' ')[-1])) AS surnames
"""

_S1_PATHS = """
UNWIND $pairs AS pr
MATCH (:ResolvedEntityV2 {resolution_id: pr.a})<-[:IN_RESOLVED_ENTITY_V2]-(la:Landlord)
WITH pr, collect(DISTINCT la)[0] AS a
MATCH (:ResolvedEntityV2 {resolution_id: pr.b})<-[:IN_RESOLVED_ENTITY_V2]-(lb:Landlord)
WITH pr, a, collect(DISTINCT lb)[0] AS b
OPTIONAL MATCH p = shortestPath((a)-[:CONNECTED_BY_SPLINK|CONNECTED_BY_DEED*..10]-(b))
RETURN pr.pair_id AS pair_id,
       [r IN relationships(p) | coalesce(r.method, type(r))] AS methods,
       CASE WHEN p IS NULL THEN null ELSE length(p) END AS hops
"""

_S2_PROFILE = """
UNWIND $rids AS rid
MATCH (e:ResolvedEntityV2 {resolution_id: rid})<-[:IN_RESOLVED_ENTITY_V2]-(l:Landlord)
OPTIONAL MATCH (l)-[r:CONNECTED_BY_SPLINK]-(:Landlord)-[:IN_RESOLVED_ENTITY_V2]->(e)
RETURN rid AS rid, count(DISTINCT l) AS members,
       count(DISTINCT toUpper(split(l.name,' ')[-1])) AS surnames,
       collect(DISTINCT r.method) AS methods
"""


def _run(driver, database, query, **params):
    with driver.session(database=database) as s:
        return [r.data() for r in s.run(query, **params)]


def read_graph_facts(driver, *, database: str, key_rows: list[dict]) -> dict:
    """Fetch per-pair graph facts keyed by pair_id (S1 path/blob) and per-entity facts (S2)."""
    s1 = [r for r in key_rows if r["stratum"] == "S1_split"]
    s2 = [r for r in key_rows if r["stratum"] == "S2_retained_merge"]
    gids = sorted({r["owner_group_id"] for r in s1 if r.get("owner_group_id")})
    og = {r["gid"]: r for r in _run(driver, database, _OG_STATS, gids=gids)} if gids else {}
    pairs = [{"pair_id": r["pair_id"], "a": r["a_rid"], "b": r["b_rid"]} for r in s1]
    paths = {r["pair_id"]: r for r in _run(driver, database, _S1_PATHS, pairs=pairs)} if pairs else {}
    rids = sorted({r["resolution_id"] for r in s2 if r.get("resolution_id")})
    prof = {r["rid"]: r for r in _run(driver, database, _S2_PROFILE, rids=rids)} if rids else {}
    return {"og": og, "paths": paths, "prof": prof}


def assemble(key_rows: list[dict], queue_by_id: dict, graph: dict) -> list[dict]:
    """Join key + queue names + graph facts into per-pair fact dicts, then classify each."""
    out = []
    for k in key_rows:
        q = queue_by_id.get(k["pair_id"], {})
        a_name, b_name = q.get("a", {}).get("name", ""), q.get("b", {}).get("name", "")
        f = {"pair_id": k["pair_id"], "stratum": k["stratum"], "v2_decision": k.get("v2_decision"),
             "a_name": a_name, "b_name": b_name,
             "surname_relation": surname_relation(a_name, b_name), "name_ratio": name_ratio(a_name, b_name)}
        if k["stratum"] == "S1_split":
            og = graph["og"].get(k.get("owner_group_id"), {})
            path = graph["paths"].get(k["pair_id"], {})
            f.update({"owner_group_id": k.get("owner_group_id"),
                      "blob_size": og.get("size"), "blob_surnames": og.get("surnames"),
                      "path_methods": path.get("methods") or [], "path_hops": path.get("hops")})
        else:
            p = graph["prof"].get(k.get("resolution_id"), {})
            f.update({"resolution_id": k.get("resolution_id"), "entity_member_count": p.get("members"),
                      "entity_surname_count": p.get("surnames"),
                      "entity_methods": [m for m in (p.get("methods") or []) if m]})
        f.update(classify(f))
        out.append(f)
    return out


def build(driver, *, database: str, key_path: str, queue_path: str, out_path: str) -> dict:
    key_rows = [json.loads(l) for l in open(key_path) if l.strip()]
    queue_by_id = {q["pair_id"]: q for q in (json.loads(l) for l in open(queue_path) if l.strip())}
    facts = assemble(key_rows, queue_by_id, read_graph_facts(driver, database=database, key_rows=key_rows))
    facts.sort(key=lambda x: (-x["priority"], x["bucket"], x["pair_id"]))
    with open(out_path, "w") as fh:
        for f in facts:
            fh.write(json.dumps(f) + "\n")
    buckets = Counter(f["bucket"] for f in facts)
    blobs = Counter(f["owner_group_id"] for f in facts if f.get("owner_group_id"))
    return {"n_pairs": len(facts), "buckets": dict(buckets), "out_path": out_path,
            "needs_review": [f["pair_id"] for f in facts if f["priority"] >= 2],
            "multi_pair_blobs": {g: n for g, n in blobs.items() if n > 1}}


if __name__ == "__main__":
    import argparse
    from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE
    ap = argparse.ArgumentParser(description="Lead-facing cutover-frame triage (NOT for the blind reviewer).")
    ap.add_argument("--dir", default="eval_out/cutover")
    args = ap.parse_args()
    drv = neo4j_driver()
    try:
        rep = build(drv, database=NEO4J_DISCOVERY_DATABASE,
                    key_path=f"{args.dir}/cutover_key.jsonl", queue_path=f"{args.dir}/review_queue.jsonl",
                    out_path=f"{args.dir}/frame_qa.jsonl")
    finally:
        drv.close()
    print(json.dumps(rep, indent=2))
