# Track-A cutover readiness — for the colleague

**Date:** 2026-09-07 · **Status:** revised after review — cutover **not yet authorized**; six conditions
tracked below (1 & 6 done, 2–5 remaining). Reversible, no public exposure. **Detail:**
`ownership-phase1-contracts.md` (rev 7), `ownership-phase2-findings.md`, `eval-protocol.md` §8.1.

*Two corrections adopted from review: the "false-merge rate ≤ legacy by construction" claim was wrong
(refinement bounds the merged-pair **set**, not the **rate**); the C0 percentage conflated denominators.
Both fixed below.*

## Engineering is ready

The whole v2 layer is **built parallel to an untouched legacy layer**, materialized, and validated:
- `:ResolvedEntityV2` materialized (run `REV2-20260907T230254Z`): **5,886 entities / 13,756 memberships**,
  each with `party_reference_id` (C1 lineage). Legacy `OwnerGroup` (6,540) **untouched**; rollback = drop
  the run (version selection).
- Modules (all read-only/pure/additive, hermetically tested): C3 resolver, C1 keying, C0 collapse+lineage,
  C4 relationship layer, C5 co-op/condo projection, shadow harness.

## The key evidence — v2 is a *strict refinement* of legacy

Shadow comparison (`shadow_compare.py`, also run against the materialized run):
- **`v2_entities_spanning_legacy_groups = 0`** — v2 **introduces no new merge decisions** relative to
  legacy: every pair v2 merges was also merged by legacy, so v2's set of false-merged pairs is a **subset**
  of legacy's. *(Correction from the prior note: this does NOT prove v2's false-merge **rate** is lower —
  if v2 removed correct pairs while keeping incorrect ones, the conditional error among retained merges
  could rise. The rate of retained merges must still be estimated — see the gate below.)*
- v2 differs from legacy only by (a) **splitting 79 legacy groups** and (b) **excluding 2,449
  association-only nodes** from identity — those removed merges were **owner-associations** (registered-llc
  co-officers, deed co-conveyance), relocated to the C4 relationship layer per R3; never same-party identity.
- **Structural invariant test PASSES** (`verify_membership_identity_only`, run `REV2-20260907T230254Z`):
  the materialized membership (13,756) is *exactly* an identity-only recompute (0 mismatches) — no
  relationship mechanism contributed. `registered-llc` is present in the graph but excluded from identity.

## Findings resolved by the parallel build

- **F1 → R3 (your diagnosis):** `registered-llc` was misclassified as identity (co-officers = distinct
  people). Now a C4 relationship, not identity. Identity = fellegi + audited curated only. C3 constraints
  retained and now fire 0 times on clean input.
- **F2:** legacy folded the **co-op/condo exclusion into grouping**; v2 keeps identity clean and excludes
  co-op/condo at the C5 projection (157 entities flagged `coop_condo_dominated`, not dropped).
- **F3:** C0 **observed exposure** (not a collision-rate bound — the true rate is unknown until
  adjudication), denominators stated separately: **349** party-reference collapses (of **118,116** eligible
  references = **0.30%**); **2,645** affected buildings (of **859,794** = **0.31%**). Lineage retained;
  same-name/same-address different-person risk is **not** auto-detectable → human-sampled.

## The authorization conditions (your six, with status)

1. **F1/R3 + structural invariant test** — ✅ implemented; the test **passes** (above). Confirm F1/R3
   conceptually and that the test is the standing fail-closed guard.
2. **Curated audit — BLOCKER (human).** Classify every `CURATED_OWNERS` seed with `{meaning ∈ same-person |
   same-legal-entity | association | common-control, evidence, reviewer, date, scope}`. Only the first two
   are admissible identity; **Kadden** must be resolved or, if ambiguous, **excluded** from v2 pending
   adjudication. *(Mechanism to add: v2 admits a curated seed only if its meaning is same-person/-entity.)*
3. **The §8.1 Track-A gate — corrected to two strata** (a single split+C0 sample can't estimate retained
   merges, so it can't compute `L = 5·FM + FS`):
   - **Changed decisions — census all 79 split groups** (79 is small; census, don't sample): are the
     separated entities genuinely distinct parties (tests the split/recall side + confirms R3)?
   - **Retained merges — sample v2 components** (over-weight curated, probabilistic-bridge, common-name,
     larger) to estimate false merges among what v2 keeps (the FM side).
   - Compute the **paired, deployment-weighted noninferiority** statistic over a frame with **both** merge
     and split decisions; **severe-error veto** and **δ = 0.01 / T = 25** (ratified) must pass.
   - **C0 is a separate inherited-risk stratum** — legacy and v2 share the Level-0 collapse, so it does not
     distinguish them; report it on its own, and remediate any severe C0 finding.

## What the cutover does / does not

- **Does:** switch canonical **identity** reads to v2 (internal), behind a version switch; **fully
  reversible**; migrate the 3 internal consumers (aggregator_audit, verify_splink, eval/sample).
- **Does not:** expose deed **paths**, draw **control conclusions**, or make any **public** attribution —
  Track B stays locked; B2 production certification stays deferred.

## Sign-off — authorize once all six hold

- [x] (1) identity-mechanism invariant test **passes** (verify_membership_identity_only)
- [ ] (2) every curated seed classified; Kadden resolved or removed
- [ ] (3) all 79 changed groups adjudicated (census)
- [ ] (4) retained v2 merges sampled sufficiently to compute the paired noninferiority gate
- [ ] (5) severe-error veto and `δ = 0.01` gate pass
- [ ] (6) C0 denominator corrected (✅ above) and its findings reported separately
- [ ] **Cutover authorized** — Reviewer: __________ date: __________
