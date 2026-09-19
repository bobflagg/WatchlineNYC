"""eval/score.py — close the seam: join the returned annotations with the private blinding key and
the dump's WoW portfolios, and produce the headline numbers.

Reads (all WatchlineNYC-side):
  * blinding_key.jsonl   — pair_id, stratum, signal, watchline decision, bbls, node ids (from sample.py)
  * annotations.jsonl    — pair_id, annotator_id, label, evidence_tiers, c2_checks (from owner-review)
Fills the WoW decision per pair from wow.wow_portfolios (two entities are WoW-SAME iff any of their
bbls share a WoW portfolio). Emits per-stratum precision (strict C1-only + inclusive C1+C2), coverage,
C2 share (Wilson CIs), Cohen's κ, and a paired McNemar vs WoW. See specs/eval-protocol.md.

Read-only on Postgres; needs no Neo4j. Also writes disagreements.jsonl and errors.jsonl for the
manual data-vintage bucketing + error-cause tagging the protocol calls for.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE

DEED_SIGNALS = {"acris-deed", "acris-deed-linked-successor"}
ADJUDICATOR = "adjudicator"          # annotator_id whose label is the gold when annotators disagree


# ---- pure stats helpers (unit-tested) ----------------------------------------------------------
def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Point estimate + 95% Wilson interval for k/n. (0,0,0) when n==0."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    z = 1.959963984540054
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ over (labelA, labelB) for items both annotators labeled. None if <2 items."""
    n = len(pairs)
    if n < 2:
        return None
    labels = sorted({x for ab in pairs for x in ab})
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == L) / n) * (sum(1 for _, b in pairs if b == L) / n)
             for L in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def mcnemar(b: int, c: int) -> float:
    """Two-sided McNemar p (chi-square with continuity correction). b,c = discordant counts."""
    if b + c == 0:
        return 1.0
    chi = (abs(b - c) - 1) ** 2 / (b + c)
    # survival of chi-square df=1 = erfc(sqrt(chi/2))
    return math.erfc(math.sqrt(chi / 2))


def gold_label(anns: list[dict]) -> tuple[str, list[str]]:
    """Resolve a pair's gold label + the evidence tiers it rests on.
    adjudicator wins; else unanimous agreement; else UNRESOLVED. Tiers: adjudicator's, else the union
    across agreeing annotators (any independent tier -> favors C1 at classification)."""
    adj = [a for a in anns if a["annotator_id"] == ADJUDICATOR]
    if adj:
        g = adj[-1]
        return g["label"], list(g.get("evidence_tiers") or [])
    prim = [a for a in anns if a["annotator_id"] != ADJUDICATOR]
    labels = {a["label"] for a in prim}
    if len(labels) == 1 and prim:
        tiers = sorted({t for a in prim for t in (a.get("evidence_tiers") or [])})
        return prim[0]["label"], tiers
    return "UNRESOLVED", []


def corroboration_class(signal: str, gold: str, tiers: list[str]) -> str | None:
    """C1 cross-source / C2 same-source-verified, for a gold SAME. None if not a SAME."""
    if gold != "SAME":
        return None
    if signal in DEED_SIGNALS and set(tiers) == {"T1"}:
        return "C2"
    return "C1"


# ---- WoW decision from the dump ----------------------------------------------------------------
def _bbl_to_wow_portfolio(conn) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT orig_id, bbls FROM wow.wow_portfolios WHERE bbls IS NOT NULL")
    out: dict[str, str] = {}
    for orig_id, bbls in cur.fetchall():
        for b in (bbls or []):
            out[str(b).strip()] = str(orig_id)
    return out


def _wow_decision(a_bbls, b_bbls, bbl2pf) -> str:
    pa = {bbl2pf[str(b).strip()] for b in a_bbls if str(b).strip() in bbl2pf}
    pb = {bbl2pf[str(b).strip()] for b in b_bbls if str(b).strip() in bbl2pf}
    return "SAME" if (pa & pb) else "DIFFERENT"


