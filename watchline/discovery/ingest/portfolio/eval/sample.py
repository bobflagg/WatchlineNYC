"""eval/sample.py — draw the FROZEN stratified pair sample for the ground-truth eval.

Read-only. Emits, into an output dir:
  * review_queue.jsonl   -> the reviewer-assist tool (BLINDED: pair_id + entity name/bbls only)
  * blinding_key.jsonl   -> PRIVATE (stratum, signal, watchline decision; wow filled later by score.py)
  * frame_manifest.json  -> preregistration (as-of date, git sha, seed, per-stratum frame/n)

Strata are frozen in specs/review-tool-contract.md. Deterministic given SEED.
See specs/eval-protocol.md for the methodology this feeds.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE, pg_conn
from watchline.discovery.ingest.portfolio import deed_edges

SEED = 42
AGG_DEGREE = 25                  # a business address shared by more landlords than this = aggregator-ish
STRATA_N = {"S1a_deed_held": 70, "S1b_deed_linked_successor": 70, "S2_model": 150,
            "S3_aggregator": 120, "S4_hard_neg": 120}
SIGNAL = {"S1a_deed_held": "acris-deed", "S1b_deed_linked_successor": "acris-deed-linked-successor",
          "S2_model": "splink-fellegi-sunter", "S3_aggregator": "aggregator-mask", "S4_hard_neg": "none"}
WATCHLINE = {"S1a_deed_held": "SAME", "S1b_deed_linked_successor": "SAME", "S2_model": "SAME",
             "S3_aggregator": "DIFFERENT", "S4_hard_neg": "DIFFERENT"}

# ---- graph queries -----------------------------------------------------------------------------
Q_DEED = ("MATCH (a:Landlord)-[:CONNECTED_BY_DEED]-(b:Landlord) WHERE a.nodeid < b.nodeid "
          "RETURN a.nodeid AS an, a.name AS anm, a.bbls AS ab, b.nodeid AS bn, b.name AS bnm, b.bbls AS bb")
Q_MODEL = ("MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord) "
           "WHERE a.nodeid < b.nodeid AND coalesce(r.method,'') = 'splink-fellegi-sunter' "
           "RETURN a.nodeid AS an, a.name AS anm, a.bbls AS ab, b.nodeid AS bn, b.name AS bnm, b.bbls AS bb")
Q_CONNECTED = ("MATCH (a:Landlord)-[:CONNECTED_BY_SPLINK|CONNECTED_BY_DEED]-(b:Landlord) "
               "WHERE a.nodeid < b.nodeid RETURN a.nodeid AS a, b.nodeid AS b")
Q_OWNERGRP = ("MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup) "
              "RETURN l.nodeid AS nodeid, og.owner_group_id AS og")
Q_AGG_ADDR = (
    "MATCH (l:Landlord) WHERE l.bizaddr IS NOT NULL AND trim(l.bizaddr) <> '' "
    "WITH toUpper(trim(l.bizaddr)) AS addr, collect({nodeid:l.nodeid, name:l.name, bbls:l.bbls}) AS ls "
    "WHERE size(ls) > $deg RETURN addr, ls[0..40] AS ls")
Q_SURNAME = (
    "MATCH (l:Landlord) WHERE l.name CONTAINS ' ' "
    "WITH toUpper(split(l.name,' ')[-1]) AS surname, collect({nodeid:l.nodeid, name:l.name, bbls:l.bbls}) AS ls "
    "WHERE size(ls) >= 2 AND size(ls) <= 20 RETURN surname, ls[0..8] AS ls LIMIT 3000")


def _pk(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _held_membership(pgc) -> dict[int, set[int]]:
    """nodeid -> set of held-group indices, from held-latest multi-parcel deeds only (branch A).
    A deed pair is 'held' iff its two nodes share a held group; else it is linked-successor."""
    held = pd.read_sql(deed_edges._deed_sql(deed_edges.MAX_PARCELS), pgc)
    lwc = pd.read_sql("SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", pgc)
    groups = deed_edges._groups_from(held, lwc)
    node2g: dict[int, set[int]] = defaultdict(set)
    for gi, ids in enumerate(groups.values()):
        for n in ids:
            node2g[n].add(gi)
    return node2g


def _rows_to_pairs(rows) -> list[dict]:
    return [{"a": {"nodeid": r["an"], "name": r["anm"], "bbls": r["ab"] or []},
             "b": {"nodeid": r["bn"], "name": r["bnm"], "bbls": r["bb"] or []}} for r in rows]


def _group_pairs(groups, connected: set, owner_of: dict, *, require_diff_owner: bool,
                 per_group_cap: int, rng: random.Random) -> list[dict]:
    """Form unconnected candidate pairs within attribute groups (shared address / surname)."""
    pool: list[dict] = []
    for members in groups:
        ms = list(members)
        rng.shuffle(ms)
        made = 0
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                a, b = ms[i], ms[j]
                if _pk(a["nodeid"], b["nodeid"]) in connected:
                    continue
                if require_diff_owner:
                    oa, ob = owner_of.get(a["nodeid"]), owner_of.get(b["nodeid"])
                    if oa is not None and oa == ob:
                        continue
                pool.append({"a": a, "b": b})
                made += 1
                if made >= per_group_cap:
                    break
            if made >= per_group_cap:
                break
    return pool


def build(out_dir: Path) -> dict:
    rng = random.Random(SEED)
    drv = neo4j_driver()
    with drv.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        deed = _rows_to_pairs([r.data() for r in s.run(Q_DEED)])
        model = _rows_to_pairs([r.data() for r in s.run(Q_MODEL)])
        connected = {_pk(r["a"], r["b"]) for r in s.run(Q_CONNECTED)}
        owner_of = {r["nodeid"]: r["og"] for r in s.run(Q_OWNERGRP)}
        agg_groups = [r["ls"] for r in s.run(Q_AGG_ADDR, deg=AGG_DEGREE)]
        surname_groups = [r["ls"] for r in s.run(Q_SURNAME)]
    drv.close()

    pgc = pg_conn()
    try:
        node2held = _held_membership(pgc)
    finally:
        pgc.close()

    def held(pair) -> bool:
        return bool(node2held.get(pair["a"]["nodeid"], set()) & node2held.get(pair["b"]["nodeid"], set()))

    frames = {
        "S1a_deed_held": [p for p in deed if held(p)],
        "S1b_deed_linked_successor": [p for p in deed if not held(p)],
        "S2_model": model,
        "S3_aggregator": _group_pairs(agg_groups, connected, owner_of,
                                      require_diff_owner=True, per_group_cap=6, rng=rng),
        "S4_hard_neg": _group_pairs(surname_groups, connected, owner_of,
                                    require_diff_owner=True, per_group_cap=3, rng=rng),
    }

    queue, key, manifest = [], [], {}
    seq = 0
    for stratum, n in STRATA_N.items():
        frame = frames[stratum]
        take = rng.sample(frame, min(n, len(frame)))
        manifest[stratum] = {"frame": len(frame), "n": len(take)}
        for pair in take:
            seq += 1
            pid = f"P{seq:04d}"
            a, b = pair["a"], pair["b"]
            if rng.random() < 0.5:          # randomize A/B so order encodes nothing
                a, b = b, a
            queue.append({"pair_id": pid,
                          "a": {"ref": "A", "name": a["name"], "bbls": [str(x) for x in a["bbls"]]},
                          "b": {"ref": "B", "name": b["name"], "bbls": [str(x) for x in b["bbls"]]}})
            key.append({"pair_id": pid, "stratum": stratum, "signal": SIGNAL[stratum],
                        "watchline": WATCHLINE[stratum], "wow": None, "anchor": None,
                        "a_nodeid": a["nodeid"], "b_nodeid": b["nodeid"],
                        "a_bbls": [str(x) for x in a["bbls"]], "b_bbls": [str(x) for x in b["bbls"]]})

    rng.shuffle(queue)                       # present strata interleaved, not blocked
    qorder = {p["pair_id"]: i for i, p in enumerate(queue)}
    key.sort(key=lambda k: qorder[k["pair_id"]])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review_queue.jsonl").write_text("\n".join(json.dumps(p) for p in queue) + "\n")
    (out_dir / "blinding_key.jsonl").write_text("\n".join(json.dumps(k) for k in key) + "\n")
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        sha = "unknown"
    fm = {"as_of_date": date.today().isoformat(), "pipeline_git_sha": sha, "seed": SEED,
          "aggregator_degree": AGG_DEGREE, "strata": manifest}
    (out_dir / "frame_manifest.json").write_text(json.dumps(fm, indent=2) + "\n")
    return fm


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval_out", help="output directory")
    args = ap.parse_args()
    fm = build(Path(args.out))
    print(f"wrote review_queue.jsonl + blinding_key.jsonl + frame_manifest.json to {args.out}/")
    for st, m in fm["strata"].items():
        print(f"  {st:<28} frame {m['frame']:>6}  sampled {m['n']}")
