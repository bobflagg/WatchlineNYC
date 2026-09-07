# Option B migration — Phase 1 contracts (for review)

**Date:** 2026-09-07 · **Status:** contracts, **for review before any Phase-2 implementation** · **Plan:**
[`ownership-migration-plan.md`](ownership-migration-plan.md) · **Baseline:**
[`ownership-phase0-baseline.md`](ownership-phase0-baseline.md).

These are the contracts Phase 2+ builds against. `[DECISION]` = a choice to confirm; `[OPEN]` = deferred
with a stated default. Nothing here is implemented yet. The invariant they must uphold:
> Identity assertions may determine entity membership. **No substantive relationship assertion may
> participate in entity resolution.** Any common-control grouping comes only from an explicit, evaluated
> admissibility rule.

## C1 — Levels & IDs

Three objects, three ID kinds:

| Object | ID | Grain (today) | Mutability |
|---|---|---|---|
| **Source reference** | `source_reference_id` | the `:Landlord`/`:Actor` node (`actor_id = 'ACT-LL-'+nodeid`) — a WoW `landlords_with_connections` party (already a light HPD `(name,bizaddr)` dedup) | immutable |
| **Resolution component** | `resolution_id` | one identity component in a *specific run* (model+threshold+snapshot) | run-scoped; recomputed each build |
| **Durable entity** | `entity_id` | a canonical owner identity where continuity is established | immutable once assigned; carries lineage |

- `[DECISION]` **`source_reference_id` = the landlord nodeid**, not the raw HPD contact row. Going finer
  (per-registration-contact references) is **out of scope** for this migration — the pipeline's atomic
  party unit is the landlord node. Recorded as a known granularity limit.
- `[DECISION]` **Relationships and conclusions reference `resolution_id`, not `entity_id`**, and record the
  run they were computed under. Invariant: *a historical conclusion retains the resolution version it was
  generated under, even after later merges/splits.*
- `[DECISION]` **`entity_id` continuity rule:** a durable `entity_id` is assigned to a resolution
  component and carried forward across runs when the component's **maximal identity core** (its members
  linked by *deterministic* mechanisms — `curated` / `registered-llc`) is unchanged. Probabilistic-only
  components get a `resolution_id` but **no durable `entity_id`** until a deterministic core or a curator
  establishes continuity. (Prevents membership churn from renaming a stable entity.)
- `[OPEN]` Physical form of `resolution_id`/lineage — a stored property vs. a reproducible derived view.
  Default: store `resolution_id` + `run_id` on the membership edge; lineage in a small side table.

### Identity lifecycle events
`merge`, `split`, `carry` — each event records predecessor/successor `entity_id`s, the `run_id`, the
triggering change (new record / correction / model update / veto change / adjudication), and a redirect
for any retired id. `[DECISION]` **Merge survivor = the entity whose deterministic core is largest**
(tie → lower `entity_id`). **Ambiguous split → all sides get new `entity_id`s** (no arbitrary survival),
with redirects from the old id to the successors.

## C2 — Identity provenance allowlist (fail-closed)

The identity materializer admits an edge into resolution **only** if its `method` is allowlisted; it
**rejects unknown mechanisms** rather than trusting the `CONNECTED_BY_SPLINK` relationship type.

| Mechanism (method string) | Admitted? | Notes |
|---|---|---|
| `curated-same-owner` | ✅ identity | auditable, privileged, **not exempt** from C4 contradiction checks |
| `registered-llc` | ✅ identity (qualified) | deterministic *same legal entity* only with **identifier + jurisdiction**; a normalized LLC name alone is a *weak* id — `[OPEN]` upgrade to a DOS entity-id join where available; until then treated as a name-based legal-entity match subject to C4 |
| `splink-fellegi-sunter` (approved version) | ✅ identity (probabilistic) | same-*reference* hypothesis; version pinned |
| `acris-deed`, `acris-deed-linked-successor` | ❌ **relationship** | never in resolution (this is the invariant) |
| any other / unknown | ❌ | rejected; build fails loudly |

`[DECISION]` The allowlist is **by provenance + assertion type**, versioned; adding a mechanism is a
reviewed contract change.

## C3 — Component-consistency algorithm (designed here; tested before Phase 2 build)

Turns allowlisted identity edges into resolution components. **Deterministic** given a fixed edge set.

1. **Pre-clustering edge vetoes (existing, kept):** `cluster_gated` drops first-name-disagreement edges
   and common-name-with-differing-address edges before union-find.
2. **Candidate components:** union-find over the surviving allowlisted edges.
3. **Component-level checks (new):** each candidate component is validated for
   - **surname consistency** (no cross-surname member set for person components — already ~0 by
     construction; enforced at component level);
   - **entity-type consistency** — do not merge a **natural person** with a **legal entity** with an
     **institution/nonprofit**; type derived from whether the name came from `firstname/lastname`
     (person) vs `corporationname` (entity), plus the institutional/HDFC exclusion list;
   - **conflicting stable identifiers** — if two members carry *different* known identifiers (e.g. DOS
     entity ids), they may not share a component;
   - `[OPEN]` **temporal impossibility** — fires only when reliable valid-time intervals exist; **no-op
     until the temporal model (Phase 3/§7) lands**, so this contract is implementable now.
