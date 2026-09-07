# Option B migration plan — separating identity from deed relationships

**Date:** 2026-09-07 · **Status:** plan, for review · **Implements:** the Option B decision + invariant in
[`ownership-model-spec.md`](ownership-model-spec.md) (callout, §2–§6, §11).

**Invariant this migration must make true and keep true:**
> Identity assertions may determine entity membership. Deed assertions may create typed relationships
> between those entities. No deed relationship may merge entity identities. Any common-control grouping
> must be produced by an explicit, evaluated admissibility rule — never by graph connectivity.

## Measured impact (raw current-edge universe; Phase 0 recomputes on the materialized/post-drop layer)

| | now (identity + deed) | after (identity-only) |
|---|---|---|
| OwnerGroups (≥2) | 6,770 | **6,690** |
| deed-derived fusions | 138 (105 `deed_only` + 33 `deed_bridged`, materialized) | 0 |
| deed relationships between **distinct** resolved entities | — | **323** (become typed `co_grantee_on_deed`) |

`deed_only` groups dissolve into singleton entities linked by a deed relationship; `deed_bridged` groups
fall back to their identity sub-entities. The "loss" is only the automatic "one owner" label — every
deed, party, role, date, and path is retained as a relationship.

## Principles

- **One behavior change, gated by a snapshot.** The invariant is enforced by a single line —
  `owner_groups` clustering over identity edges only. Everything else is additive. That change ships only
  after Phase 0 makes it reversible.
- **Entities before relationships before rules before exposure.** Phases are ordered by dependency.
- **Deny-by-default for consumers.** Unmodified consumers must not treat deed-derived structures as
  identity. Public exposure is gated behind the eval.

## Phases

### Phase 0 — Baseline, legacy snapshot, consumer inventory *(reversible foundation)*
- **Snapshot** the current `:OwnerGroup`/`IN_OWNER_GROUP` layer as a versioned legacy view (tag every
  node with a `legacy_run_id`, or export to a restorable form) so the change is reversible and consumers
  can migrate off it deliberately.
- **Recompute the exact deltas** on the materialized (post-co-op/condo-drop) universe — the table above is
  the raw universe; Phase 0 produces the authoritative materialized numbers and snapshots them.
- **Inventory OwnerGroup consumers** and what each assumes: `aggregator_audit.py` (counts distinct owners
  per address to build the mask), `verify_splink.py` (composition canary + OwnerGroup canaries),
  `eval/` + `case-escobar.md`, and the (future) agent/UI consumption spec. Record expected behavior before
  changing anything.

### Phase 1 — Identity-only OwnerGroup *(the invariant-enforcing change)*
- **`owner_groups._EDGES` → `CONNECTED_BY_SPLINK` only** (drop `CONNECTED_BY_DEED`). This is the change
  that makes "no deed edge in identity union-find" true. Re-materialize.
- **Component-level consistency checks** for probabilistic (`fellegi-sunter`) identity components before a
  connected component is accepted as one entity: name compatibility, entity-type agreement, temporal
  impossibility, conflicting stable identifiers. Split or flag failures. Deterministic `registered-llc` /
  `curated` edges are exempt (same legal entity / human-verified).
- **`verify_splink` canary flips to a regression check:** post-migration `deed_only` = `deed_bridged` = 0;
  any non-zero is now a FAIL (a deed edge re-entered identity), not a WARN.
- Reversible via the Phase 0 snapshot.

### Phase 2 — Stable resolved-entity ids + lineage
- Every `Landlord` maps to a **stable `resolved_entity_id`**: its OwnerGroup id if grouped, else a
  deterministic singleton id. Carries lineage to source references, method, and confidence. Reproducible
  and versioned (property or derived view — decide in this phase).
- This is the addressable **endpoint** for deed relationships (Phase 3) and building projection, so a
  relationship connects two resolved entities, not raw records, and duplicate deed appearances don't look
  like distinct relationships.
