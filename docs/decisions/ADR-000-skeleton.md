# ADR-000 — Decision Log Skeleton

Phase 0 inventory, 2026-07-09. One row per substrate divergence. Status = OPEN on all items until decisions are ratified in Phase 1/2.

Principles cited as (P-N) refer to the numbered Reconciliation Principles in RECONCILIATION-KICKOFF.md.

---

## ADR-001 — Building coverage: PLUTO-complete vs violations-only

| | |
|---|---|
| **Topic** | Building node coverage — what is the canonical building substrate? |
| **Evidentiary approach** | ~444K Building nodes; bootstrapped from BBLs that appear in HPD violations; PLUTO enrichment is a LEFT JOIN. Buildings with no violations are absent. |
| **Discovery approach** | ~858K Building nodes; bootstrapped from full `pluto_latest` (~858K lots), then backfilled with any registration BBLs missing from PLUTO. All buildings exist regardless of whether they have violations. |
| **Principle** | P-1 (conform the substrate), P-2 (Building is a shared vocabulary key) |
| **Recommended resolution** | Adopt full PLUTO as canonical substrate (as flagged in the kickoff brief). The evidentiary graph's building-from-violations approach was driven by incremental ingestion order; it is not a principled choice. Full PLUTO means agent-level queries ("which buildings in this borough have no violations?") are answerable. Implement a shared `buildings` ingestion pipeline (as a library module) that both graphs call. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09. Adopting full PLUTO as canonical substrate. Created `watchline/shared/buildings.py` with `load_pluto()` and `load_backfill()` functions shared by both graphs. Discovery's `buildings/pipeline.py` now delegates to the shared module. New `watchline/evidentiary/ingest/buildings/pipeline.py` created; `evidentiary-buildings` Makefile target added as a prerequisite for all event pipelines. The evidentiary event pipelines still contain building-creation Cypher (for enrichment/idempotency); these will be migrated to schema-only MERGE stubs in Phase 4 once the shared substrate is stable. |

---

## ADR-002 — Borough derivation: BBL-first vs source-string

| | |
|---|---|
| **Topic** | How is `Building.borough` set? |
| **Evidentiary approach** | String lookup on the `borough` column of the source table (HPD/DOB/ECB text field), mapped via `BOROUGH_MAP = {"MANHATTAN": "Manhattan", ...}`. Depends on source data quality; may produce wrong values if source encoding varies. |
| **Discovery approach** | Derived deterministically from BBL first digit: `BOROUGH_FROM_BBL = {"1": "Manhattan", "2": "Bronx", ...}`. Source-independent and always correct for valid BBLs. |
| **Principle** | P-1 (substrate must not diverge), P-2 (same fact, same value) |
| **Recommended resolution** | Adopt BBL-first borough derivation (discovery approach). It is deterministic and correct by definition; the source string adds nothing and introduces a failure mode. Apply to the shared buildings pipeline in Phase 2. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09. Applied `borough_from_bbl()` from `watchline/shared/bbl.py` across all five evidentiary ingest pipelines. Removed local `BOROUGH_MAP`/`BOROUGH_CODE_MAP` dicts from `hpd_violations`, `dob_violations`, `ecb_violations`, `hpd_litigations`, and `rentstab`. HPD violations was the only source-string case; the rest were already BBL-first with local dicts. HPD litigations had a two-step double lookup via `boro` field — replaced with single `borough_from_bbl(bbl)` call. Discovery pipelines already use BBL-first and are unaffected. |

---

## ADR-003 — DOB event_id: `number` vs `isndobbisviol`

