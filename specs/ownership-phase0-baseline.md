# Option B migration — Phase 0 baseline & consumer inventory

**Date:** 2026-09-07 · **Status:** Phase 0 output (read-only measurement) · **Plan:**
[`ownership-migration-plan.md`](ownership-migration-plan.md) · **Snapshot:** the numbers below are the
reproducible baseline the migration is measured against; re-run to refresh.

## 1. Baseline versions & rollback unit

| Component | Value at baseline |
|---|---|
| Code (git) | `0cb7298` on `entity-linking-prototype` |
| Portfolio run id | `PF-20260901T165123Z` |
| OwnerGroup build (`generated_at`) | 2026-09-04T00:50:07Z · `method = splink-identity+curated+llc` |
| Source records | `justfixwow` Postgres dump (`:5434`); vintage held with the dump |
| Latest `DeedTransfer` `event_date` | 2028-09-17 *(future-dated — ACRIS has erroneous dates; a data-quality caveat, not a blocker)* |

**Graph snapshot (counts):**

| | count |
|---|---:|
| Buildings | 859,794 |
| Landlords | 118,493 |
| Portfolios | 97,244 |
| OwnerGroups | 6,540 |
| `IN_OWNER_GROUP` | 15,777 |
| `CONNECTED_BY_SPLINK` (identity) | 13,203 |
| `CONNECTED_BY_DEED` (relationship) | 1,429 |
| `APPARENT_CONTROL` | 171,347 |
| `MANAGED_BY` | 66,837 |
| `DeedTransfer` events (`:Event`) | 3,018,093 |

The **rollback unit** to version together (per the plan): this git sha · the portfolio run id ·
the OwnerGroup build id/method · the Postgres source watermark · schemas/indexes · derived masks &
eval fixtures. Before the Phase-1 change, snapshot the current `OwnerGroup`/`IN_OWNER_GROUP` layer
(tag by build id or export) so it is version-selectable, not overwritten.

## 2. Transition matrix — *deed-removal only* (materialized 6,540 groups)

Effect of removing deed edges from identity union-find alone; the Phase-2 consistency algorithm may
change it further. Row classes are **not** mutually-exclusive evidence types.

| legacy composition | count | → identity groups ≥2 | → singletons | → entity-pair deed rels |
|---|---:|---:|---:|---:|
| `identity` | 6,402 | 6,402 | 78 | 83 |
| `deed_only` | 105 | 0 | 234 | 159 |
| `deed_bridged` | 33 | 70 | 10 | 60 |
| **total** | 6,540 | **6,472** | **322** | **302** |

## 3. Conservation totals (auditable)

- **Source-reference conservation (no loss):** 15,777 landlord refs in OwnerGroups **before** →
  **15,455 grouped (≥2) + 322 singletons = 15,777** after. ✅ nothing dropped; the 322 become singleton
  resolved entities.
- **Deed edges:** 1,429 total · 1,339 internal to a materialized group · 90 crossing a group boundary
  (vintage drift — deed edges added since the 2026-09-04 build).
- **Internal deed edges decompose:** 1,339 → **302 cross-entity pairs** (the genuine typed relationships
  that replace the fusion) + **996 within-entity (redundant) edges** (both endpoints already the same
  identity entity — the "deed redundant/extends" case).
- **Landlord nodes touched by any deed edge:** 2,124.
- **Deed events underlying the edges:** not stored on the edge (`deed_edges` emits `(src,dst,weight)`
  and rebuilds cliques from Postgres `real_property_master`), so the "every legacy deed edge maps to a
  conveyance event, 0 orphans" check is a **Phase-3 reconciliation task** (anti-join edge→event), not
  computable from the current edge. Flagged for Phase 3.

## 4. Consumer inventory

Semantic consumers of the `OwnerGroup` layer (concept each needs; current read; replacement under the
identity-only model; migration note). **agent/ and ui/ reference it nowhere** — confirmed, so there is no
public/serving consumer to migrate.

| Consumer | Concept | Current read | Replacement | Migration note |
|---|---|---|---|---|
| `aggregator_audit.py` | **identity** (owners-per-address) | `(:Landlord)-[:IN_OWNER_GROUP]->(og)` to count distinct owners at each high-degree address | same, over identity-only `ResolvedEntityV2` (owner = entity id, incl. singletons) | **Feedback loop** — its mask shapes `CONNECTED_BY_ADDRESS`/Portfolio. Freeze the mask as a versioned input from a declared upstream run (plan Phase 4 DAG); re-validate the 73-address mask against identity-only counts. |
| `verify_splink.py` | **identity + provenance** | OwnerGroup canaries + `composition` breakdown + layer-divergence | canaries over identity-only; the `composition` canary becomes the **invariant regression test** (no deed mechanism in identity provenance) | Update after Phase 5; property test replaces the `deed=0` symptom check. |
| `eval/sample.py` | **identity** (stratification) | `Q_OWNERGRP` maps landlord→OwnerGroup for S2/owner strata | same, over `ResolvedEntityV2` | Re-freeze the eval sample against the v2 entity ids; record as an eval-fixture version bump. |
| `case-escobar.md` | identity (illustration) | example Cypher over OwnerGroup / IN_PORTFOLIO | recompute example numbers | Doc; refresh after cutover. |
| (future) agent / UI | identity / paths / control | — none today — | reads v2 identity groups; deed **paths** only (vetted), never named control groups pre-eval | Governed by the consumption contract ([`ownership-layer-decision.md`](ownership-layer-decision.md) §M5 caveat). |

**Not consumers (producer / orchestration / tests):** `owner_groups.py` (producer), `pipeline.py`
(orchestrator), `coop_condo.py` + `deed_edges.py` (comment references only), `tests/test_owner_groups*.py`.

## 5. What Phase 0 establishes → Phase 1 inputs

- Baseline is reproducible and version-selectable; the change is reversible against it.
- The migration touches **more than the 138 obviously-deed-derived groups** (even `identity` groups shed
  78 singletons) — Phase 1 contracts must cover all of it.
- **Zero source-reference loss** is the conservation invariant Phase 4/5 must re-verify after the
  consistency algorithm runs (which may move members further).
- No serving/public consumer exists — consumer migration is 3 internal scripts + fixtures + docs, so the
  cutover ceremony stays light (per the plan's right-sizing).

**Open for Phase 1 (contracts):** the three-ID scheme + lineage; the component-consistency algorithm
(design/review/test before Phase 2); the party→building projection; the identity provenance allowlist;
the Phase-5 identity thresholds ([`eval-protocol.md`](eval-protocol.md) §8.1). Phase 0 is complete;
Phases 2–5 unlock on Phase-1 sign-off.

## 6. Caveats on the numbers

- **Materialized vs. raw universe:** all counts here are the **materialized** 6,540-group layer (post
  co-op/condo drop). The raw current-edge union-find is 6,770 (6,618/118/34); they converge on the next
  rebuild. Use the materialized numbers.
- **Vintage drift:** 90 deed edges + some identity edges cross the 2026-09-04 group boundaries because
  edges were rebuilt since; a fresh `--step ownergroup` before Phase 2 removes the drift.
- Future-dated ACRIS deeds exist (§1) — a source data-quality issue to carry into Phase 3 temporal rules.