def _load_jsonl(path: str) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def score(key_path: str, ann_path: str, out_dir: Path) -> dict:
    key = {k["pair_id"]: k for k in _load_jsonl(key_path)}
    anns_by_pair: dict[str, list[dict]] = defaultdict(list)
    for a in _load_jsonl(ann_path):
        anns_by_pair[a["pair_id"]].append(a)

    conn = pg_conn()
    try:
        bbl2pf = _bbl_to_wow_portfolio(conn)
    finally:
        conn.close()

    # per-pair resolved record
    recs = []
    kappa_pairs = []
    for pid, k in key.items():
        anns = anns_by_pair.get(pid, [])
        gold, tiers = gold_label(anns)
        wow = _wow_decision(k["a_bbls"], k["b_bbls"], bbl2pf)
        recs.append({"pair_id": pid, "stratum": k["stratum"], "signal": k["signal"],
                     "watchline": k["watchline"], "wow": wow, "gold": gold,
                     "cclass": corroboration_class(k["signal"], gold, tiers)})
        prim = [a for a in anns if a["annotator_id"] != ADJUDICATOR]
        if len(prim) >= 2:
            kappa_pairs.append((prim[0]["label"], prim[1]["label"]))

    # per-stratum metrics
    strata = sorted({r["stratum"] for r in recs})
    report: dict = {"kappa": cohens_kappa(kappa_pairs), "n_pairs": len(recs), "strata": {}}
    for st in strata:
        rs = [r for r in recs if r["stratum"] == st]
        watchline = rs[0]["watchline"] if rs else "SAME"
        adjud = [r for r in rs if r["gold"] in ("SAME", "DIFFERENT")]  # exclude INDET/UNRESOLVED
        m = {"n": len(rs), "adjudicable": len(adjud),
             "coverage": round(len(adjud) / len(rs), 3) if rs else 0}
        if watchline == "SAME":
            c1 = sum(1 for r in adjud if r["cclass"] == "C1")
            c2 = sum(1 for r in adjud if r["cclass"] == "C2")
            diff = sum(1 for r in adjud if r["gold"] == "DIFFERENT")
            m["strict_precision"] = wilson(c1, c1 + diff)
            m["inclusive_precision"] = wilson(c1 + c2, c1 + c2 + diff)
            m["c2_share"] = round(c2 / (c1 + c2), 3) if (c1 + c2) else 0
        else:  # DIFFERENT stratum: correct = gold DIFFERENT
            good = sum(1 for r in adjud if r["gold"] == "DIFFERENT")
            m["split_precision"] = wilson(good, len(adjud))
        report["strata"][st] = m

    # head-to-head vs WoW on all adjudicable pairs where the two systems disagree
    disc = [r for r in recs if r["gold"] in ("SAME", "DIFFERENT") and r["watchline"] != r["wow"]]
    b = sum(1 for r in disc if r["watchline"] == r["gold"])   # watchline right, wow wrong
    c = sum(1 for r in disc if r["wow"] == r["gold"])         # wow right, watchline wrong
    report["head_to_head"] = {"discordant": len(disc), "watchline_right_wow_wrong": b,
                              "wow_right_watchline_wrong": c, "mcnemar_p": round(mcnemar(b, c), 5)}

    # artifacts for manual data-vintage bucketing + error-cause tagging
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "disagreements.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs
                  if r["gold"] in ("SAME", "DIFFERENT") and r["watchline"] != r["wow"]) + "\n")
    (out_dir / "errors.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs
                  if r["gold"] in ("SAME", "DIFFERENT") and r["gold"] != r["watchline"]) + "\n")
    (out_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def _fmt(w):  # (p, lo, hi) -> "0.91 [0.85,0.95]"
    return f"{w[0]:.2f} [{w[1]:.2f},{w[2]:.2f}]" if w else "-"


def gate_mode(og_ids: list[str] | None, out_dir: Path) -> dict:
    """Run the hardened WoW veil-pierce gate (``wow_gate.py``) over candidate ``CONNECTED_BY_DEED`` owner
    groups: which are genuine WoW false-splits the deed uniquely recovers (PASS) vs WoW over-lumps WoW
    already groups on a shared aggregator address (FAIL)? With no ``og_ids`` the population is the
    *deed-only* groups (members tied ONLY by ``CONNECTED_BY_DEED``, no ``CONNECTED_BY_SPLINK``) — the
    natural candidate set; pass owner_group_id(s) to gate specific groups (e.g. bridge candidates).

    Analysis-only: reads the live discovery graph + ``wow.wow_portfolios``, writes nothing to either.
    Writes ``<out_dir>/wow_gate.json`` and returns the summary dict."""
    from . import wow_gate

    ENUM = ("MATCH (a:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)<-[:IN_OWNER_GROUP]-(b:Landlord) "
            "WHERE id(a) < id(b) "
            "WITH og, sum(CASE WHEN EXISTS((a)-[:CONNECTED_BY_DEED]-(b)) THEN 1 ELSE 0 END) AS d, "
            "         sum(CASE WHEN EXISTS((a)-[:CONNECTED_BY_SPLINK]-(b)) THEN 1 ELSE 0 END) AS s "
            "WHERE d >= 1 AND s = 0 "
            "MATCH (m:Landlord)-[:IN_OWNER_GROUP]->(og) "
            "RETURN og.owner_group_id AS og, apoc.coll.toSet(apoc.coll.flatten(collect(m.bbls))) AS bbls")
    BY_ID = ("MATCH (m:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup) WHERE og.owner_group_id IN $ids "
             "RETURN og.owner_group_id AS og, apoc.coll.toSet(apoc.coll.flatten(collect(m.bbls))) AS bbls")

    drv = neo4j_driver()
    try:
        with drv.session(database=NEO4J_DISCOVERY_DATABASE) as s:
            rows = (s.run(BY_ID, ids=og_ids) if og_ids else s.run(ENUM)).data()
    finally:
        drv.close()

    conn = pg_conn()
    results = []
    try:
        for r in rows:
            res = wow_gate.gate_bbls(conn, r["bbls"])
            results.append({"owner_group": r["og"], "buildings": len(r["bbls"]),
                            "passed": res.passed, "reasons": res.reasons})
    finally:
        conn.close()

    results.sort(key=lambda x: (x["passed"], -x["buildings"]))   # fails first, largest first
    n_pass = sum(1 for x in results if x["passed"])
    out = {"population": "specified" if og_ids else "deed-only",
           "n_candidates": len(results), "n_pass": n_pass, "n_fail": len(results) - n_pass,
           "results": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "wow_gate.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--annotations")
    ap.add_argument("--out", default="eval_out")
    ap.add_argument("--gate", action="store_true",
                    help="WoW veil-pierce gate mode: score candidate CONNECTED_BY_DEED owner groups as "
                         "genuine WoW false-splits (PASS) vs over-lumps (FAIL) via wow_gate.py. "
                         "Default population = deed-only groups; restrict with --owner-group.")
    ap.add_argument("--owner-group", dest="owner_groups", action="append", default=[], metavar="OG-ID",
                    help="(with --gate) gate only these owner_group_id(s); repeatable.")
    a = ap.parse_args()

    if a.gate:
        rep = gate_mode(a.owner_groups or None, Path(a.out))
        print(f"WoW veil-pierce gate [{rep['population']}]: {rep['n_pass']}/{rep['n_candidates']} PASS · "
              f"{rep['n_fail']} over-lumps  ->  {Path(a.out) / 'wow_gate.json'}")
        for r in rep["results"]:
            tag = "PASS" if r["passed"] else "FAIL"
            reason = "" if r["passed"] else f"  — {r['reasons'][0]}" if r["reasons"] else ""
            print(f"  {tag}  {r['owner_group']:<14} {r['buildings']:>4} bldgs{reason}")
    else:
        if not (a.key and a.annotations):
            ap.error("--key and --annotations are required (or use --gate)")
        rep = score(a.key, a.annotations, Path(a.out))
        print(f"pairs {rep['n_pairs']}  κ={rep['kappa']}")
        for st, m in rep["strata"].items():
            if "strict_precision" in m:
                print(f"  {st:<28} precision strict {_fmt(m['strict_precision'])} · "
                      f"inclusive {_fmt(m['inclusive_precision'])} · C2 {m['c2_share']} · cov {m['coverage']}")
            else:
                print(f"  {st:<28} split-precision {_fmt(m['split_precision'])} · cov {m['coverage']}")
        h = rep["head_to_head"]
        print(f"  vs WoW: discordant {h['discordant']} · watchline✓/wow✗ {h['watchline_right_wow_wrong']} · "
              f"wow✓/watchline✗ {h['wow_right_watchline_wrong']} · McNemar p={h['mcnemar_p']}")
