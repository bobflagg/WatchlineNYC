# Option B migration — Phase 1 contracts (rev 2, for re-review)

**Date:** 2026-09-07 · **Status:** contracts, **for re-review before any Phase-2 implementation** · **Plan:**
[`ownership-migration-plan.md`](ownership-migration-plan.md) · **Baseline:**
[`ownership-phase0-baseline.md`](ownership-phase0-baseline.md).

`[DECISION]` = a choice to confirm; `[OPEN]` = deferred with a stated default. Nothing here is implemented.
Invariant they uphold:
> Identity assertions may determine entity membership. **No substantive relationship assertion may
> participate in entity resolution.** Any common-control grouping comes only from an explicit, evaluated
> admissibility rule.

### rev 1 → rev 2 (all five re-review blockers)
1. **`resolution_id` is the universal run-scoped consumer key; `entity_id` is optional durable metadata**
   (C1, C6) — fixes the "consumers need an id many components won't have" contradiction.
2. **Renamed `source_reference` → `party_reference`** with an honest, stable, non-nodeid key + lineage back
   to source rows (C1) — it is a normalized party, not an immutable occurrence.
3. **Component resolution fully specified** as deterministic **constrained union-find** with hard/soft
   constraints + permutation-invariance test (C3).
4. **No "current" projection** — source-qualified **latest-observed** claims only (C5).
5. **Synchronized legacy/v2 build contract at a common watermark** added (C8).

## C1 — Levels & IDs

| Object | ID | Grain | Mutability / stability |
|---|---|---|---|
| **Party reference** | `party_reference_id` | a normalized landlord party = WoW `landlords_with_connections` node (a `(name, biz-address)` HPD dedup) | **not an occurrence**; id is a **stable hash of the normalized `(name, biz_address)`** (normalization-version stamped), **not** the rebuild-unstable `nodeid` |
| **Resolution component** | `resolution_id` | one identity component in a specific run (model+threshold+snapshot) | run-scoped; **always present**; the universal consumer key |
| **Durable entity** | `entity_id` | canonical owner identity where continuity is established | **optional** continuity metadata; immutable once assigned |

- `[DECISION]` **`party_reference` is a normalized party, not a source occurrence.** Raw per-row references
  are out of scope, so we do **not** claim occurrence-level provenance. Its id derives from the stable
  normalized key (or a persisted app id), never `nodeid` (which `landlords_with_connections` regenerates
  each rebuild — `nodeid` stays only as a within-run join handle). **Lineage is retained:** every
  `party_reference` keeps edges to its contributing source rows `(registrationid, bbl, role, date)` so an
  identity assertion can be traced to the records that supported it and corrections are possible.
- `[DECISION]` **`resolution_id` is the universal run-scoped identity key.** Consumers needing distinct
  resolved parties *within a declared run* use it (always present, incl. singletons). **`entity_id` is
  optional** — assigned/carried only where continuity holds (deterministic-core unchanged: members linked
  by `curated`/`registered-llc`); probabilistic-only components have a `resolution_id` and no `entity_id`.
  Relationships/conclusions reference `resolution_id` + `run_id`; those needing cross-run durability
  additionally reference `entity_id` when present.
- Invariant: *a historical conclusion retains the `resolution_id`/`run_id` it was generated under.*
- **Lifecycle** (`entity_id` only): `merge`/`split`/`carry` events with predecessor/successor ids, `run_id`,
  trigger, and redirects. `[DECISION]` merge survivor = the entity whose deterministic core is largest
  (tie → lower id); **ambiguous split → all-new ids** + redirects.
- `[OPEN]` physical form (properties vs. side table); default: `resolution_id`+`run_id` on the membership
  edge, `entity_id` lineage in a side table.

## C2 — Identity provenance allowlist (fail-closed)

Materializer admits an edge into resolution only if `method` is allowlisted; **unknown methods are
rejected** (the `CONNECTED_BY_SPLINK` type is not the boundary).

| Method | Admit | Note |
|---|---|---|
| `curated-same-owner` | ✅ | auditable/privileged, **not exempt** from C3 hard constraints |
| `registered-llc` | ✅ (qualified) | deterministic same-entity only with **identifier + jurisdiction**; normalized name alone is weak → `[OPEN]` join to DOS entity-id; until then subject to C3 |
| `splink-fellegi-sunter` (pinned version) | ✅ | probabilistic same-*reference* |
| `acris-deed`, `acris-deed-linked-successor` | ❌ | **relationship — never in resolution** |
| unknown | ❌ | build fails loudly |

## C3 — Component resolution: deterministic constrained clustering

