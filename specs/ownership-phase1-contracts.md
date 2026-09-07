# Option B migration — Phase 1 contracts (rev 7)

**Status: Part A + B1 SIGNED OFF (2026-09-07); Phase 2 in progress. B2 (production) deferred.**

*rev 6 → rev 7 (Phase-2 finding F1/R3): `registered-llc` (name-only) is **removed from identity** — it
links co-officers (distinct people) of one LLC = an owner-association, not same-party identity — and moves
to the C4 relationship layer with deeds. Identity input = `splink-fellegi-sunter` + audited
`curated-same-owner` (+ `registered-llc-id` when a DOS join exists). C3's person/entity-type cannot-links
are **retained** (they correctly rejected the non-identity edges). See `ownership-phase2-findings.md` F1.*

*rev 5 → rev 6 (post-sign-off corrections): loss formula made explicit with deployment weights
`L = 5·w_M·FM_cond + w_S·FS_cond`; production certification **gates each mechanism independently** (no
pooling); CI method is **estimator-specific** (Clopper–Pearson only for unweighted per-mechanism binomial;
survey/bootstrap for weighted pooled; paired bootstrap for the loss diff; finite-population for a census).
Ratified: `T=25`, `δ=0.01`. B2 numbers remain to be ratified before any production/public exposure.*

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
- `[DECISION]` row-level lineage (contributing `(registrationid, bbl, role, date)` rows + any
  identifiers/entity-type) is retained **sufficient to detect available collision *indicators* and estimate
  residual collision *risk*** — **not** to prove two same-name/same-address parties are distinct when the
  source has no discriminating identifier. **Absence of a detected contradiction does not establish same
  identity**, and because C0 has already collapsed the rows, resolution cannot later recover the
  distinction (an inherited irreversibility);
- `[DECISION]` a **durable `entity_id` is blocked** on a **positive contradiction** (incompatible
  identifiers/types among contributing rows); passing these checks **does not make C0 deterministic
  evidence** of same-identity;
- `[DECISION]` the eval reports **both** the detected-collision rate **and** the unresolved-C0 ambiguity
  among multi-row party references (§8.1), and the **severe-error veto applies to C0** (irreversible
  pre-resolution operation).
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

Only assertions meaning **"these two references denote the same real party"** are admitted (F1/R3).

| Method | Class | Admit | Note |
|---|---|---|---|
| `curated-same-owner` | deterministic | ✅ *(audited)* | admit **only** seeds meaning same person/legal entity; a "same-owner / shared-control" seed is a **relationship** (C4). Not exempt from C3 constraints |
| `registered-llc-id` | deterministic | ✅ | same **legal entity** by identifier **+ jurisdiction**, **LLC-reference ↔ LLC-reference only** (never person↔person); durable core; not in the graph yet |
| `splink-fellegi-sunter` (pinned) | probabilistic | ✅ | same-**person** hypothesis |
| **`registered-llc` (name-only)** | **owner-association** | ❌ | links **co-officers (distinct people)** of one LLC — association, **not identity** (F1/R3) → **relationship layer, C4** |
| `acris-deed`, `acris-deed-linked-successor` | relationship | ❌ | never in resolution → C4 |
| unknown | — | ❌ | build fails loudly |

`[DECISION]` (F1/R3) `registered-llc` (name-only) is **removed from identity** → C4; the identity input is
`splink-fellegi-sunter` + audited `curated-same-owner` only. `registered-llc-id` activates with the
`[OPEN]` DOS-entity-id join, LLC-reference-scoped. *(Supersedes the earlier `registered-llc-name` split.)*

## C3 — Component resolution: deterministic constrained clustering

Constrained clustering (hard *cannot-link* / soft *should-link*), realized as **constrained union-find over
a canonical edge order** — a global optimizer is unnecessary (components max 37; determinism + constraint
satisfaction, not optimality, is required).

**Soft should-link** = allowlisted identity edges, **precedence** `curated-same-owner (3) >
registered-llc-id (2.5) > splink-fellegi-sunter (1)` (F1/R3: `registered-llc` name-only is not identity);
within a tier by score. `cluster_gated` pre-vetoes still drop first-name / common-name+address edges.
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
   (not silently dropped). A skipped **probabilistic** edge (`fellegi-sunter`) is dropped with provenance.