| | |
|---|---|
| **Topic** | Which DOB violations column is the stable, globally-unique primary key? |
| **Evidentiary approach** | `event_id = "EVT-DOB-{number}"` where `number` is a string field (e.g. "3234567890NV"). |
| **Discovery approach** | `event_id = "EVT-DOB-{isndobbisviol}"` where `isndobbisviol` is a numeric field (e.g. `12345678`). |
| **Principle** | P-2 (same fact, same event_id in both graphs) |
| **Recommended resolution** | **Must resolve before Phase 2.** These produce different `event_id` values for the same physical DOB record. A cross-graph join on `event_id` will fail for all DOB events. Inspect the live `dob_violations` table to determine which field is the stable, unique identifier. The discovery codebase documents `isndobbisviol` as "stable, globally-unique key — verified 1:1 with row count". The evidentiary codebase documents `number` as the "primary key" without a verification note. **Provisional recommendation:** adopt `isndobbisviol` (discovery approach) pending verification against the live table. This will require migrating evidentiary DOB Event nodes on next rebuild. |
| **Status** | DECIDED — 2026-07-09. Live query confirmed: `isndobbisviol` is unique (2,475,392 distinct = 2,475,392 total rows, zero nulls). `number` has 8,601 duplicates — it is not a primary key. Adopt `EVT-DOB-{isndobbisviol}` as the canonical scheme. Evidentiary DOB pipeline must be updated in Phase 2; existing DOB Event nodes require a full rebuild of the evidentiary graph to migrate (no in-place rename — `event_id` is an IS KEY constraint). |

---

## ADR-004 — HPD litigations `source_name`: `'HPD-Litigations'` vs `'HPD'`

| | |
|---|---|
| **Topic** | The `source_name` property on HPD litigation CourtFiling Event nodes |
| **Evidentiary approach** | `source_name = 'HPD-Litigations'` |
| **Discovery approach** | `source_name = 'HPD'` |
| **Principle** | P-2 (same fact, same value) |
| **Recommended resolution** | Adopt `'HPD-Litigations'` (evidentiary approach). It is more specific and distinguishes litigation records from HPD violation records (also `source_name = 'HPD'`), which is important for query filtering. The evidentiary graph also uses `source_name` to route investigative intents — a collision would break queries that filter `source_name = 'HPD'` expecting violations only. |
| **Status** | OPEN |

---

## ADR-005 — ACRIS scope and party handling

| | |
|---|---|
| **Topic** | (a) Which ACRIS document types to ingest; (b) whether grantors/grantees become Actor nodes |
| **Evidentiary approach** | Scope: `doctype IN ('DEED', 'CORRD')` since 2010. Party handling: grantor/grantee names stored as pipe-separated strings on Event node; no Actor nodes. `grantee_canonical_id` null-provisioned for future matching. |
| **Discovery approach** | Scope: `doctype ILIKE '%DEED%'` (all 8 deed subtypes, any date). Party handling: ACRIS party → `Actor:WatchlineNode {actor_id: ACT-ACRIS-<sha1>}` + `PARTY_TO {role}` edge. Deliberately disjoint from LandlordActor namespace. |
| **Principle** | P-3 (actor identity intentionally different), P-4 (single Event supertype) |
| **Recommended resolution** | Split by concern. (a) Document scope: adopt discovery's `ILIKE '%DEED%'` — broader and more authoritative. The evidentiary '2010+' date filter was a pragmatic scope limit; the full history is more useful for ownership change detection. (b) Party handling: the two graphs' different approaches are consistent with Principle 3 — discovery holds raw ACRIS parties; evidentiary defers to its identity resolution pipeline. Keep both as-is. For the shared substrate library, only Events and Buildings are shared; ACRIS party Actors are discovery-only until the evidentiary resolution pipeline is built. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09 (Phase 3). (a) Updated `evidentiary/ingest/acris/load.py` SQL from `doctype IN ('DEED', 'CORRD')` to `doctype ILIKE '%DEED%'` and removed the `2010-01-01` date floor. (b) Party handling unchanged — intentionally different per P-3. |

---

## ADR-006 — Actor key prefix collision: `ACT-` used for three different namespaces