4. **Repair (deterministic):** when a component fails a check, remove the **lowest-precedence edge on the
   offending path** (precedence `curated` > `registered-llc` > `splink-fellegi-sunter`; ties by ascending
   `(nodeid,nodeid)`) and re-evaluate; repeat until consistent or no probabilistic edges remain.
5. **Flag, don't force:** a component that cannot be made consistent by removing probabilistic edges is
   **flagged and not used as one entity** — its members fall back to smaller consistent components /
   singletons (deny-by-default). A flag never silently merges.

`[DECISION]` Determinism, precedence order, and flag-not-merge are the committed properties. The algorithm
is specced, reviewed, and unit-tested **before** Phase-2 implementation (per the plan).

## C4 — Conveyance-event representation (Phase 3 target)

- **Canonical form already exists in the graph:** `(:Building)-[:HAS_EVENT]->(:Event
  {event_type:'DeedTransfer', source_name:'ACRIS', event_id, source_record_id, event_date})<-[:PARTY_TO
  {role}]-(:Actor)`. This is the substrate — n-ary, role-bearing, dated, document-identified.
- **`co_grantee_on_deed` / `conveyance_party`** between **resolved entities** (`resolution_id` endpoints,
  deduped) is a **derived view** over those events, carrying: contributing `event_id`s, roles, dates,
  method (`acris-deed` **held** vs `acris-deed-linked-successor`, kept distinct). Never `co-title`.
- `[DECISION]` The **event is canonical**; the only open item is the derived pairwise view's storage shape
  (materialized edge vs. computed on read) — `[OPEN]`, default: materialized edge with provenance.
- Property unit is the **BBL** (`Building` is BBL-keyed); multi-BIN-per-BBL is a documented limitation, not
  a parcel layer.

## C5 — Party → building projection

- A building associates to an entity via the entity's members' `bbls` (rental-only; co-op/condo excluded,
  per `coop_condo.py`).
- `[DECISION]` A **building MAY associate to multiple entities** (joint ownership) — represented as
  multiple entity→building associations, **never a node merge**.
- `[DECISION]` **Default projection = current** (latest registration/deed); historical projection is
  available via the temporal model when it lands (`[OPEN]`).
- `[DECISION]` **Allegations/violations do NOT propagate** across inferred entity membership by default
  (deny-by-default); a building's events stay attached to the building.

## C6 — Consumer read contracts (deny-by-default)

Default reads see **identity entities only**; a consumer must **opt in** to deed-relationship/path or
control-conclusion behavior.

| Consumer | Target read (v2) | Change |
|---|---|---|
| `aggregator_audit` | owner = `entity_id` (incl. singletons) at each address | mask becomes a **frozen, versioned input** from a declared upstream run (Phase-4 DAG); re-validate the 73-address list |
| `verify_splink` | canaries over v2; the `composition` canary becomes the **invariant regression test** (C2/C3 property) | update at cutover |
| `eval/sample` | strata over v2 `entity_id`s | **fixture version bump**; re-freeze the sample |
| (future) agent/UI | identity entities; deed **paths** only (vetted); **no** named control groups pre-eval | governed by [`ownership-layer-decision.md`](ownership-layer-decision.md) §M5 |

## C7 — Acceptance thresholds

The Phase-5 identity cutover is gated by the **preregistered thresholds in
[`eval-protocol.md`](eval-protocol.md) §8.1** — fixed **before** Phase-2 results are examined
(pairwise precision by mechanism; component + **severe** false-merge rate; person-vs-entity; common-name /
probabilistic-bridge components; false-merge weighted above false-split; explicit cutover value + failure
response). This contract adopts §8.1 by reference; the numeric bars are set with the team before Phase 2.

## Sign-off checklist (what "Phase 1 approved" means)

- [ ] C1 IDs + lifecycle (survivor/split rules, what references `resolution_id`).
- [ ] C2 allowlist (and the `registered-llc` identifier+jurisdiction stance).
- [ ] C3 consistency algorithm (determinism, precedence, flag-not-merge) — **plus its unit tests written**.
- [ ] C4 event-centric deeds + derived-view shape.
- [ ] C5 projection (multi-membership, current-default, no allegation propagation).
- [ ] C6 consumer read contracts + deny-by-default.
- [ ] C7 §8.1 numeric thresholds fixed.

On sign-off, Phases 2–5 unlock (parallel `ResolvedEntityV2`, event relationships, shadow + consumer
migration, cutover) — all against the untouched legacy layer, reversible by version selection.