- **Specify the party→building projection** here (it is a prerequisite for the eval, per spec §5): whether
  buildings inherit every party relationship, retain overlapping memberships, group by current vs.
  historical claims, propagate through joint ownership, and whether allegations flow through projected
  membership.

### Phase 3 — Deed as a typed relationship (not identity)
- Enrich `CONNECTED_BY_DEED` provenance: **method kept distinct** (`acris-deed` held vs
  `acris-deed-linked-successor`), plus deed ids, dates, grantor/grantee roles, doc type, lot coverage.
- **Source-near naming:** `co_grantee_on_deed` (both roles grantee) / `conveyance_party` (roles retained)
  — never `co-title`, which overstates the record.
- **Expose as typed evidence paths** (spec step 3), **vetted-only**, with **path-admissibility** (which
  edge-type sequences may be shown, max path length, permitted mechanisms, temporal coherence, whether a
  weak identity edge may anchor a path) and **path calibration**. No unified groups, rankings, or
  propagated attributes at this step.

### Phase 4 — Explicit common-control admissibility rule (`linked-successor` first)
- Introduce an **explicit, evaluated rule** that consumes `acris-deed-linked-successor` relationships (with
  their single-purpose-successor + restructuring + temporal gates) to *propose* a common-control grouping
  — materialized **separately** (e.g. a `:ControlGroup` candidate or a flagged relationship), **never by
  connectivity**. Held-deed co-conveyance stays a relationship/path unless a rule qualifies it.
- Each rule specifies: input claim types, required roles, temporal constraints, exclusions, conclusion
  type + scope, confidence/calibration source, and allowed consequence tiers. Gated behind the eval.

### Phase 5 — Consumer contract (deny-by-default) + retire legacy
- **Consumer semantics:** identity `OwnerGroup` = resolved owner (safe to present); deed
  relationships/paths = typed, vetted; common-control candidates = post-eval, public only after
  admissibility. `composition`/entity-type is **deny-by-default**.
- **Migrate internal consumers:** re-validate the `aggregator_audit` mask against identity-only owner
  counts (the 73-address list may shift); update `verify_splink` (regression checks); recompute the
  eval/case-study numbers; the agent/UI consumption spec surfaces **paths, not named groups**, pre-eval
  (reconcile with the caveat already in [`ownership-layer-decision.md`](ownership-layer-decision.md) §M5).
- **Retire the legacy snapshot** once consumers have migrated.

## Sequencing, reversibility, risk

- **Order:** 0 → 1 → 2 → 3 → 4 → 5. Phase 1 depends on the Phase 0 snapshot; relationships (3) need
  entities (2); rules (4) need typed relationships (3); public exposure (5) is gated by the eval.
- **Reversibility:** Phase 1 is the only behavior change and is restorable from Phase 0. Phases 2–5 are
  additive.
- **Risks to measure, not assume:** the `aggregator_audit` owner-count shift (re-validate the mask);
  how many `fellegi-sunter` components the consistency checks split (Phase 1); and the recall *perception*
  change (deed-only owners no longer auto-present as one owner — expected and documented, not a defect).

## Validation gates

1. **Post-Phase-1:** `verify_splink` reports `deed_bridged` = `deed_only` = 0 (invariant holds).
2. **Before public exposure (Phase 5):** the [`eval-protocol.md`](eval-protocol.md) ablation shows the
   deed-relationship + rule layer adds value **beyond** identity + sourced records, and the preregistered
   decision rules (§8) clear the relevant consequence tier.
3. **Ongoing:** the regression canary keeps identity union-find deed-free.

## Open decisions (settle during the phase, flagged here)

- Phase 2: `resolved_entity_id` as a stored property vs. a reproducible derived view.
- Phase 4: the `:ControlGroup` candidate shape (node vs. flagged relationship) and the first rule's exact
  conclusion type/scope.
- Phase 5: whether the legacy view is retained read-only for a fixed window or exported and deleted.
