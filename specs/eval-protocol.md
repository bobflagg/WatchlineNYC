# Evaluation Protocol — Beneficial-Ownership Resolution (minimal viable)

**Goal.** Measure, against adjudicated ground truth, whether WatchlineNYC's ownership
resolution (a) correctly merges an owner's differently-named LLCs without over-merging, and
(b) correctly splits owners that WoW fuses via shared management addresses — and quantify the
delta vs. WoW's clustering. Designed for one collaborator-pair, ~600 pairs, ~2 weeks.

**As-of date.** Fix a snapshot date `D`. Both systems' decisions and all adjudication evidence
are evaluated as of `D`. Freeze strata, sampling frame, codebook, and metrics *before*
adjudicating (lightweight preregistration; note it in the paper).

---

## 1. Unit & labels

**Unit:** the pairwise decision — *"are landlord entities X and Y the same beneficial owner?"*
**Labels:** `SAME` · `DIFFERENT` · `INDETERMINATE`. Indeterminate is a first-class outcome
(public record often can't settle ownership); excluded from precision/recall denominators and
reported separately as **coverage**.

Every `SAME` also carries a **corroboration class**, assigned at scoring from the recorded evidence
and the system's signal (see §3):
- **C1 — cross-source corroborated**: rests on ≥1 source *other than* the record the system keyed on.
- **C2 — same-source verified**: rests only on the primary record the system's signal used, with all
  three mandatory checks (§3) passed.

Precision is reported **both ways** — strict (C1 only) and inclusive (C1+C2); the gap discloses how
much of a result stands on single-source (typically deed-only) evidence.

## 2. Strata & sampling (~600 pairs)

Uniform sampling is useless (≈all random pairs are trivial non-matches). Sample where decisions
and errors live. Draw each stratum by simple random sample from its frame; record the frame size.

| # | Stratum | Frame (pairs, as of `D`) | n |
|---|---------|--------------------------|---|
| S1 | **Deed merges** | linked (incl.) by `CONNECTED_BY_DEED` | 150 |
| S2 | **Model merges** | linked by `CONNECTED_BY_SPLINK` method `splink-fellegi-sunter` | 150 |
| S3 | **Aggregator splits** | share a masked aggregator business address, placed in **different** OwnerGroups | 150 |
| S4 | **Hard negatives** | same surname **or** same address, **not** merged | 150 |

**Recall anchors (not sampled):** a fixed set of operators with *externally documented, complete*
portfolios (e.g. Croman via the AG settlement, plus named portfolios from enforcement actions /
investigative reporting). Used only for recall (§4).

## 3. Annotator codebook

**Golden rule — what counts as evidence.** The system's *output* (a `CONNECTED_BY_DEED` edge, an
OwnerGroup assignment, any "match" flag) is **never** evidence. Only **primary records** are — ACRIS
deeds, NYS DOS filings, HPD registrations, court/enforcement records. The tool presents *all* primary
records for both entities and never highlights "the match," and the annotator is **blind** to the
system's signal (§4), so they reconstruct the picture independently.

**Evidence hierarchy** (record the highest tier reached + a one-line rationale):

- **T1** — ACRIS deed grantee identity / documented conveyance chain (incl. grantor-chain restructuring).
- **T2** — NYS DOS entity filing: shared CEO / process / registered-agent principal. *Thin in
  practice — `ceoname` is populated for ~11% of LLCs, the process name is usually the entity itself,
  and DOS is active-only (dissolved shells absent). "No DOS match" ≠ "no such entity."*
- **T3** — shared principal across independent filings (HPD registration, mortgage, court).
- **T4** — external record: AG/DOF settlement, court judgment, named-portfolio reporting, JustFix data.
- **Insufficient** — address-only, name-only, or nothing but the system's own output.

**Decision rules.**
- `DIFFERENT` ⇐ positive evidence of *distinct* ownership (distinct grantees / distinct principals /
  no linking conveyance).
