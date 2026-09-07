# Option B migration — Phase 2 findings (parallel build)

**Date:** 2026-09-07 · **Status:** findings from building `ResolvedEntityV2` alongside legacy; **F1
needs a C3 refinement decision before the resolver is run for the cutover.** The C3 resolver
(`resolved_entity.resolve`) is committed as the **signed-off** spec and is **not** changed here.

## F1 — C3 person-attribute cannot-links wrongly split entity-level (`registered-llc`) merges

**What the parallel build showed** (read-only, live graph, snapshot 2026-09-07): running `resolve_graph`
over the identity edges and comparing to legacy identity-only union-find:

| | components (multi-member) |
|---|---|
| legacy identity-only (no C3 constraints) | 6,690 |
| C3 as signed off | **6,498** (+ extra singletons; 7,311 total) |

C3 **dropped 859 edges — all `registered-llc-name`**: 847 on the **surname** constraint, 12 on
**entity_type**. **Zero** `splink-fellegi-sunter` edges were dropped; **zero** `curated` adjudications.
Of 16,034 references, 16,017 classify as `person`.

**Root cause.** `registered-llc` links landlord nodes whose buildings share a DOF owner **entity**, so it
deliberately connects **differently-surnamed person references** (co-officers of one LLC) — "links by
owner entity, spans surnames by design." C3's `surname` and `entity_type` cannot-links are
**person-identity** properties; applying them to an **owner-entity** assertion splits legitimate merges.
The rest of the pipeline already treats this asymmetrically — `verify_splink` scopes its hard
cross-surname gate to **model edges only**, and `cluster_gated` keeps `fellegi-sunter` edges
surname-clean **upstream** (hence 0 fellegi drops here).

**Why this is the parallel build doing its job:** the gap surfaced read-only, before any cutover, with a
faithful implementation of the signed-off contract. No silent fix.

### Proposed C3 refinement (for review — pick one)

- **R1 — scope person-attribute constraints to person-identity edges.** `surname` / `entity_type`
  cannot-link apply only when the *merging edge* is `fellegi-sunter`; `registered-llc-*` and `curated`
  (owner-level) impose only the **conflicting-identifier** constraint. *Con:* constraints become
  edge-method-scoped, not clean component-summary properties (a component can then hold mixed surnames via
  an llc edge, which is correct but complicates the invariant).
- **R2 (recommended) — drop person-attribute cannot-links from C3; keep conflicting-identifier + an
  institution guard.** Rationale: `fellegi` surname-cleanliness is already enforced upstream
  (`cluster_gated`), and `registered-llc`/`curated` are owner-level (surname/type-agnostic), so the
  universal `surname`/`entity_type` cannot-links are **redundant for fellegi and wrong for llc**. Retain
  the **conflicting stable identifier** hard constraint (universal, correct; a no-op until DOS ids exist)
  and a coarse **institution guard** (institutions are already excluded from ownership, so don't fold one
  into an owner component). *Effect:* C3 matches legacy identity-only on the 859 owner-entity merges while
  keeping the adjudication path for identifier conflicts.

**Recommendation: R2.** It aligns with the existing architecture (cross-surname is a model-edge concern,
handled upstream), keeps C3's constrained-union-find clean, and preserves the invariant the reviewer cared
about (deterministic conflicts → adjudication). The permutation-invariance and allowlist properties are
unchanged. If chosen, C3/§C3 and `resolve` update together, with the surname/entity-type tests replaced by
identifier-conflict + institution-guard tests.

**Blocking:** the resolver should not be run *for the cutover comparison* until R1/R2 is decided — the
current output over-splits 859 real owner merges. Everything else in Phase 2 (graph read, party-reference
keying, parallel materialization) can proceed.
