"""eval/cutover_score.py — the §8.1 Track-A cutover gate scorer (Option B).

Joins `cutover_key.jsonl` (from `cutover_frame.py`) with adjudications and computes the ratified gate:

  * SEVERE-ERROR VETO — any adjudicated **severe false merge** fails the candidate.
  * PAIRED, DEPLOYMENT-WEIGHTED NONINFERIORITY — upper one-sided 95% bound of the paired-bootstrap
    difference `L(v2) − L(legacy)` must be `≤ δ` (`δ = 0.01`), `L = 5·FM + 1·FS`.

The two strata map to the v2-vs-legacy decision structure (v2 is a strict refinement of legacy):
  * **S1** (v2 SPLIT, legacy MERGED — the disagreement): gold DIFFERENT ⇒ v2 correct / legacy false-merge;
    gold SAME ⇒ v2 false-split / legacy correct.
  * **S2** (BOTH MERGED — agreement, samples v2's retained merges): gold DIFFERENT ⇒ both false-merge;
    gold SAME ⇒ both correct.
So the paired *difference* is driven by S1; S2 estimates the absolute retained-merge false-merge rate (FM)
that the gate also reports. `INDETERMINATE` is excluded from the primary estimate (worst-case reported too).

Weights are the preregistered **deployment** stratum weights (S1 = split decisions, S2 = merge decisions);
the census/sample frames oversample, so pass deployment weights — defaults are sample-proportional with a
`weights_are_deployment=False` flag so an un-weighted run is never mistaken for the ratified gate.
Confidence-interval method: Clopper–Pearson for the per-mechanism rates (scipy), paired bootstrap for the
loss difference. C0 is scored separately (not here).
"""
from __future__ import annotations

import random

FM_WEIGHT = 5.0
FS_WEIGHT = 1.0
DELTA = 0.01
S1, S2 = "S1_split", "S2_retained_merge"


def per_item_loss(stratum: str, gold: str) -> tuple[float, float]:
    """(v2_loss, legacy_loss) for one determinate adjudicated pair, weighted 5·FM + 1·FS."""
    if stratum == S1:                       # v2 split; legacy merged
        return (0.0, FM_WEIGHT) if gold == "DIFFERENT" else (FS_WEIGHT, 0.0)
    return (FM_WEIGHT, FM_WEIGHT) if gold == "DIFFERENT" else (0.0, 0.0)   # S2: both merged


def _bootstrap_upper(diffs: list[float], weights: list[float], *, n: int, seed: int,
                     alpha: float = 0.05) -> float:
    """Upper one-sided (1−alpha) bound of the weighted-mean paired difference, by resampling items."""
    m = len(diffs)
    if m == 0:
        return 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        num = sum(diffs[i] * weights[i] for i in idx)
        den = sum(weights[i] for i in idx)
        means.append(num / den if den else 0.0)
    means.sort()
    return means[min(n - 1, int((1 - alpha) * n))]


def _cp_upper(k: int, n: int, alpha: float = 0.05) -> float | None:
    """One-sided Clopper–Pearson upper bound for an error rate k/n (None if scipy absent)."""
    if n == 0:
        return None
    try:
        from scipy.stats import beta
    except ModuleNotFoundError:
        return None
    return 1.0 if k == n else float(beta.ppf(1 - alpha, k + 1, n - k))


def score_cutover(key_rows: list[dict], annotations: list[dict], *, delta: float = DELTA,
                  weights: dict | None = None, weights_are_deployment: bool = False,
                  bootstrap_n: int = 10000, seed: int = 42) -> dict:
    """Compute the Track-A gate. `annotations`: `[{pair_id, label, severe?}, …]` (label ∈
    SAME/DIFFERENT/INDETERMINATE; `severe` marks a severe false merge). `weights`: per-stratum deployment
    weight (set `weights_are_deployment=True` for a real gate). Returns the verdict + components."""
    ann = {a["pair_id"]: a for a in annotations}
    joined = [{"stratum": k["stratum"], "gold": ann[k["pair_id"]].get("label"),
               "severe": bool(ann[k["pair_id"]].get("severe", False))}
              for k in key_rows if k["pair_id"] in ann]
    det = [j for j in joined if j["gold"] in ("SAME", "DIFFERENT")]
    n_indet = sum(1 for j in joined if j["gold"] == "INDETERMINATE")

    severe_false_merges = [j for j in det if j["stratum"] == S2 and j["gold"] == "DIFFERENT" and j["severe"]]

    wmap = weights or {S1: 1.0, S2: 1.0}
    diffs, wts = [], []
    for j in det:
        v2l, legl = per_item_loss(j["stratum"], j["gold"])
        diffs.append(v2l - legl)
        wts.append(wmap.get(j["stratum"], 1.0))
    diff_upper = _bootstrap_upper(diffs, wts, n=bootstrap_n, seed=seed)

    s1 = [j for j in det if j["stratum"] == S1]
    s2 = [j for j in det if j["stratum"] == S2]
    fs_v2_k = sum(1 for j in s1 if j["gold"] == "SAME")          # v2 false splits (S1 census)
    fm_v2_k = sum(1 for j in s2 if j["gold"] == "DIFFERENT")     # v2 false merges (S2 sample)
    coverage = len(det) / len(joined) if joined else 0.0

    veto_ok = not severe_false_merges
    noninferior = diff_upper <= delta
    return {
        "verdict": "PASS" if (veto_ok and noninferior) else "FAIL",
        "severe_veto_ok": veto_ok, "severe_false_merges": len(severe_false_merges),
        "noninferiority_ok": noninferior, "delta": delta,
        "loss_diff_upper95": round(diff_upper, 4),
        "weights_are_deployment": weights_are_deployment,
        "fs_v2": {"k": fs_v2_k, "n": len(s1), "rate": (fs_v2_k / len(s1)) if s1 else None,
                  "cp_upper95": _cp_upper(fs_v2_k, len(s1))},
        "fm_v2": {"k": fm_v2_k, "n": len(s2), "rate": (fm_v2_k / len(s2)) if s2 else None,
                  "cp_upper95": _cp_upper(fm_v2_k, len(s2))},
        "coverage": round(coverage, 3), "determinate": len(det), "indeterminate": n_indet,
        "worst_case_fm_v2_rate": ((fm_v2_k + n_indet) / (len(s2) + n_indet)) if (len(s2) + n_indet) else None,
    }
