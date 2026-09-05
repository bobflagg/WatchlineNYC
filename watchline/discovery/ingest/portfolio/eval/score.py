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

from watchline.shared.connections import pg_conn

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--out", default="eval_out")
    a = ap.parse_args()
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
