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
(public record often can't settle ownership); it is excluded from precision/recall denominators
and reported separately as **coverage**.

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

Apply this **evidence hierarchy**; record the highest tier reached and a one-line rationale.

- **T1** — ACRIS deed grantee identity / documented conveyance chain
- **T2** — NYS DOS entity filing: shared registered principal / officer / signatory
- **T3** — shared principal across *independent* filings (HPD reg, mortgage, court) — **not** the
  signal the system used
- **T4** — external record: AG/DOF settlement, court judgment, named-portfolio reporting, JustFix
  curated data
- **Insufficient** — address-only, name-only, **or only the signal the system used**

**Decision rules.**
- `SAME` ⇐ ≥1 corroboration at T1–T4 that is **independent of the system's driving signal**.
- `DIFFERENT` ⇐ positive evidence of *distinct* ownership (distinct grantees / distinct principals).
- else `INDETERMINATE`.

**Circularity rule (mandatory).** If the system merged the pair via signal *S* (e.g. a deed), the
adjudicator may **not** use *S* as the basis for `SAME`; independent corroboration is required, or
the pair is `INDETERMINATE`. State this explicitly in the paper.

## 4. Annotation process

- **2 annotators**, independent, **blind** to which system (WatchlineNYC / WoW) produced any
  decision and blind to the driving signal.
- Report **inter-annotator agreement (Cohen's κ)**; target κ ≥ 0.70, else diagnose the stratum.
- **Third-party adjudication** (or documented consensus) resolves disagreements → the gold label.

## 5. Metrics

Compute per stratum; report **Wilson 95% CIs** on all proportions.

- **Precision (S1, S2)** = `SAME / (SAME + DIFFERENT)` among system-merged pairs; report
  **coverage** = `1 − INDETERMINATE/n`.
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

## 8. Deliverables

1. Head-to-head metrics table (per stratum + WoW comparison, CIs, McNemar *p*).
2. κ and coverage / indeterminate rate.
3. Error-taxonomy breakdown (counts by cause).
4. **Released benchmark:** anonymization-reviewed pairs + gold labels + evidence tiers + rationales
   + this codebook — a reusable ground-truth set (a resource contribution in its own right).

**Notes on credibility.** Reporting an indeterminate rate and a data-vintage split reads as rigor,
not weakness — everyone in this domain knows ownership hides. A JustFix collaborator as
co-adjudicator materially raises trust in the gold set and neutralizes the "who says you're right"
objection.
