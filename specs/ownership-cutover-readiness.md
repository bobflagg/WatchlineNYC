# Track-A cutover readiness — for the colleague

**Date:** 2026-09-07 · **Ask:** authorize the **Track-A internal identity cutover** (swap canonical
identity reads to `ResolvedEntityV2`), or tell us what more you need. Reversible, no public exposure.
**Detail:** `ownership-phase1-contracts.md` (rev 7), `ownership-phase2-findings.md`, `eval-protocol.md` §8.1.

## Engineering is ready

The whole v2 layer is **built parallel to an untouched legacy layer**, materialized, and validated:
- `:ResolvedEntityV2` materialized (run `REV2-20260907T230254Z`): **5,886 entities / 13,756 memberships**,
  each with `party_reference_id` (C1 lineage). Legacy `OwnerGroup` (6,540) **untouched**; rollback = drop
  the run (version selection).
- Modules (all read-only/pure/additive, hermetically tested): C3 resolver, C1 keying, C0 collapse+lineage,
  C4 relationship layer, C5 co-op/condo projection, shadow harness.

## The key evidence — v2 is a *strict refinement* of legacy

Shadow comparison (`shadow_compare.py`, also run against the materialized run):
- **`v2_entities_spanning_legacy_groups = 0`** — v2 **never merges anything legacy split**. Every v2 merge
  is a subset of a legacy merge, so **v2's identity false-merge rate ≤ legacy's by construction.**
- v2 differs from legacy only by (a) **splitting 79 legacy groups** and (b) **excluding 2,449
  association-only nodes** from identity — and those removed merges were **owner-associations**
  (registered-llc co-officers, deed co-conveyance), correctly relocated to the C4 relationship layer per
  R3. They were never same-party identity.

So the cutover's *only* real risk is: **are those 79 splits correct** (do they separate genuinely distinct
parties)? R3 says yes (co-officers/co-conveyance are distinct parties); the cutover gate should confirm it.

## Findings resolved by the parallel build

- **F1 → R3 (your diagnosis):** `registered-llc` was misclassified as identity (co-officers = distinct
  people). Now a C4 relationship, not identity. Identity = fellegi + audited curated only. C3 constraints
  retained and now fire 0 times on clean input.
- **F2:** legacy folded the **co-op/condo exclusion into grouping**; v2 keeps identity clean and excludes
  co-op/condo at the C5 projection (157 entities flagged `coop_condo_dominated`, not dropped).
- **F3:** C0 residual collision risk is **bounded (349 collapses / 2,645 buildings = 0.31%)**; lineage
  retained; same-name/same-address different-person risk is **not** auto-detectable → human-sampled.

## Decisions needed to authorize the cutover

1. **Confirm F1/R3** — the registered-llc → relationship taxonomy (you recommended it; confirm the
   implementation matches: identity is fellegi + audited curated only).
2. **Curated audit** — confirm each `CURATED_OWNERS` seed means *same person/legal entity* (Croman/Rashad
   ✓ same-person; **Kadden** needs confirming it's same-person, not co-owners).
3. **The §8.1 Track-A gate — proposed proportionate form.** Rather than the full production eval, gate the
   *reversible, no-exposure* cutover on a **focused adjudication of a sample of the 79 v2 splits** (are the
   separated entities genuinely distinct parties?) plus the C0 same-name/same-address stratum — with the
   already-ratified **severe-error veto** and **noninferiority (`δ = 0.01`, `T = 25`)** computed on that
   sample. The refinement invariant already bounds false-merges; this adjudication tests the split
   (recall) side directly and feasibly. *(Full B2 production certification stays deferred with Track B.)*

## What the cutover does / does not

- **Does:** switch canonical **identity** reads to v2 (internal), behind a version switch; **fully
  reversible**; migrate the 3 internal consumers (aggregator_audit, verify_splink, eval/sample).
- **Does not:** expose deed **paths**, draw **control conclusions**, or make any **public** attribution —
  Track B stays locked; B2 production certification stays deferred.

## Sign-off

- [ ] F1/R3 confirmed · [ ] curated audit done (Kadden: ______) · [ ] §8.1 Track-A gate form approved
- [ ] **Cutover authorized** — or, what's still needed: ____________________
- Reviewer: __________________ date: __________