Formulated as **constrained clustering** — hard *cannot-link* constraints and soft *should-link* edges —
realized as **constrained union-find over a canonical edge order** (a global optimizer is unnecessary:
components are tiny, max 37; determinism + constraint-satisfaction, not optimality, is what's required).

**Soft should-link** = allowlisted identity edges, each with a **precedence weight**
`curated-same-owner (3) > registered-llc (2) > splink-fellegi-sunter (1)`; within a tier, by edge score.
Existing pre-vetoes (`cluster_gated`: first-name, common-name+address) drop bad edges up front.

**Hard cannot-link** between two party references (from per-reference attributes, not edges):
- **entity-type mismatch** — natural person ✗ legal entity ✗ institution/nonprofit (type from
  `firstname/lastname` vs `corporationname` + the institutional/HDFC list);
- **surname disagreement** for two person references;
- **conflicting stable identifiers** (e.g. different DOS entity ids), when present.

**Procedure (total, deterministic, permutation-invariant):**
1. **Canonicalize** the edge list to a fixed total order: precedence weight desc, then score desc, then
   `(min(id), max(id))`. *(Sorting first is what makes the result independent of input order.)*
2. **Constrained union-find:** walk edges in that order; union the endpoints' components **iff** the merged
   set contains **no** cannot-link pair. An edge whose union would violate a constraint is **skipped**
   (dropped, with provenance) — so the component naturally splits where a constraint forbids joining, and
   the output **is a real partition**, not a flag over a still-connected blob.
3. **Irreconcilable deterministic conflict:** if the skipped edge is a **deterministic** one
   (`curated`/`registered-llc`) — i.e. two high-trust assertions imply a merge a hard constraint forbids —
   it is **not** silently dropped: both references keep their (separate) components **and** the conflict is
   emitted to an **adjudication queue** (curated is auditable, not infallible; a `registered-llc` conflict
   usually means the name-only match was wrong — the C2 `[OPEN]` DOS-id upgrade resolves these).
4. **Output:** every party reference gets a `resolution_id`; singletons are their own component. No
   separate "flag then fall back" step — the partition is the constrained-union-find result; flags attach
   only to references in a step-3 adjudication conflict.

**Tests (before Phase-2 build):** the pure procedure is unit-tested, including **permutation invariance**
— shuffling the input edge order yields an identical partition and identical adjudication set — plus each
constraint type, a deterministic-conflict case, and the property that adding/removing any `acris-deed`
edge changes nothing (it never enters this procedure).

## C4 — Conveyance-event representation (Phase-3 target)

Canonical form already exists: `(:Building)-[:HAS_EVENT]->(:Event {event_type:'DeedTransfer',
source_name:'ACRIS', event_id, source_record_id, event_date})<-[:PARTY_TO {role}]-(:Actor)`.
`co_grantee_on_deed` / `conveyance_party` between **resolved components** (`resolution_id` endpoints,
deduped) is a **derived view** carrying contributing `event_id`s, roles, dates, and method (`acris-deed`
held vs `acris-deed-linked-successor`, kept distinct). Never `co-title`. `[DECISION]` event is canonical;
`[OPEN]` derived-view storage shape (default: materialized edge with provenance). BBL is the property unit
(multi-BIN-per-BBL = documented limitation).

## C5 — Party → building projection (source-qualified, no "current")

**No single "current owner" projection** until temporal + successor rules exist. Instead, **source-typed,
qualified latest-observed claims**, each carrying `source_type · effective/record date · rule_version ·
resolution run`:
- `[DECISION]` **latest-observed HPD association** (as of its source date);
- `[DECISION]` **latest-observed deed-derived association** under a named rule;
- `[DECISION]` **`unknown-current`** when succession cannot be established.

`[DECISION]` A building **may associate to multiple components** (joint ownership) — multiple associations,
never a node merge. `[DECISION]` **allegations/violations do not propagate** across inferred membership
(deny-by-default); events stay on the building. Rental-only (co-op/condo excluded). Do **not** project
through undifferentiated `bbls` as if current — a stale `bbl` yields a dated `latest-observed` claim, not a
current one.

## C6 — Consumer read contracts (deny-by-default)

Default reads see identity components (`resolution_id`) only; opt-in required for deed relationships/paths
or control conclusions.

| Consumer | Needs | Target read | Note |
|---|---|---|---|
| `aggregator_audit` | distinct owners **within one run** | count distinct **`resolution_id`** per address (incl. singletons) — **not** `entity_id` | mask = frozen versioned input (C8 / Phase-4 DAG); re-validate the 73 addresses |
| `verify_splink` | invariant + canaries | over v2; the `composition` canary becomes the **C3 invariant regression test** | update at cutover |
| `eval/sample` | stable strata | strata over **`resolution_id`** (+ `entity_id` where durable cross-run identity is wanted) | fixture version bump; re-freeze |
| (future) agent/UI | identity + paths | components; deed **paths** only (vetted); no named control groups pre-eval | [`ownership-layer-decision.md`](ownership-layer-decision.md) §M5 |

`[DECISION]` No consumer requires a durable `entity_id`; `resolution_id` within a declared run suffices for
all three. Cross-run durability is used only if/when a feature needs to track an owner across rebuilds.

## C7 — Acceptance thresholds

Phase-5 cutover gated by the preregistered thresholds in [`eval-protocol.md`](eval-protocol.md) §8.1
(fixed before Phase-2 results are seen). Adopted by reference.

## C8 — Synchronized legacy/v2 build contract

Throughout the rollback window:
- `[DECISION]` legacy and v2 projections are **produced from the same source watermark** (both built in one
  run from one Postgres snapshot — cheap here, no dual ingestion);
- both remain **rebuildable as ingestion advances** (a later watermark yields a new L-N / V2-N pair);
- a test checks **source-coverage parity** between the paired runs;
- the **version selector records both the semantic version and the watermark**, so selecting legacy reverts
  *semantics only*, never data freshness.

## Sign-off checklist

- [ ] C1 — `resolution_id` universal key; `entity_id` optional; `party_reference` stable-keyed + lineage.
- [ ] C2 — allowlist + `registered-llc` identifier/jurisdiction stance.
- [ ] C3 — constrained-clustering procedure + **permutation-invariance test written**.
- [ ] C4 — event-centric deeds + derived-view shape.
- [ ] C5 — source-qualified latest-observed projection (no "current"); multi-membership; no propagation.
- [ ] C6 — consumers keyed on `resolution_id`; deny-by-default.
- [ ] C7 — §8.1 numeric thresholds fixed.
- [ ] C8 — synchronized legacy/v2 build + parity test.

On sign-off, Phases 2–5 unlock against the untouched legacy layer, reversible by version selection.