4. **Output:** every reference gets a `resolution_id`; singletons included.

**Tests before build:** permutation invariance (shuffled input ⇒ identical partition + adjudication set);
each constraint type; a deterministic-conflict case; and that adding/removing any `acris-deed` edge changes
nothing.

## C4 — Substantive relationship layer (Phase-3 target)

Holds the owner-**association** signals that are **not** identity (deeds **and**, per F1/R3, the name-only
`registered-llc`). Endpoints are resolved components (`resolution_id`), deduped; **endpoints are never
merged**.

- **Conveyance events (canonical, already in the graph):** `(:Building)-[:HAS_EVENT]->(:Event
  {event_type:'DeedTransfer', source_name:'ACRIS', event_id, source_record_id, event_date})<-[:PARTY_TO
  {role}]-(:Actor)`. `co_grantee_on_deed` / `conveyance_party` is a **derived view** over these w/
  contributing `event_id`s, roles, dates. Never `co-title`. **Held vs. linked-successor is derived from
  source** (`deed_edges._deed_sql` vs `_restructured_groups`), **not** from the graph edge: the current
  `CONNECTED_BY_DEED` edge tags *all* recoveries `acris-deed` (both branches are unioned in
  `deed_node_groups`), so the distinction must be recomputed from ACRIS, consistent with events being
  canonical. *(Optional: also tag the legacy edge `acris-deed-linked-successor` at the producer if a legacy
  consumer needs it — a separate, additive pipeline change.)*
- **Reported-owner-entity association (from `registered-llc`, F1/R3):** two references share a DOF owner
  entity. Model as `associated_via_reported_owner_entity` between resolved components now; the fuller form
  is an explicit legal entity — `(Person)-[:REPORTED_IN_ROLE {role,date,source}]->(LegalEntity)` and
  `(LegalEntity)-[:REPORTED_FOR]->(Building)` — once the owner entity is independently resolved
  (`registered-llc-id`). **Endpoints are associated, not merged.**

Both feed the eventual **common-control admissibility rule** (Phase 6), never identity. `[DECISION]` events
canonical; `[OPEN]` derived-view storage. BBL is the property unit (multi-BIN = documented limitation).

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

## C7 — Acceptance thresholds (tiered; confidence-bound; power-derived)

Gated by [`eval-protocol.md`](eval-protocol.md) **§8.1** (rev 6):
- **Confidence-interval method is estimator-specific:** Clopper–Pearson for **unweighted per-mechanism**
  binomial gates; a **stratified survey estimator / stratum-resampled bootstrap** for **weighted pooled**
  rates; the **paired bootstrap** for the loss difference; **finite-population** reporting for a census
  (adjudicator uncertainty separate). `3/n` is planning-only.
- **Track-A internal cutover** (reversible, no public exposure): **severe-error veto** + a **paired
  noninferiority test** — upper 95% bound of `L(v2) − L(legacy)` `≤ δ = 0.01`, with the mix explicit
  `L = 5·w_M·FM_cond + w_S·FS_cond` (`w_M+w_S=1` preregistered deployment proportions) — + worst-case
  `INDETERMINATE` sensitivity. **[RATIFIED 2026-09-07: T=25, δ=0.01.]**
- **Production / public exposure (deferred):** **each mechanism gated independently** (no pooling) —
  deterministic LB ≥ 99%, probabilistic LB ≥ 95%; component FM UB ≤ 2%; severe UB ≤ 0.5%; coverage
  ≥ 80%/mechanism; power-derived n or census; an **underpowered protected stratum blocks production** of
  that mechanism. **[B2 not yet ratified — pending the per-mechanism + estimator corrections, now applied.]**
- "Severe" is consequence-based (living-person / large-bridge `T`), distinct from ordinary false merge; the
  run manifest **pins the §8.1 revision hash**.

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
- [ ] C7 — §8.1 gate is **confidence-bound + power-derived + tiered** (Track-A relative/veto vs production certification); `[RATIFY]` values frozen + protocol hash pinned.
- [ ] C8 — synchronized legacy/v2 build + parity.

On sign-off, Phases 2–5 unlock against the untouched legacy layer, reversible by version selection.
