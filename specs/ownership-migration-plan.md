# Option B migration plan (v2) — parallel construction, then cutover

**Date:** 2026-09-07 · **Status:** plan, revised after review · **Implements:** the Option B decision +
invariant in [`ownership-model-spec.md`](ownership-model-spec.md).

**Invariant to make — and keep — true:**
> Identity assertions may determine entity membership. Deed assertions may create typed relationships
> between those entities. No deed relationship may merge entity identities. Any common-control grouping
> must be produced by an explicit, evaluated admissibility rule — never by graph connectivity.

**v1 → v2 (why this was rewritten).** v1 made the invariant-enforcing edit (`owner_groups` clustering
over identity edges only) an **early breaking change** to the canonical `OwnerGroup`. A snapshot makes old
data recoverable; it does not make that cutover reversible. v2 uses **parallel construction → shadow
validation → consumer migration → cutover**, with rollback as *version selection*, not snapshot restore.

**Scope note (right-sizing).** This is a **pre-production** prototype: `OwnerGroup` has ~4 *internal*
consumers (`aggregator_audit`, `verify_splink`, `eval/`, `case-escobar`), no public serving, no caches /
search indexes / API / external consumers. So the parallel model, versioned entity IDs, event-centric
deeds, and the invariant test are built **now** (cheap while nothing serves). The heavyweight cutover
ceremony (feature-flag serving, shadow-serving windows, cache/index migration, external-consumer
migration) is **scoped to before production exposure** — which the staged rollout already defers. The
structure below is the reviewer's; the ceremony is sized to current reality and scales up at exposure.

## Transition matrix (materialized layer, 6,540 groups, snapshot 2026-09-07)

| legacy composition | count | → identity groups ≥2 | → singletons | → entity-pair deed rels |
|---|---:|---:|---:|---:|
| `identity` | 6,402 | 6,402 | 78 | 83 |
| `deed_only` | 105 | 0 | 234 | 159 |
| `deed_bridged` | 33 | 70 | 10 | 60 |
| **total** | 6,540 | **6,472** | **322** | **302** |

So identity-only yields **6,472** groups (≥2) + **322** new singleton entities, and the deed fusions
become **302 typed relationships between distinct resolved entities**. *(“Entity-pair deed rels” counts
distinct resolved-entity pairs linked by ≥1 deed — not deeds, not party pairs. A multi-grantee deed is one
event with n role edges, expanded to pairs only in a derived view; see Phase 3.)* Even `identity` groups
shed 78 deed-attached singletons — the migration touches more than the 138 obviously-deed-derived groups.

## Rollback = version selection, not restore

Rollback is choosing a prior **version**, not restoring a snapshot (a static snapshot goes stale as
ingestion continues). Keep both projections live and switch via run-id / read-alias / API-version. The
**rollback unit** is: source-data watermark · code revision · config/thresholds · graph run-ids · schemas
& indexes · derived datasets (masks, eval fixtures) · cache/index version · consumer-contract version.

## Phases

### Phase 0 — Inventory & reproducible baseline
Snapshot data, code, config, masks, source watermark, outputs; produce the transition matrix (above).
**Full consumer inventory** — not just the named scripts: graph queries, serializers, background jobs,
reports/notebooks, export schemas, caches/indexes, UI assumptions, eval fixtures, dashboards, docs/prompts,
external consumers. For each: which concept it needs (**identity vs. association vs. control**), current
query, replacement query, acceptable result changes, owner, migration status, rollback behavior.

### Phase 1 — Contracts & schemas (no behavior change)
Define, before building: source-reference claims; **entity versions + immutable IDs** (see Phase 2);
the **conveyance-event** representation (see Phase 3); lineage; the party→building **projection**;
consequence tiers; and the read contracts consumers will target. Nothing canonical changes yet.

### Phase 2 — Parallel identity model (`ResolvedEntityV2`), alongside legacy
- Build identity components from **identity assertions only** (`CONNECTED_BY_SPLINK`) as a *new* projection
  — **leave the legacy `OwnerGroup` untouched**.
- **Identity lifecycle, not membership-derived IDs.** An entity gets an **immutable ID** with versioned
  revisions; define merge/split **events**, predecessor/successor lineage, alias/redirect for retired IDs,
  which ID survives a merge, new IDs for ambiguous splits, and snapshot-scoped membership. ("Stable ID" and
  "reproducible clustering output" are different requirements.)