| | |
|---|---|
| **Topic** | `actor_id` prefix `ACT-` is used by both LandlordActor (`ACT-<nodeid>`) in discovery and OwnershipNetwork Actors (`ACT-<uuid4>`) in evidentiary. ACRIS actors use `ACT-ACRIS-<sha1>` which is a sub-namespace of `ACT-`. |
| **Evidentiary approach** | `canonical_id = "ACT-<uuid4>"` (OwnershipNetwork), `canonical_id = "MGT-<uuid5>"` (ManagingAgent). |
| **Discovery approach** | `actor_id = "ACT-<nodeid>"` (LandlordActor), `actor_id = "ACT-ACRIS-<sha1>"` (ACRIS). |
| **Principle** | P-3 (actor keys must be namespaced so regimes never collide) |
| **Recommended resolution** | Adopt explicit namespacing per Principle 3, as the kickoff brief prescribes. Rename discovery LandlordActor key to `ACT-LL-<nodeid>`. Retain `ACT-ACRIS-<sha1>`. Retain evidentiary `ACT-<uuid4>` for OwnershipNetwork (these never enter the discovery graph). `MGT-<uuid5>` is already distinct. Document the namespace registry in a new `docs/actor-namespaces.md`. This is a breaking change for the discovery graph — schedule for Phase 3 with a full rebuild. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09. Renamed discovery LandlordActor key from `ACT-{nodeid}` to `ACT-LL-{nodeid}` in `hpd_registrations/pipeline.py` and `portfolio/pipeline.py` (both `_actor_id()` functions). `ACT-ACRIS-{sha1}` is unchanged. Evidentiary `ACT-{uuid4}` and `MGT-{uuid5}` are already disjoint and unaffected. Namespace registry written to `docs/actor-namespaces.md`. Discovery graph rebuild required to migrate existing nodes; no in-place rename is possible against a live graph due to the IS KEY constraint on `actor_id`. |

---

## ADR-007 — Neo4j database env var: `NEO4J_DATABASE` → `NEO4J_EVIDENTIARY_DATABASE` / `NEO4J_DISCOVERY_DATABASE`

| | |
|---|---|
| **Topic** | The `.env` was updated to use `NEO4J_EVIDENTIARY_DATABASE` and `NEO4J_DISCOVERY_DATABASE`; all pipeline code still reads `NEO4J_DATABASE`. Every pipeline currently falls through to the default `"neo4j"`. |
| **Evidentiary approach** | All pipeline files: `NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")`. Makefile-stash CYPHER_ARGS uses `-d "$(NEO4J_DATABASE)"`. |
| **Discovery approach** | All pipeline files: same `NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")`. Makefile-discovery references `NEO4J_DATABASE` in the `check` target. |
| **Principle** | P-9 (verify against live schema before writing), P-7 (idempotency) |
| **Recommended resolution** | Update evidentiary pipelines to read `NEO4J_EVIDENTIARY_DATABASE`; update discovery pipelines to read `NEO4J_DISCOVERY_DATABASE`. Also update Makefile CYPHER_ARGS and the `check` target. This is Phase 2 work but is a **prerequisite for any pipeline run** — should be prioritised ahead of other Phase 2 items. Also requires deciding where the shared config module lives (see ADR-008). |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09. All `os.environ.get("NEO4J_DATABASE")` calls updated via sed; Makefile-stash CYPHER_ARGS and Makefile-discovery check target updated manually. Python variable names (`NEO4J_DATABASE`) left unchanged — they are internal and do not need to match the env var name. |

---

## ADR-008 — Shared config module: evidentiary-centralised vs discovery-distributed