- `SAME` ⇐ co-ownership verified from primary records, recorded as **C1** (a corroboration from a
  source *other than* the record the system keyed on) or **C2** (only the same primary-record type the
  system's signal used — permitted **only** behind the hard gate below).
- else `INDETERMINATE`.

**Circularity ruling.** Circularity is *not* "used the same signal" — it is "used the system's
*output*, or confirmed a match the adjudicator could not have overturned." Verifying the same primary
*record* the system keyed on is allowed, because the adjudicator checks inputs the heuristic cannot
and can reject the pair — but only as **C2**, and only when **all three** mandatory checks pass
(recorded as checkboxes; no C2 `SAME` without all three):

1. **Entity identity** — the linking party is the *same* entity across the deeds, not a
   normalized-name collision (confirm via DOS record / consistent address, not the name string alone).
2. **Successor reality** — each successor LLC is genuinely single-purpose (pull *its own* full ACRIS
   history), not an independent portfolio the system's size proxy under-counted.
3. **Restructuring vs. sale** — the onward conveyance reads as the grantee restructuring its own
   holdings (nominal/related-party transfer; timing/attorney pattern), not an arms-length sale.

If any check fails or cannot be made, the pair is `INDETERMINATE`, not `SAME`. Rationale for the
ruling: the fully-obscured veil-pierce cases — the system's most valuable output — show *nothing* in
DOS/HPD by design, so a rule that demanded cross-source corroboration for every `SAME` could never
confirm them; C2 credits them, the hard gate keeps them honest, and §5's strict number quarantines
them for skeptics.

## 4. Annotation process

- **2 annotators**, independent, **blind** to which system (WatchlineNYC / WoW) produced any
  decision and blind to the driving signal.
- **Every pair captures**: label, highest evidence tier, a one-line rationale, and — for any `SAME`
  whose only corroboration is the deed record — the **three C2 checkboxes** (§3). The tool enforces
  the hard gate: a deed-only `SAME` missing any checkbox is recorded as `INDETERMINATE`. The system's
  signal is *not* shown; class C1/C2 is assigned at scoring by rejoining the blinding key.
- Report **inter-annotator agreement (Cohen's κ)**; target κ ≥ 0.70, else diagnose the stratum.
- **Third-party adjudication** (or documented consensus) resolves disagreements → the gold label.

## 5. Metrics

Compute per stratum; report **Wilson 95% CIs** on all proportions.

- **Precision (S1, S2)** among system-merged pairs, reported **two ways** (see §1 corroboration
  classes): **strict** = `C1 / (C1 + DIFFERENT)`, **inclusive** = `(C1+C2) / (C1+C2 + DIFFERENT)`.
  `INDETERMINATE` excluded from the denominator. Also report **coverage** = `1 − INDETERMINATE/n` and
  the **C2 share** of confirmed SAMEs (the strict↔inclusive gap) — expect it large on S1 (deed),
  small on S2 (model).
- **Split precision (S3)** = `DIFFERENT / (SAME + DIFFERENT)` (a correct split = the pair really is
  two different owners).
- **False-merge rate (S4)** = `SAME / adjudicable` (guards against vetoes/mask over-firing —
  should be low; these were *not* merged, so `SAME` here = a recall miss, not a precision error).
- **Recall (anchors only)** = recovered true same-owner pairs / all true pairs within each
  documented portfolio. Full-population recall is **not** claimed; say so.
- *(optional)* **B³ precision/recall** on the anchor portfolios for cluster-shape quality.

## 6. Head-to-head vs. WoW

- Run **both** systems' merge/split decision on the **same** adjudicated pairs (blind).
- Paired data on identical items ⇒ significance by **McNemar's test** on the discordant pairs
  (where the two systems disagree and the gold label breaks the tie). Report on S2 + S3.
- **Headline table:** Precision / Split-precision / Recall-proxy / F1 for WoW vs. WatchlineNYC,
  overall and on the disagreement strata, with CIs and McNemar *p*.

## 7. Controls & error analysis

- **Data-vintage control.** Any system disagreement traceable to a record present in one snapshot
  but absent in the other (cf. the 333 Rector / "Dianna Lam" confound) is bucketed as **DATA**, not
  **METHOD**, and excluded from method precision/recall. Report the two buckets separately.
- **Error taxonomy.** Tag every gold error (false `SAME` / false `DIFFERENT`) with a cause:
  `common-name` · `stale-deed` · `aggregator-leak` · `missing-filing` · `genuine-ambiguity`.
  This figure is the contribution, not just the number.

## 8. Preregistered decision rules (fix these before adjudication)

Fixing the rules before any data is seen is what turns the head-to-head from a demo into evidence.
Folded from [`ownership-model-spec.md`](ownership-model-spec.md) §9. Bracketed values are defaults to
**fix with the team / co-adjudicator before adjudication**, not post hoc.

- **Primary metric:** strict precision (C1-only) on system-merged pairs (S1+S2); inclusive is secondary.
  The strict number is the claim; the strict↔inclusive gap (C2 share) is reported, not buried.
- **INDETERMINATE in the headline:** reported *as* coverage (`1 − INDET/n`) beside every precision
  figure, never silently dropped. A stratum with coverage `< [0.70]` is reported **inconclusive**, not
  scored.
- **Reviewer-agreement gate:** κ `≥ [0.60]` on the double-adjudicated subset. Below it, revise the
  codebook and re-adjudicate that stratum *before* reporting any metric.
- **Blinding of mechanism:** adjudicators see **records only** — blind to both the system's decision and
  the linking mechanism. Per-mechanism precision/recall (`registered-llc` / `acris-deed` /
  `fellegi-sunter` / `curated`) is computed **post hoc** by rejoining the private key, so mechanism
  knowledge can't bias a label.
- **Independent ground truth:** a SAME is C1 only if corroborated by ≥2 **independent primary sources**
  (§1); the system's own output is never evidence.
- **Recall proxy (name which):** recall is reported only against the **curated anchor portfolios**
  (documented owners) as an explicit proxy — full-population recall is undefined for unknown
  common-control and is **not** claimed. Optionally add discovery-yield among known cases.
- **Sampling weights:** strata are fixed-n, not proportional; per-stratum numbers are primary, and any
  pooled/population estimate must **reweight by stratum prevalence**.
- **Go / no-go for the method claim (design-paper level):** WatchlineNYC strict precision `≥` WoW
  precision on the disagreement strata, McNemar `p < 0.05`, with false-merge rate (S4) `≤ [bar]`.
  Failing that, report the honest negative.
- **Stopping / rollback:** if *severe* false-attribution — a false SAME implicating a **living person**
  or bridging groups whose combined size `> [T]` — exceeds `[rate]` in any stratum, that mechanism is
  pulled from the merged set pending fix, and the fact is reported, not hidden.

**Launch thresholds are staged and stricter (deferred).** The bars above validate the *method* for a
design paper. *Public attribution* requires the separate, consequence-tiered thresholds in
[`ownership-model-spec.md`](ownership-model-spec.md) §8/§10 — set per rollout stage (research < beta <
public) — which this minimal eval does not establish.

### 8.1 Identity-resolution cutover thresholds (gate the Option B Phase-5 cutover)

The Phase-5 identity cutover gate is preregistered and frozen (run manifest pins this section's revision
hash) **before Phase-2 results are seen**. `[RATIFY]` = a value the team fixes at sign-off. Two rules that
make the earlier draft statistically coherent:

- **Gates are on confidence bounds, not point estimates.** Precision passes only if its **one-sided 95%
  lower bound** meets the threshold; an error rate passes only if its **one-sided 95% upper bound** is below
  it. (99/100 correct does *not* pass a 99% gate.)
- **Sample size is power-derived per independently-gated population, not fixed.** With zero observed errors
  the one-sided 95% upper bound ≈ 3/n, so certifying an error rate `p` needs ≈ `3/p` **determinate**
  observations — ~**299** for a 99% precision lower bound, ~**598** for a 0.5% upper bound; at 70–80%
  coverage, ~430–855 sampled. A fixed n≈100 is for **descriptive** strata only, never for certifying 0.5%.

### Tiered by consequence (matches the staged rollout: research < beta < public)

The full statistical **certification** is the bar for **production / public exposure** (Track B, or any
public use of the identity layer). The **Track-A internal cutover** — reversible by version selection, no
public exposure, replacing a legacy layer never certified to any bound — uses a proportionate gate: it must
be **no worse than the incumbent and carry no observed severe error**, not independently certify 0.5%.

**Track-A internal-cutover gate (feasible now):**
- **Severe-error veto:** *any* adjudicated **severe** false merge (defined below) fails the candidate.
- **Relative gate — a paired noninferiority test, not a point comparison.** Weighted loss
  `L = 5·FM + 1·FS`, where **FM** and **FS** are each **deployment-weighted rates** — the adversarial
  strata are reweighted back to population prevalence so the two terms share a common per-decision estimand
  (FM among merge decisions, FS among split decisions, combined on the deployment-weighted decision mix).
  Both systems are scored on the **same adjudicated items** (paired), determinate-only for the primary
  estimate. The gate: the **one-sided 95% upper bound of the paired, deployment-weighted difference
  `L(v2) − L(legacy)`** (paired bootstrap over adjudicated items) must be **≤ a preregistered
  noninferiority margin `[RATIFY] δ`**. `δ = 0` is strict noninferiority and may need more sample than the
  feasible frame supports; a small positive `δ` keeps it feasible — the team fixes `δ` at sign-off.
- **Descriptive, honestly bounded:** report every metric with its named-method one-sided 95% bound **and**
  a sensitivity pair — best case and **worst case (every `INDETERMINATE` counted as an error)** — plus
  coverage and indeterminacy reasons by mechanism and stratum.
- Feasible sample: the ~530-pair eval frame + a component-sampled identity set — enough for the paired
  noninferiority comparison and descriptive bounds, not for independently certifying 0.5%.

**Production / public-exposure certification (deferred):**

| Gate | Rule |
|---|---|
| Deterministic pairwise precision (`curated`/`registered-llc-id`) | one-sided 95% **lower** bound **≥ 99%** |
| Probabilistic pairwise precision (`registered-llc-name`/`fellegi-sunter`) | one-sided 95% **lower** bound **≥ 95%** |
| Component false-merge rate | one-sided 95% **upper** bound **≤ 2%** |
| Severe false merge | any observed case **vetoes**; pooled deployment-weighted **upper** bound **≤ 0.5%** before production |
| Coverage | **≥ 80% overall and per gated mechanism**; ≤80% (down to 70%) only for explicitly-labeled exploratory strata, which are then inconclusive + reported with the worst-case bound |
| Sample size | **power-derived** per independently-gated population (planning approx `≈3/p` → ~299/~598 determinate; ~430–855 sampled). If a mechanism's **total population is smaller** than the required n, **census it** (adjudicate all) rather than declaring it uncertifiable |
| Protected strata | report all. A stratum with an **adequate determinate sample must meet the 2% upper-bound gate**; one **without is reported underpowered/inconclusive and receives no independent assurance** — it does **not** get a fabricated ≤2% claim |
| Underpowered protected stratum → consequence | **blocks production of the affected mechanism/use case** (a high-risk stratum may not "launch anyway"); it may launch only under an explicitly restricted consequence tier. *(Track-A internal cutover: reported inconclusive, **not** a blocker — the severe-veto + reversibility bound the risk; production is where it blocks.)* |
| False splits | secondary constraint via the weighted loss `L` (paired noninferiority, above) |
| Failure | no cutover; correct/remove the mechanism, **freeze a new candidate version**, evaluate on fresh or sequestered data |

**Confidence-interval method (fixed):** gates use **one-sided Clopper–Pearson (exact)** bounds; Wilson is
acceptable for *descriptive* reporting only. The `≈3/p` rule is **planning only** — the actual gate is the
exact bound on observed data. Use the same method consistently across mechanisms and reruns.

### Definitions (fixed here)

- **Severe false merge (consequence-based, not just "distinct parties fused"):** a false merge that
  implicates a **living person**, **bridges components above a declared combined size** (`[RATIFY] T = 25`),
  transfers allegations/enforcement statistics, or connects otherwise-unrelated portfolios through a
  high-impact party. Track A exposes no allegations/public results, so its severe class is the **intrinsic**
  identity kind (living-person / large-bridge); downstream **publication** harm is a Track-B gate.
- **Component false-merge rate denominator:** *number of adjudicated multi-member components containing ≥1
  false merge ÷ number of adjudicated multi-member components.* **Sample components directly**, stratified
  by size and bridge-dependence (pair sampling under-detects one bad member in a large component). An
  `INDETERMINATE` member makes the component `INDETERMINATE` (excluded), and is also reported under the
  worst-case (member-is-error) bound.
- **C0 (Level-0) collisions use a different unit:** sample **sets of contributing source rows within one
  `party_reference`** (not party-reference pairs — the collision is *inside* a reference, pre-resolution).
  Report the collision rate among multi-row party references, the % showing evidence of >1 real party, and
  the buildings/records affected. The severe-error veto applies to C0 too (it is an irreversible
  pre-resolution identity operation).

The main §8 head-to-head rules carry `[RATIFY]` proposals frozen the same way: false-merge S4 `[bar]`,
severe-attribution stopping `[rate]`, bridge size `[T] = 25`.

## 9. Cluster-level validity & ablation

Pairwise precision (§5) is necessary but not sufficient: a good edge rate can still produce bad
clusters (one false bridge merges two valid groups). On the anchor portfolios (where a gold cluster
exists), also report:

- **Cluster metrics:** false-merge / false-split rate, **B³ purity & completeness**, and the max and
  distribution of cluster error (not just the mean).
- **Bridge sensitivity:** recompute clusters after removing each single inferred edge; a group that
  collapses when one edge is dropped is a bridge-risk flag. Report **direct-evidence** membership
  separately from **transitive** membership.
- **Ablation (isolates the common-control layer's marginal value):** score four configurations on the
  same items — (a) WoW, (b) sourced records only, (c) + registration network, (d) + both. If (d) does
  not beat (c)/(b) on the task metrics, the common-control layer is not earning its complexity.
- **Adversarial strata (extends §2):** the sample must over-include the dangerous cases random sampling
  misses — common surnames, shared professional/office addresses, relatives, large managers, reused LLC
  addresses, high-degree nodes.

## 10. Deliverables

1. Head-to-head metrics table (per stratum + WoW comparison, CIs, McNemar *p*) — precision **strict
   and inclusive**, with the **C2 share** per stratum.
2. κ and coverage / indeterminate rate.
3. Error-taxonomy breakdown (counts by cause).
4. **Released benchmark:** anonymization-reviewed pairs + gold labels + evidence tiers + rationales
   + this codebook — a reusable ground-truth set (a resource contribution in its own right).

**Notes on credibility.** Reporting an indeterminate rate and a data-vintage split reads as rigor,
not weakness — everyone in this domain knows ownership hides. A JustFix collaborator as
co-adjudicator materially raises trust in the gold set and neutralizes the "who says you're right"
objection.
