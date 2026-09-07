# Review note — Finding F1: one C3 constraint-scope decision

**Date:** 2026-09-07 · **Asks:** one decision (R1 vs R2) to refine a C3 constraint scope. **Detail:**
[`ownership-phase2-findings.md`](ownership-phase2-findings.md). **Does not reopen sign-off** — Part A + B1
stand; this is a scoped refinement of C3 (which you signed off), surfaced by the parallel build doing its
job.

## What happened

Phase 2 built `ResolvedEntityV2` (the C3 constrained-clustering resolver) **alongside the untouched legacy
layer** and ran it **read-only** against the live graph. Comparing to legacy identity-only union-find:

| | multi-member components |
|---|---|
| legacy identity-only | 6,690 |
| C3 as signed off | **6,498** (+ extra singletons) |

C3 **dropped 859 `registered-llc-name` edges** — **847 on `surname`, 12 on `entity_type`**. **Zero**
`fellegi-sunter` drops, **zero** `curated` adjudications. (16,017 of 16,034 references classify as person.)

## Why

`registered-llc` links landlord nodes whose buildings share a DOF **owner entity** — so it deliberately
connects **differently-surnamed person references** (co-officers of one LLC): "links by owner entity, spans
surnames by design." C3's `surname`/`entity_type` cannot-links are **person-identity** properties; applied
to an **owner-entity** assertion they split legitimate merges. The rest of the pipeline already treats this
asymmetrically — `verify_splink` scopes its cross-surname gate to **model edges only**, and `cluster_gated`
keeps `fellegi` edges surname-clean **upstream** (hence 0 fellegi drops here).

## The decision (pick one)

- **R1 — scope person-attribute constraints to person-identity edges.** `surname`/`entity_type` apply only
  when the merging edge is `fellegi-sunter`; `registered-llc-*`/`curated` impose only conflicting-identifier.
  *Con:* constraints become edge-scoped rather than clean component-summary properties.
- **R2 (recommended) — drop person-attribute cannot-links from C3; keep conflicting-identifier + an
  institution guard.** `fellegi` surname-cleanliness is already enforced upstream, and `registered-llc`/
  `curated` are owner-level (surname/type-agnostic), so the universal `surname`/`entity_type` cannot-links
  are **redundant for fellegi and wrong for llc**. Retain the **conflicting stable identifier** hard
  constraint (correct, universal; no-op until DOS ids) and a coarse **institution guard** (institutions are
  already excluded from ownership).

**Effect of R2:** C3 stops over-splitting the 859 owner-entity merges (matches legacy on those); the
constrained-union-find, **permutation-invariance**, allowlist, and deterministic→adjudication path are
**unchanged**; the surname/entity_type unit tests are replaced by identifier-conflict + institution-guard
tests.

## What it blocks / doesn't

- **Blocks:** running the resolver for the **cutover comparison** — today it over-splits 859 real merges.
- **Does not block:** the rest of Phase 2 (party-reference stable keying, parallel materialization), which
  proceeds regardless.

## Sign-off

- [ ] **R2** approved (recommended) — or [ ] R1 — or [ ] adjust: ____________________
- Reviewer: __________________ date: __________