| | |
|---|---|
| **Topic** | Evidentiary centralises `pg_conn()`, `neo4j_driver()`, `NEO4J_DATABASE` in `portfolio/config.py`, re-exported by `agents/config.py` and `acris/config.py`. Discovery defines these helpers locally in each pipeline. |
| **Evidentiary approach** | One config module; shared by three packages. |
| **Discovery approach** | Each pipeline is self-contained; no shared config. |
| **Principle** | P-5 (one source of truth for shared ingestion primitives) |
| **Recommended resolution** | Create a shared `watchline/shared/connections.py` (or similar) that provides `pg_conn()`, `neo4j_evidentiary_driver()`, `neo4j_discovery_driver()`, and the `NEO4J_EVIDENTIARY_DATABASE` / `NEO4J_DISCOVERY_DATABASE` constants. Both graph-specific ingestion codebases import from this shared module. This is the natural home for the ADR-007 fix and prevents the config from drifting again. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09 (Phase 2). Created `watchline/shared/connections.py` with `pg_conn()`, `neo4j_driver()`, `NEO4J_EVIDENTIARY_DATABASE`, `NEO4J_DISCOVERY_DATABASE`. All 9 discovery + 6 evidentiary pipelines import from shared. Single point of change for credential rotation. |

---

## ADR-009 — Graph type enforcement: evidentiary has none

| | |
|---|---|
| **Topic** | Discovery enforces schema via a GQL graph type (`ALTER CURRENT GRAPH TYPE SET`). Evidentiary has no equivalent. |
| **Evidentiary approach** | Manual `CREATE CONSTRAINT IF NOT EXISTS` in individual pipeline files + `scripts/01_schema.cypher` (contents not read in this inventory). |
| **Discovery approach** | `watchline/discovery/schema/graph_type.cypher` — single source of truth, applied once on empty DB before any pipeline. Declaratively enforces all node types, relationship types, and key constraints. |
| **Principle** | P-6 (graph types are the enforced schema) |
| **Recommended resolution** | Create `watchline/evidentiary/schema/graph_type.cypher` covering the shared substrate layer (Building, Event, and their relationships). The evidentiary overlay (Observation, Claim, Evidence, Rule, Relationship reified node, etc.) may be defined in the same file or in a separate evidentiary-only extension. Align with Neo4j 2026.06+ Enterprise requirement. This is Phase 2 work and should be drafted before the first Phase 2 pipeline is modified. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09. Graph type snapshot written to `watchline/evidentiary/schema/graph_type.cypher` from live `SHOW CURRENT GRAPH TYPE` output against the evidentiary database (2026-07-09). Covers all 14 node types, all relationship types, and all constraints including the `landlord_nodeid` legacy constraint. ADR-009 is now resolved for Phase 2; graph type enforcement (ALTER CURRENT GRAPH TYPE SET) is a Phase 3 item when the evidentiary schema is stable. |

---

## ADR-010 — Batch size and cursor conventions

| | |
|---|---|
| **Topic** | Batch sizes and server-side cursor `itersize` values differ between the two codebases. |
| **Evidentiary approach** | Buildings: 500; violations: 500; observations: 500; portfolio store: 200. Cursor itersize: 2000. |
| **Discovery approach** | Buildings: 2000; events: 2000; portfolio edges: 5000 (cursor). Cursor itersize: 5000 consistently. |
| **Principle** | P-5 (shared library, consistent conventions) |
| **Recommended resolution** | Adopt discovery's larger batch sizes in the shared buildings/events library (2000 batch, 5000 cursor). The evidentiary 500-row batches were conservative; at 11M HPD violations they add unnecessary round-trips. Exception: portfolio store stays at 200 (inner UNWIND multiplies row count). Document the rationale as a comment in the shared config. |
| **Status** | OPEN |

---

## ADR-011 — PostgreSQL source database name in docstrings: `deedwatch` vs `wow`

| | |
|---|---|
| **Topic** | Evidentiary pipeline docstrings refer to the PostgreSQL source as "deedwatch"; discovery refers to it as "wow". Both connect to whatever `PGDATABASE` resolves to. |
| **Evidentiary approach** | Docstrings: "Ingests from the deedwatch PostgreSQL database". |
| **Discovery approach** | Docstrings and `check` target: "Reads WoW (`wow`, port 5434), NOT `deedwatch`". |
| **Principle** | P-9 (source of record is WoW PostgreSQL) |
| **Recommended resolution** | The source is the WoW PostgreSQL instance. `deedwatch` was a developer-specific label. Update evidentiary docstrings to reference `wow` (port 5434). The `check` Makefile target already validates `PGDATABASE = "wow"`. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09 (Phase 3). Updated docstrings in 4 evidentiary event pipelines (hpd_violations, hpd_litigations, dob_violations, ecb_violations) from "deedwatch PostgreSQL database" to "WoW PostgreSQL database (`wow`, port 5434)". References to "DeedWatch" in `fw/server.py`, `fw/explorer.py`, `ui/app.py`, `ui/sidebar.py` are the conversational agent product name and are intentionally unchanged. |