- **Component-consistency is its own algorithm, not a validation add-on.** Specify: how a component splits
  when one edge is suspect; determinism; edge ranking before removal; handling when one removal admits
  several partitions; whether a flag *blocks* single-entity use or only annotates; re-checking direct
  matches as a component grows; contradictory stable identifiers; cross-time identity for people vs. LLCs vs.
  renamed/reused names. **Exemptions weakened:** `curated` is auditable/privileged but **not exempt** from
  contradictions (it can be wrong/stale/narrow); `registered-llc` is deterministic **only** when identifier
  **and jurisdiction** establish the same legal entity — a normalized name alone is not a stable identifier
  (join to the DOS entity id where possible).

### Phase 3 — Parallel relationship model (conveyance-event-centric)
- **Canonical form is the event**, which already exists in the graph: `(:Actor)-[:PARTY_TO {role}]->(:Event
  {event_type:'DeedTransfer'})-[:AFFECTS]->(:Building)`. This preserves n-ary conveyances, asymmetric roles,
  document identity, lot coverage, dates, and "repeated co-appearance vs. one transaction."
- `co_grantee_on_deed` / `conveyance_party` between **resolved entities** (Phase 2 endpoints, deduped) is a
  **derived convenience view** over the events, with provenance back to the conveyance — never the
  canonical store, and never `co-title` (which overstates the record).
- **Reconcile:** every legacy deed-derived fusion (the 138) must be represented by ≥1 typed relationship
  over retained evidence; verify completeness, provenance, endpoint stability, and temporal/role semantics.
  *(Storage + reconciliation only — exposure is Phase 4.)*

### Phase 4 — Shadow consumers, evaluation, path exposure
- Run each consumer against **legacy and v2** and compare; migrate them **individually** off legacy.
  Re-validate the **`aggregator_audit` mask** against identity-only owner counts, and make its dependency
  explicit: it uses owner counts to build a mask that shapes `CONNECTED_BY_ADDRESS`/Portfolio — **freeze the
  mask per model version** (or prove convergence) to avoid a feedback loop.
- Expose deed **evidence paths** to research (`vetted`) — *now* separated from storage — under
  **path-admissibility** (allowed edge-type sequences, max length, permitted mechanisms, temporal coherence,
  weak-identity anchoring) and **path calibration**. ("Vetted" is the audience, not the epistemic quality —
  vetted users still misinterpret/publish.)

### Phase 5 — Semantic cutover
Switch canonical reads to v2 behind a **reversible alias / feature flag / API version** (light now — a
run-id switch — heavier before production). Monitor discrepancies and downstream behavior. The one-line
`owner_groups._EDGES` change is the *last* step, or is unnecessary if consumers read the versioned v2
projection directly.

### Phase 6 — Explicit inference rules (bounded conclusions, not groups)
- A rule emits a **bounded, scoped conclusion**, e.g. *"Entity A and Entity B are candidates for continuity
  of control over scope S during interval T, based on evidence E."* `linked-successor` is the first
  candidate (it already encodes single-purpose-successor + restructuring + temporal chain).
- **No transitive group closure.** A `ControlGroup` node is formed only if a **separate group-level rule
  evaluates the whole proposed membership** — never because qualifying pairwise relations happen to connect.
- Each rule states: input claim types, roles, temporal constraints, exclusions, conclusion type + scope,
  confidence/calibration source, allowed consequence tiers. Gated behind the eval.

### Phase 7 — Legacy serving retirement
Stop **serving** legacy after the observation window, **retaining** the versioned artifact for
reproducibility. Retirement requires: all known consumers moved; no legacy reads over the window;
reconciliation within bounds; rollback exercised; new IDs/redirects verified; caches/indexes & eval fixtures
migrated; docs updated; no open high-severity discrepancies; retention policy approved.

## Validation gates (structural, not symptomatic)

The v1 canary (`deed_only = deed_bridged = 0`) is too weak — it passes trivially if the classification
stops being computed. Assert the invariant **directly**, and add a **property-based test**:

- every identity-union edge carries an allowed **identity** mechanism;
- no deed-derived assertion appears in identity-component provenance;
- every deed-relationship endpoint resolves to an **entity version**;
- every legacy deed union is represented by ≥1 typed relationship (Phase 3 reconciliation);
- **property:** *adding, deleting, or modifying any deed relationship cannot change identity-component
  membership* — the invariant, encoded as a test;
- no consumer receives a legacy mixed group through the identity-only contract;
- before public exposure: the [`eval-protocol.md`](eval-protocol.md) ablation shows the deed-relationship +
  rule layer adds value beyond identity + sourced records, and the preregistered decision rules clear the
  relevant consequence tier.

## Open decisions (settle in-phase)

- Phase 2: entity-ID scheme + merge/split lineage representation; property vs. derived-view materialization.
- Phase 3: event-centric canonical vs. the derived pairwise view's exact shape and provenance link.
- Phase 6: the first rule's conclusion type/scope and the group-level rule (if any).
- Phase 7: legacy retention window and serving-vs-artifact policy.
