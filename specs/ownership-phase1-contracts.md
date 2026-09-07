# Option B migration — Phase 1 contracts (rev 3, for re-review)

**Date:** 2026-09-07 · **Status:** contracts, **for re-review before any Phase-2 implementation** · **Plan:**
[`ownership-migration-plan.md`](ownership-migration-plan.md) · **Baseline:**
[`ownership-phase0-baseline.md`](ownership-phase0-baseline.md).

`[DECISION]` = confirm; `[OPEN]` = deferred w/ default; `[RATIFY]` = a concrete value proposed here for the
team to fix at sign-off. Nothing implemented. Invariant:
> Identity membership comes only from allowlisted identity assertions. **No substantive relationship
> assertion may participate in entity resolution.** Common-control grouping only from an explicit,
> evaluated admissibility rule.

### rev 2 → rev 3 (four re-review blockers)
1. **C7 thresholds:** checklist no longer claims them "fixed"; concrete **`[RATIFY]` values proposed** in
   [`eval-protocol.md`](eval-protocol.md) §8.1, frozen at sign-off, with the run manifest **pinning the
   protocol revision hash**. *(I propose values; the team ratifies acceptable-harm numbers — not mine to
   set unilaterally.)*
2. **`registered-llc` split** into deterministic `registered-llc-id` (identifier+jurisdiction) vs.
   probabilistic `registered-llc-name` (normalized-name hypothesis); today's edges are name-only (C2/C3).
3. **The base `(name,address)` dedup is now a governed Level-0 identity transformation** (C0), not a
   silent pre-step — versioned, collision-detecting, durable-id-blocking, and in the eval.
4. **Durable-core continuity** redefined by **core overlap** (grow/merge/split/conflict), not "unchanged"
   (C1).

## C0 — Base normalization is a governed identity transformation

The `party_reference` grain collapses source rows sharing a normalized `(name, biz-address)` into one WoW
`landlords_with_connections` node. That **is** an identity decision made before the allowlist, so it is
governed as **Level-0 identity resolution**, not treated as neutral provenance:
- `[DECISION]` it is **versioned** (normalization-version stamped) and **evaluated as part of the identity
  pipeline** (its own precision on same-key-different-party collisions);
- `[DECISION]` enough **row-level info is retained** (the contributing `(registrationid, bbl, role, date)`
  rows, plus any identifiers/entity-type) to **detect collisions** at a `party_reference`;
- `[DECISION]` a **durable `entity_id` is blocked** for any `party_reference` whose contributing rows carry
  **incompatible identifiers or entity types** (a suspected Level-0 collision);
- `[DECISION]` **same-name/same-address collision cases are included in the cutover evaluation** (§8.1).
- `[OPEN]` **Out of scope for this migration:** splitting to finer per-occurrence source references (a WoW
  ingestion-grain change). Recorded as an inherited limitation; the governance above bounds its risk.

## C1 — Levels & IDs

| Object | ID | Grain | Stability |
|---|---|---|---|
| **Party reference** | `party_reference_id` | normalized `(name, biz-address)` party (Level-0, C0) | stable **within a normalization version**; a version bump is a lifecycle event w/ predecessor/successor lineage — **not** the rebuild-unstable `nodeid` |
| **Resolution component** | `resolution_id` | one identity component in a run (model+threshold+snapshot) | run-scoped; **always present**; universal consumer key |
| **Durable entity** | `entity_id` | canonical identity where continuity holds | **optional**; immutable once assigned; carries lineage |

- `[DECISION]` `party_reference_id` derives from the stable normalized key (or a persisted app id), keeps
  lineage to its source rows (C0), and is **stable only within a normalization version**; a normalization
  change emits party-reference predecessor/successor lineage (same machinery as entity merges/splits).
- `[DECISION]` `resolution_id` is the **universal run-scoped key** (always present, incl. singletons);
  `entity_id` is **optional** durable metadata. Relationships/conclusions reference `resolution_id`+`run_id`.
- **Durable-core continuity (C1, revised):** an `entity_id`'s **deterministic core** = its members linked by
  **deterministic** methods (`curated-same-owner`, `registered-llc-id`). Cross-run continuity is decided by
  **core overlap**, not equality:
  - core **gains** references (e.g. a newly discovered deterministic alias) → **carry** the same `entity_id`;
  - two prior cores **merge** → survivor = larger core (tie → lower id), others redirect;
  - one core **splits** → **all-new** `entity_id`s + redirects (no arbitrary survival);
  - **conflicting** claims about one durable entity → adjudication (no silent pick).
  Probabilistic-only components get a `resolution_id` and **no** `entity_id` until a deterministic core (or a
  curator) establishes one.
- `[OPEN]` physical form; default: `resolution_id`+`run_id` on the membership edge, lineage in a side table.

## C2 — Identity provenance allowlist (fail-closed)

