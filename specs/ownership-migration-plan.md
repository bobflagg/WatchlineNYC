# Option B migration plan (v4) — parallel construction, then cutover

**Date:** 2026-09-07 · **Status:** direction approved; **Phase 0–1 execution-ready**, Phases 2–5 executable
once Phase 1's identity contracts, the component-consistency algorithm, and the Phase-5 thresholds are
approved · **Implements:** the Option B decision + invariant in
[`ownership-model-spec.md`](ownership-model-spec.md).

**Invariant to make — and keep — true** (generalized beyond deeds, per review):
> Identity assertions may determine entity membership. **No substantive relationship assertion may
> participate in entity resolution.** Substantive relationships (e.g. deeds) hold *between* resolved
> entities. Any common-control grouping must be produced by an explicit, evaluated admissibility rule —
> never by graph connectivity.

**Two tracks.** *Track A* (Phases 0–5) is the identity/relationship separation and cutover — a correctness
fix with **no public exposure**. **Phases 0–1 are execution-ready now; Phases 2–5 unlock once Phase 1 is
approved** (the component-consistency algorithm determines entity membership, so it is *designed, reviewed,
and tested as a Phase-1 contract deliverable — before any Phase-2 implementation*, not "specified while
constructing"). *Track B* (Phases 6–8) exposes deed paths and draws control conclusions — separate risk
transitions, gated by the eval; **deferred**. Don't block Track A on Track B.

**Right-sizing.** Pre-production prototype: `OwnerGroup` has ~4 *internal* consumers (`aggregator_audit`,
`verify_splink`, `eval/`, `case-escobar`), no serving/caches/indexes/API/external users. The durable,
cheap-now pieces (parallel model, versioned IDs, event-centric deeds, invariant test) are built now; the
heavyweight serving ceremony (feature-flag/shadow serving, observation windows, cache/index migration)
scales up at production exposure, which Track B gates.

## Transition matrix — *deed-removal only* (materialized layer, 6,540 groups, snapshot 2026-09-07)

Effect of removing deed edges from identity union-find **alone**; the Phase-2 consistency algorithm may
change it further. Row classes are *not* mutually-exclusive evidence types — an `identity` group can also
contain deed evidence (hence its 78 shed singletons / 83 relationships).

| legacy composition | count | → identity groups ≥2 | → singletons | → entity-pair deed rels |
|---|---:|---:|---:|---:|
| `identity` | 6,402 | 6,402 | 78 | 83 |
| `deed_only` | 105 | 0 | 234 | 159 |
| `deed_bridged` | 33 | 70 | 10 | 60 |
| **total** | 6,540 | **6,472** | **322** | **302** |

Phase 0 emits the **conservation totals** that make this auditable: source party-references and unique
source nodes before/after; deed events; eligible deed role-assertions; distinct resolved-entity pairs;
self-pairs removed (both refs resolve to one entity); rows excluded + reason; and legacy deed edges with
**no** corresponding conveyance event (must be 0).

## Identity model — three distinct objects (decide in Phase 1)

- **`source_reference_id`** — an immutable source occurrence (a named party in a record).
- **`resolution_id`** (a.k.a. `entity_version_id`) — the membership result of a *particular* model +
  threshold + data snapshot. Probabilistic components merge/split, so this is run-scoped.
- **`entity_id`** — a *durable* canonical identity, assigned only where continuity is established (not
  every resolution component earns one immediately).

Relationships record **which `resolution_id` supported their endpoints**. Invariant: *historical
conclusions retain the entity-resolution version under which they were generated, even after later merges
or splits.* (Decide before Phase 3, so re-resolution can't silently reinterpret old relationships.)

## Rollback = version selection **at a common source watermark**

Choose a prior **version** (run-id / read-alias), not a snapshot restore. But version-selection only
isolates *semantics* if both projections sit on the **same source watermark** — otherwise reverting to
legacy also reverts data freshness, conflating two changes. So during the rollback window:

```
source watermark N
├── legacy semantics  (run L-N)
└── v2 semantics      (run V2-N)
```

The switch chooses semantics at a common N; a test verifies **source-coverage parity** between the two
runs. *(Cheap here: the graph is batch-rebuilt from one Postgres snapshot per run, so building L-N and V2-N
from the same dump satisfies this by construction — no dual continuous-ingestion pipeline needed.)*
Rollback unit: source watermark · code rev · config/thresholds · run-ids · schemas & indexes · derived
datasets (masks, fixtures) · cache/index version · consumer-contract version.

---

## Track A — identity/relationship separation & cutover (execution-ready)

### Phase 0 — Inventory & reproducible baseline
Snapshot data/code/config/masks/watermark/outputs; produce the transition matrix + conservation totals.
**Full consumer inventory** (not just the named scripts): graph queries, serializers, jobs,
reports/notebooks, export schemas, caches/indexes, UI assumptions, eval fixtures, dashboards, docs/prompts,
external consumers. Per consumer: concept needed (**identity vs. association vs. control**), current query,
replacement query, acceptable changes, owner, status, rollback behavior.

### Phase 1 — Contracts & schemas (no behavior change)
Define: source-reference claims; the **three IDs** above + merge/split lineage (events,
predecessor/successor, alias/redirect, survivor rule, ambiguous-split → new IDs); the **conveyance-event**
representation (Phase 3); the party→building **projection**; the **identity provenance allowlist**; the
read contracts consumers will target. The **allowlist is by provenance + assertion type** — exact
jurisdictional legal-entity id; curated same-entity adjudication; an approved probabilistic same-reference
mechanism+version — and the materializer **rejects unknown mechanisms** rather than trusting the
`CONNECTED_BY_SPLINK` relationship type.

### Phase 2 — Parallel identity model (`ResolvedEntityV2`), alongside legacy
- Build identity components from **allowlisted identity assertions only**, as a *new* projection;
  **legacy `OwnerGroup` untouched**.
- **Component-consistency is its own algorithm** (specify: deterministic split when one edge is suspect;
  edge ranking; behavior when a removal admits several partitions; whether a flag blocks single-entity use
  or annotates; re-checking direct matches as a component grows; contradictory identifiers; cross-time
  identity for people vs. LLCs vs. renamed/reused names). Exemptions weakened: `curated` is
  auditable/privileged but **not exempt** from contradictions; `registered-llc` is deterministic **only**
  with identifier **and jurisdiction** (a normalized name is not a stable id — join to the DOS entity id
  where possible).

### Phase 3 — Parallel relationship model (conveyance-event-centric)
- **Canonical form is the event, which already exists:** `(:Building)-[:HAS_EVENT]->(:Event
  {event_type:'DeedTransfer'})<-[:PARTY_TO {role}]-(:Actor)`. Keep the source's native property reference on the
  event; the property unit here **is the BBL** (a tax lot) and `Building` is BBL-keyed, so no separate
  parcel node — the residual (multiple BINs under one BBL) is a **documented limitation**, revisited only
  if an inference rule needs sub-BBL lot coverage.
- `co_grantee_on_deed` / `conveyance_party` between **resolved entities** (with `resolution_id`) is a
  **derived view** over the events, provenance back to the conveyance — never canonical, never `co-title`.
- **Reconciliation = complete event-and-role conservation, not one-per-group.** Every eligible legacy
  deed-derived edge/event contributing to the 138 affected groups maps to its originating deed event; every
  source party+role, property/lot association, and contributing event is preserved; every derived pair
  points back to *all* contributing events and none appears without one; dedup differences are accounted
  for. Use an **anti-join completeness report**, not group-level counts.

### Phase 4 — Offline validation (no user exposure)
Structural + identity + evidence-preservation checks against legacy and v2 (below). **Migrate internal
machine consumers** individually; re-validate the **`aggregator_audit` mask** against identity-only owner
counts. Make the dependency a **fixed, versioned DAG** — `source claims → identity assertions →
ResolvedEntityV2 → address statistics → mask version → registration-network version` — with the mask a
**frozen input generated from a declared upstream run** (no convergence proof; break any cycle by freezing).

### Phase 5 — Semantic cutover (identity reads only)
Switch canonical identity reads to v2 behind a version switch (light now — a run-id alias). **Acceptance
criteria** (this is the identity fix; the public control-eval is *not* required for it): complete evidence
reconciliation; **zero prohibited edge mechanisms** in identity components; all known consumers migrated;
all output differences either explained by the transition matrix or recorded as intentional; **no
unexplained source-reference loss**; stable-ID merge/split tests pass; **identity-resolution quality clears
the preregistered thresholds** in [`eval-protocol.md`](eval-protocol.md) §8.1 (fixed *before* Phase 2
results are examined); rollback switch exercised; no severity-1 discrepancies open. This cutover is
**separate** from any later public exposure of deed paths or control conclusions.

---

## Track B — inference & exposure (deferred; gated by the eval)

### Phase 6 — Bounded control conclusions (not groups)
A rule emits a **versioned, scoped conclusion** — subject entities, property/lot scope, valid interval,
evidence, rule+version, confidence/adjudication state, consequence-tier permissions — e.g. *"A and B are
candidates for continuity of control over S during T, based on E."* `linked-successor` is the first
candidate. **No transitive group closure**, and the first rule does **not** decide whether to create a
`ControlGroup`; a group is formed only if a separate group-level rule evaluates the whole membership. Defer
the group representation (node vs. flagged relationship) until there's experience with conclusions.

### Phase 7 — Research-user path exposure (bounded pilot)
Expose deed **evidence paths** to `vetted` users under **path-admissibility** (allowed edge-type sequences,
max length, mechanisms, temporal coherence, weak-identity anchoring). "Vetted" is the audience, not the
path's epistemic quality. **Path calibration must come from an offline labeled evaluation**; if it is
instead learned in the pilot, run the first exposure as a **bounded calibration study** with logging,
access controls, and stopping rules. Then evaluate user interpretation / downstream use before wider
exposure.

### Phase 8 — Legacy serving retirement
Stop **serving** legacy after the observation window, **retaining** the versioned artifact. Requires: all
consumers moved; no legacy reads over the window; reconciliation within bounds; rollback exercised; IDs /
redirects verified; caches/indexes & fixtures migrated; docs updated; no open severity-1 discrepancies;
retention policy approved.

## Validation gates (structural, not symptomatic)

The old `deed_only = deed_bridged = 0` canary is too weak (passes if classification stops). Assert directly:
every identity-union edge carries an **allowlisted identity mechanism**; no substantive-relationship
assertion appears in identity-component provenance; every deed-relationship endpoint resolves to an
`resolution_id`; the anti-join evidence-conservation report is clean; and the **property test** (narrowed):
> *Holding source references and identity assertions constant, adding, removing, or modifying any
> substantive relationship assertion cannot change identity-component membership.*
Plus a **dependency test** enumerating exactly which deed-derived fields (if any) are permitted to generate
identity assertions — so a future change can't relabel deed connectivity as an identity feature and pass.

## Open decisions (settle in-phase)

- Phase 1: `entity_id` continuity rules; whether `resolution_id`/lineage is a property or a derived view.
- Phase 3: the derived pairwise view's shape + storage + provenance link (the **event is already decided
  canonical**).
- Phase 6: the first rule's conclusion type/scope; group-level rule (if any); group representation.
- Phase 8: legacy retention window; serving-vs-artifact policy.
