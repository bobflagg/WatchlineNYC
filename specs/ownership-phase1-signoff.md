# Phase 1 sign-off request — Option B ownership migration

**Date:** 2026-09-07 · **Asks:** approve the Phase-1 design decisions **and** ratify the gate numbers, to
unlock Phase 2. **Full detail:** [`ownership-phase1-contracts.md`](ownership-phase1-contracts.md) (rev 5),
[`eval-protocol.md`](eval-protocol.md) §8/§8.1, [`ownership-migration-plan.md`](ownership-migration-plan.md).

This is a **quick accept/adjust**, not a re-read. Signing it freezes the preregistered gate — the run
manifest will pin the §8.1 revision hash so the numbers can't drift.

**Why it's safe to ratify now (no preregistration risk):** everything measured so far (transition matrix,
composition counts, baseline) is *legacy-layer descriptive* data. **`ResolvedEntityV2` does not exist yet**,
so these numbers are being fixed genuinely blind to v2's performance. Sign-off is what lets construction start.

---

## Part A — Design decisions to approve (gates *starting* Phase 2)

Confirm each (details in contracts rev 5). These authorize building; they carry no numbers.

- [ ] **C0** — the base `(name,address)` dedup is a governed Level-0 identity transformation (versioned;
  detects collision *indicators*, doesn't prove distinctness; blocks a durable id on positive contradiction).
- [ ] **C1** — `resolution_id` = universal run-scoped key; `entity_id` = optional durable id via **core
  overlap** (grow/merge/split/conflict); `party_reference` stable *within* a normalization version + lineage.
- [ ] **C2** — fail-closed allowlist; **`registered-llc-id` (deterministic) vs `registered-llc-name`
  (probabilistic)** split — today's edges are name-only.
- [ ] **C3** — deterministic **constrained union-find** (hard cannot-link: entity-type/surname/conflicting-id;
  soft should-link by precedence) + **permutation-invariance test written before build**.
- [ ] **C4** — deeds canonical as `:Event`/`PARTY_TO`; `co_grantee_on_deed` a derived view (not `co-title`).
- [ ] **C5** — source-qualified **latest-observed** projection (no "current"); multi-membership; no allegation
  propagation.
- [ ] **C6** — consumers keyed on `resolution_id`; deny-by-default.
- [ ] **C8** — legacy + v2 built at a **common source watermark**; version selector records the watermark.

## Part B — Numbers to ratify

### B1 — Track-A internal-cutover gate (needed now; gates the reversible internal swap)

| Item | Proposed | Accept / adjust |
|---|---|---|
| **Severe-error veto** | *any* adjudicated severe false merge fails the candidate | |
| **"Severe" = consequence-based** | implicates a **living person**, or bridges components with combined size **> T** | |
| **Large-bridge size `T`** | **25** | |
| **Noninferiority margin `δ`** (upper 95% bound of deployment-weighted `L(v2)−L(legacy)`, `L=5·FM+FS`, paired bootstrap) | **≤ 0.01** *(v2's weighted-error may exceed legacy by at most 0.01; `δ=0` is strict but may exceed the feasible sample)* | |
| **CI method** | one-sided **Clopper–Pearson** for gates (Wilson descriptive only) | |
| **Indeterminate reporting** | determinate-only primary **+** worst-case (indeterminate-as-error) sensitivity | |

### B2 — Production / public-exposure certification (ratify now *or* defer with Track B)

Gates public exposure, **not** the Track-A internal cutover — safe to defer, but freezing now is cleaner.

| Gate | Proposed | Accept / adjust |
|---|---|---|
| Deterministic precision (`curated`/`registered-llc-id`) | one-sided 95% **lower** bound **≥ 99%** | |
| Probabilistic precision (`registered-llc-name`/`fellegi-sunter`) | lower bound **≥ 95%** | |
| Component false-merge rate | upper bound **≤ 2%** | |
| Severe false-merge rate (pooled) | upper bound **≤ 0.5%** | |
| Coverage | **≥ 80%** overall & per gated mechanism | |
| Sample size | **power-derived** (~299/~598 determinate); **census** if population smaller | |
| Underpowered protected stratum | **inconclusive → blocks production** of that mechanism | |
| §8 head-to-head | S4 false-merge `≤ 2%`; severe-stopping `≤ 0.5%`; bridge `T = 25` | |

---

## What sign-off unlocks / does not

- **Unlocks:** Phases 2–5 — build `ResolvedEntityV2` and the event-centric deed relationships **alongside the
  untouched legacy layer**, shadow-compare, migrate the 3 internal consumers, and cut over behind a
  version switch. **Fully reversible** by version selection; **no public exposure** (Track A).
- **Does not unlock:** Track B (research-user deed paths, control-conclusion rules, public attribution) —
  separately gated by the B2 certification + the eval ablation.

## Ratified by

- Reviewer: __________________  date: __________  ·  §8.1 revision hash pinned: __________
- Notes / adjustments: 