| Method | Class | Admit | Note |
|---|---|---|---|
| `curated-same-owner` | deterministic | ✅ | auditable/privileged, not exempt from C3 hard constraints |
| `registered-llc-id` | deterministic | ✅ | identifier **+ jurisdiction** (e.g. DOS entity id); establishes durable core |
| `registered-llc-name` | **probabilistic** | ✅ | normalized-name hypothesis (**today's `registered-llc` is this**); high-precision but **cannot** establish a durable core, sits in the probabilistic conflict path |
| `splink-fellegi-sunter` (pinned) | probabilistic | ✅ | same-*reference* hypothesis |
| `acris-deed`, `acris-deed-linked-successor` | relationship | ❌ | never in resolution |
| unknown | — | ❌ | build fails loudly |

`[DECISION]` Migrate `llc_edges` to emit **`registered-llc-name`** now (it is name-only); `registered-llc-id`
activates with the `[OPEN]` DOS-entity-id join. One method name never covers both deterministic and weak.

## C3 — Component resolution: deterministic constrained clustering

Constrained clustering (hard *cannot-link* / soft *should-link*), realized as **constrained union-find over
a canonical edge order** — a global optimizer is unnecessary (components max 37; determinism + constraint
satisfaction, not optimality, is required).

**Soft should-link** = allowlisted identity edges, **precedence** `curated-same-owner (3) >
registered-llc-id (2.5) > registered-llc-name (1.5) > splink-fellegi-sunter (1)`; within a tier by score.
`cluster_gated` pre-vetoes still drop first-name / common-name+address edges.
**Deterministic methods = {`curated-same-owner`, `registered-llc-id`} only.**

**Hard cannot-link** (per-reference attributes): entity-type mismatch (person/entity/institution);
surname disagreement (persons); conflicting stable identifiers.

**Procedure (total, deterministic, permutation-invariant):**
1. **Canonicalize** edges: precedence desc, score desc, `(min id, max id)` — so the result is independent
   of input order.
2. **Constrained union-find:** union endpoints iff the merged set has **no** cannot-link pair; else **skip**
   the edge (recorded) — the partition is the union-find result, a real partition.
3. **Irreconcilable *deterministic* conflict:** a skipped **deterministic** edge (`curated` /
   `registered-llc-id`) → components stay separate **and** the conflict goes to an **adjudication queue**
   (not silently dropped). A skipped **probabilistic** edge (`registered-llc-name`, `fellegi-sunter`) is
   just dropped with provenance.
4. **Output:** every reference gets a `resolution_id`; singletons included.

**Tests before build:** permutation invariance (shuffled input ⇒ identical partition + adjudication set);
each constraint type; a deterministic-conflict case; and that adding/removing any `acris-deed` edge changes
nothing.

## C4 — Conveyance-event representation (Phase-3 target)

Canonical already exists: `(:Building)-[:HAS_EVENT]->(:Event {event_type:'DeedTransfer', source_name:'ACRIS',
event_id, source_record_id, event_date})<-[:PARTY_TO {role}]-(:Actor)`. `co_grantee_on_deed` /
`conveyance_party` between resolved components (`resolution_id`, deduped) is a **derived view** w/
contributing `event_id`s, roles, dates, method (held vs linked-successor, distinct). Never `co-title`.
`[DECISION]` event canonical; `[OPEN]` derived-view storage (default: materialized edge w/ provenance).
BBL is the property unit (multi-BIN-per-BBL = documented limitation).

## C5 — Party → building projection (source-qualified, no "current")

**No single "current owner"** until temporal+successor rules exist. **Source-typed latest-observed claims**,
each carrying `source_type · effective/record date · rule_version · resolution run`: `[DECISION]`
latest-observed **HPD** association; `[DECISION]` latest-observed **deed-derived** association under a named
rule; `[DECISION]` **`unknown-current`** when succession isn't established. `[DECISION]` a building **may
associate to multiple components** (joint ownership; never a node merge). `[DECISION]`
**allegations/violations do not propagate** across inferred membership (deny-by-default). Rental-only. A
stale `bbl` yields a **dated** latest-observed claim, not a current one.

## C6 — Consumer read contracts (deny-by-default)

| Consumer | Needs | Target read | Note |
|---|---|---|---|
| `aggregator_audit` | distinct owners **within one run** | count distinct **`resolution_id`** per address (incl. singletons) | mask = frozen versioned input (C8); re-validate 73 addrs |
| `verify_splink` | invariant + canaries | over v2; `composition` canary → **C3 invariant regression test** | update at cutover |
| `eval/sample` | stable strata | strata over **`resolution_id`** (+ `entity_id` where cross-run durability wanted) | fixture version bump; re-freeze |
| (future) agent/UI | identity + paths | components; deed **paths** only (vetted); no named control groups pre-eval | §M5 |

`[DECISION]` No consumer requires durable `entity_id`; `resolution_id` within a declared run suffices.

## C7 — Acceptance thresholds

Phase-5 cutover gated by [`eval-protocol.md`](eval-protocol.md) **§8.1**. rev 3 adds **`[RATIFY]` proposed
concrete values** there; they are **frozen at sign-off, before any Phase-2 results are seen**, and the
**run manifest pins the §8.1 protocol revision hash** so the adopted numbers cannot change silently. The
checklist below reflects that these are proposed-pending-ratification, not yet fixed.

## C8 — Synchronized legacy/v2 build

Throughout the rollback window: `[DECISION]` legacy + v2 built from the **same source watermark** (one run,
one snapshot); both **rebuildable as ingestion advances**; a **source-coverage parity test**; the version
selector **records semantic version + watermark** (rollback reverts semantics only, not freshness).

## Sign-off checklist

- [ ] C0 — Level-0 `(name,address)` collapse governed (versioned, collision-detecting, durable-id-blocking, in eval).
- [ ] C1 — `resolution_id` universal; `entity_id` optional; `party_reference` stable-within-normalization + lineage; **core-overlap continuity**.
- [ ] C2 — allowlist with **`registered-llc-id` vs `registered-llc-name`** split.
- [ ] C3 — constrained-clustering procedure + **permutation-invariance test written**.
- [ ] C4 — event-centric deeds + derived-view shape.
- [ ] C5 — source-qualified latest-observed projection; multi-membership; no propagation.
- [ ] C6 — consumers keyed on `resolution_id`; deny-by-default.
- [ ] C7 — **§8.1 `[RATIFY]` values frozen + protocol hash pinned** (not merely referenced).
- [ ] C8 — synchronized legacy/v2 build + parity.

On sign-off, Phases 2–5 unlock against the untouched legacy layer, reversible by version selection.