---

## ADR-012 — `fw/connections.py` uses a third set of env var names

| | |
|---|---|
| **Topic** | The evidentiary application framework (`fw/connections.py`) connects to Neo4j using `NEO4J_EPISTEMIC_URI`, `NEO4J_EPISTEMIC_USER`, `NEO4J_EPISTEMIC_PASSWORD`, `NEO4J_EPISTEMIC_DATABASE` — a third naming scheme distinct from the two ingestion codebases. |
| **Evidentiary approach** | `fw/connections.py`: `NEO4J_EPISTEMIC_*` vars. |
| **Discovery approach** | N/A (no equivalent `fw/` layer). |
| **Principle** | P-5 (shared helpers), P-7 (idempotency — configuration drift is a runtime error source) |
| **Recommended resolution** | Align `fw/connections.py` to use `NEO4J_EVIDENTIARY_DATABASE` (the settled name from `.env`). `NEO4J_EPISTEMIC_URI/USER/PASSWORD` can be retained as aliases for the same endpoint (both the ingest and the query path hit the same Neo4j instance for the evidentiary KG), or unified to `NEO4J_URI/USER/PASSWORD` with the database distinguished by the `_EVIDENTIARY_DATABASE`/`_DISCOVERY_DATABASE` suffix. Decide on one canonical naming convention in Phase 1 before writing any new pipeline. |
| **Status** | DECIDED + IMPLEMENTED — 2026-07-09 (Phase 3). Updated `fw/connections.py` to use `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_EVIDENTIARY_DATABASE` (default `"evidentiary"`). Updated `Makefile.evidentiary` `EV_CYPHER_ARGS` to match. `.env` must carry `NEO4J_URI/USER/PASSWORD` alongside or instead of `NEO4J_EPISTEMIC_*`; any deployment using the old names must update its `.env`. |

---

## ADR-013 — Marshal eviction events: discovery-only

| | |
|---|---|
| **Topic** | Discovery ingests `marshal_evictions_all` as `Event(Eviction, Marshal)`; evidentiary has no equivalent pipeline. |
| **Evidentiary approach** | Not ingested. Listed in CLAUDE.md as "not yet ingested". |
| **Discovery approach** | `EVT-MARSHAL-<courtindexnumber>-<docketnumber>`. |
| **Principle** | P-1 (conform the substrate where the same fact should appear in both) |
| **Recommended resolution** | Marshal evictions are a domain fact (not an epistemic overlay) and should eventually be in both graphs. However, the evidentiary graph lacks a `Source` node and `Observation` layer for this source. Design the shared substrate to include marshal evictions as Events; defer the evidentiary overlay (Observations, Claims) until the eviction data model is agreed. Flag as a Phase 4 item. |
| **Status** | OPEN |

---

## ADR-014 — Rent stabilization data: evidentiary-only

| | |
|---|---|
| **Topic** | Evidentiary enriches Building nodes with DHCR rent stabilization unit counts (2018–2023, current, change, deregulating flag). Discovery has no equivalent. |
| **Evidentiary approach** | `rentstab_v2` → Building property enrichment (not a separate Event). |
| **Discovery approach** | Not ingested. |
| **Principle** | P-1 (conform the substrate) |
| **Recommended resolution** | RS unit counts are domain facts about buildings, not an epistemic overlay. Include in the shared buildings substrate library so both graphs carry them. The data is additive (SET properties on existing Building nodes) and does not alter identity. Phase 2 task. |
| **Status** | OPEN |
