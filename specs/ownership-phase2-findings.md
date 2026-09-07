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

### F1 RESOLUTION — R3 (neither R1 nor R2), 2026-09-07

Review rejected both R1 and R2 and diagnosed the real error: **`registered-llc` was misclassified as an
identity edge.** It links **co-officers — distinct people — of one LLC**, i.e. an owner *association*, not
aliases of one party. Merging them into `ResolvedEntityV2` violates the invariant regardless of constraint
scope. The 859 "over-splits" were the C3 constraints *correctly* preventing distinct people from being
collapsed. **The fix is the edge taxonomy, not the constraints.**

**R3 (adopted):**
- **Remove owner-level `registered-llc` (name-only) from identity resolution** → it joins the substantive
  relationship layer (C4), alongside deeds, as an owner-association.
- **`registered-llc-id`** stays deterministic identity **only for LLC-reference ↔ LLC-reference** (same
  legal entity by jurisdiction + id), **never person↔person** (not present in the graph yet).
- **Audit `curated-same-owner`** by endpoint semantics: keep as identity only where a seed means "these two
  references are the **same person / legal entity**"; a "same owner / shared control" seed is a
  *relationship*, not identity. *(Action: review `CURATED_OWNERS` — Croman/Rashad = same-person fragments ✓;
  confirm Kadden is same-person, not co-owners.)*
- **Retain** C3's person and entity-type cannot-links (they were correct).

**Re-diagnostic after R3 (live, read-only):** identity edges = 10,933 (`splink-fellegi-sunter` 10,744 +
`curated-same-owner` 189); `registered-llc` (2,270) excluded → relationship layer. **ResolvedEntityV2 =
5,886 components, 0 adjudications, 0 dropped** (the cannot-links now have only clean same-party input, so
they fire zero times — correct defense-in-depth). 3 components have a deterministic core (durable-`entity_id`
eligible) — the curated seeds; the rest are probabilistic (`resolution_id` only) until a DOS-id join
activates `registered-llc-id`.

**Takeaway (reviewer):** the parallel build proved the "identity-only" legacy input still carried
owner-association edges. Correct response = fix the taxonomy, not loosen identity. Implemented in
`resolved_entity.py` (identity methods = fellegi + curated only; `registered-llc`/deed rejected fail-closed);
contracts C2/C4 updated accordingly.
