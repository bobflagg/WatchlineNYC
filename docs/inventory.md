# Phase 0 Inventory — WatchlineNYC KG Reconciliation

**Date:** 2026-07-09  
**Status:** Phase 0 READ-ONLY — no code changes made.

---

## Executive Summary

Two independently-built ingestion codebases share the same PostgreSQL source (`wow`, port 5434) but diverge on every modelling dimension. The six most consequential divergences are:

1. **Building coverage:** Discovery loads all ~858K PLUTO lots as the building substrate; Evidentiary bootstraps only from BBLs that appear in violation tables (~444K). Borough is derived differently (BBL first-digit in Discovery; string lookup on source field in Evidentiary).
2. **DOB event_id collision:** Discovery keys DOB events on `isndobbisviol` (numeric); Evidentiary keys on `number` (a different string field in the same table). These are not the same column — the same physical DOB record gets a different `event_id` in each graph.
3. **Actor identity model:** Discovery uses raw, unresolved landlord identities (`actor_id = ACT-<nodeid>`, keyed on `landlords_with_connections.nodeid`) plus a separate ACRIS namespace (`ACT-ACRIS-<sha1>`). Evidentiary resolves landlords into `OwnershipNetwork` Actors keyed on `canonical_id = ACT-<uuid4>` (stable across runs via Jaccard BBL matching) and managing agents keyed on `canonical_id = MGT-<uuid5>`. These identity regimes are deliberately different (Principle 3) but collide on key prefix: both use `ACT-` with different derivations.
4. **ACRIS party handling:** Discovery creates `Actor` nodes for ACRIS deed parties and writes `PARTY_TO` edges; Evidentiary stores grantor/grantee names as string properties on the Event node only (`grantor_names`, `grantee_names`), with `grantee_canonical_id` null-provisioned for a future matching pipeline.
5. **Env var mismatch:** All evidentiary pipeline files read `NEO4J_DATABASE` and fallback to `"neo4j"`. The `.env` now provides `NEO4J_EVIDENTIARY_DATABASE` and `NEO4J_DISCOVERY_DATABASE` instead. Every evidentiary pipeline and both Makefiles will silently connect to the wrong database until this is fixed.
6. **Graph type:** Discovery has a machine-enforceable GQL graph type (`schema/graph_type.cypher`) applied with `ALTER CURRENT GRAPH TYPE SET`. Evidentiary has no equivalent; it relies on `CREATE CONSTRAINT IF NOT EXISTS` statements scattered across individual pipeline files and a `scripts/01_schema.cypher` that was not read (not in discovery codebase).

---

## Evidentiary KG

### 1. Project Layout

```
watchline/evidentiary/ingest/
├── portfolio/          Landlord graph load (SQL → Landlord nodes) + WCC/Louvain +
│                       OwnershipNetwork Actors + PBC-001 Claims + BeneficialControl rels
│   ├── config.py       pg_conn(), neo4j_driver(), NEO4J_DATABASE (reads NEO4J_DATABASE)
│   ├── load.py         PostgreSQL → intermediate Landlord nodes + CONNECTED_BY_* edges
│   ├── algorithms.py   GDS WCC + recursive Louvain; yields (orig_id, frozenset, split_info)
│   ├── store.py        Portfolio → ontology: IdentityObservation, IdentityAssertion,
│   │                   OwnershipNetwork Actor, Evidence, PBC-001 Claim, BeneficialControl Relationship
│   ├── pipeline.py     Entry point: init/load/project/wcc/store/reconcile/cleanup
│   ├── recluster_actor.py  One-off utility: re-run Louvain on a single actor
│   └── sql/landlords_with_connections.sql
├── agents/             ManagingAgent ingestion from wow_bldgs.allcontacts
│   ├── config.py       Re-exports from portfolio.config
│   ├── load.py         wow_bldgs.allcontacts (title='Agent') → deduped agent list
│   ├── store.py        ManagingAgent Actor nodes + ManagedBy Relationship nodes
│   └── pipeline.py     Entry point: load/store
├── hpd_violations/     HPD violation events (~11M)
│   └── pipeline.py     Source nodes + Building nodes (via pluto_latest join) + Violation Events + Observations
├── dob_violations/     DOB violation events (~2.5M)
│   └── pipeline.py     Source nodes + Building nodes + Violation Events + Observations
├── ecb_violations/     ECB/OATH judgment events (~1.8M)
│   └── pipeline.py     Source nodes + Building nodes + Judgment Events + Observations
├── hpd_litigations/    HPD housing court filings (~239K)
│   └── pipeline.py     Source nodes + CourtFiling Events + Observations
├── rentstab/           DHCR rent stabilization data
│   └── pipeline.py     Source nodes + Building enrichment (RS unit counts, deregulating flag)
├── phc001/             Rule PHC-001 evaluation (graph-only, no Postgres)
│   └── pipeline.py     Reads graph Events → PersistentHazardousConditions Claims + Evidence
└── acris/              ACRIS deed transfers
    ├── config.py       Re-exports from portfolio.config
    ├── load.py         real_property_master + real_property_legals + parties → aggregated deed rows
    ├── store.py        DeedTransfer Event nodes (grantor/grantee as string properties)
    └── pipeline.py     Entry point: load/store
```

**Framework** (`watchline/fw/`) is separate from ingestion and uses its own connection env vars (`NEO4J_EPISTEMIC_URI`, `NEO4J_EPISTEMIC_USER`, `NEO4J_EPISTEMIC_PASSWORD`, `NEO4J_EPISTEMIC_DATABASE`).

### 2. Building Modeling

**Source tables:** `hpd_violations` (primary; BBL reconstruction from `boroid/block/lot` when blank), joined with `pluto_latest` for enrichment. `rentstab_v2` adds RS unit count properties to existing Building nodes. DOB/ECB/litigations also MERGE Building nodes from their source BBLs.

**Properties written by HPD pipeline:** `bbl`, `address` (PLUTO preferred over HPD street name), `borough` (string-lookup on HPD's uppercase borough field via BOROUGH_MAP), `bin`, `latitude`, `longitude`, `residential_units`, `year_built`, `building_class`, `created_at`, `updated_at`.

**Rentstab adds:** `rs_units_2018`–`rs_units_2023`, `rs_units_current`, `rs_units_change`, `rs_deregulating`, `rs_pdfsoa_2023`.

**MERGE key:** `bbl` (string, `Building:WatchlineNode {bbl: ...}`).

**BBL normalization:** In-Python function `normalize_bbl()` in HPD pipeline:
```python
bbl = (row.get("bbl") or "").strip()
if len(bbl) == 10:
    return bbl
# reconstruct: boroid.zfill(1) + block.zfill(5) + lot.zfill(4)
```
Note: `lpad`-style reconstruction also appears inline in `BUILDINGS_SQL` for the SQL path:
```sql
CASE WHEN trim(bbl) = '' OR bbl IS NULL
THEN lpad(boroid::text,1,'0')||lpad(block::text,5,'0')||lpad(lot::text,4,'0')
ELSE trim(bbl) END AS bbl_canonical
```

**Coverage:** Only BBLs that appear in HPD violations (~444K). Buildings with no violations are absent. PLUTO enrichment is opportunistic (LEFT JOIN), not the source of Building node creation.

### 3. Actor Modeling

Two distinct Actor sub-types coexist in the evidentiary graph:

**OwnershipNetwork Actors:**
- Labels: `:Actor:WatchlineNode`
- Key property: `canonical_id = "ACT-<uuid4>"` — random UUID4 on creation, then matched across runs by Jaccard similarity of BBL sets (threshold 0.5).
- Key properties: `actor_type = 'OwnershipNetwork'`, `display_name`, `bbl_set`, `resolution_confidence`.
- Source: `landlords_with_connections` (via Landlord intermediate nodes).
- Identity: resolved — the Louvain community is collapsed into one canonical node.

**ManagingAgent Actors:**
- Labels: `:Actor:WatchlineNode`
- Key property: `canonical_id = "MGT-<uuid5>"` — UUID5 derived from `normalize(name) || normalize(address)`, stable across runs.
- Key properties: `actor_type = 'ManagingAgent'`, `display_name`, `business_address`.
- Source: `wow_bldgs.allcontacts` (title='Agent').

No secondary label (`LandlordActor`, `AcrisParty`) is used in the evidentiary graph; both Actor types merge under the `:Actor` label and are distinguished by `actor_type` property.

### 4. Event Modeling

All events share `:Event:WatchlineNode` with MERGE on `event_id`. No secondary label added for any source type.

| Pipeline | event_type | source_name | event_id scheme | Source PK column |
|---|---|---|---|---|
| hpd_violations | Violation | HPD | `EVT-HPD-<violationid>` | `violationid` (integer) |
| dob_violations | Violation | DOB | `EVT-DOB-<number>` | `number` (string) |
| ecb_violations | Judgment | ECB | `EVT-ECB-<ecbviolationnumber>` | `ecbviolationnumber` (string) |
| hpd_litigations | CourtFiling | HPD-Litigations | `EVT-HPD-LIT-<litigationid>` | `litigationid` (integer) |
| acris | DeedTransfer | ACRIS | `EVT-ACRIS-<documentid>` (deferred) | `documentid` |

Each pipeline also creates:
- `Source` node (MERGE on `source_id`), e.g. `SRC-HPD-VIOLATIONS-001`
- `Observation` nodes (MERGE on `observation_id`, e.g. `OBS-HPD-<violationid>`) linked via `-[:ORIGINATES_IN]->` to Source

### 5. Relationships

| Relationship | How written |
|---|---|
| `(Building)-[:HAS_EVENT]->(Event)` | MERGE inline with Event node creation |
| `(Observation)-[:ORIGINATES_IN]->(Source)` | MERGE inline with Observation creation |
| `(Event)-[:ORIGINATES_IN]->(Source)` | MERGE inline with violation load |
| `(Landlord)-[:CONNECTED_BY_NAME]->(Landlord)` | MERGE in load.py (intermediate) |
| `(Landlord)-[:CONNECTED_BY_ADDRESS]->(Landlord)` | MERGE in load.py (intermediate) |
| `(IdentityAssertion)-[:RESOLVES_TO]->(Actor)` | CREATE in store.py |
| `(IdentityAssertion)-[:ASSERTS_IDENTITY_OF]->(IdentityObservation)` | MERGE |
| `(Actor)-[:SUBJECT_OF]->(Claim)` | CREATE |
| `(Claim)-[:SUPPORTED_BY]->(Evidence)` | CREATE |
| `(Claim)-[:PRODUCED_BY]->(Rule)` | CREATE |
| `(Relationship:BeneficialControl)-[:INVOLVES_ACTOR]->(Actor)` | MERGE (reified) |
| `(Relationship:BeneficialControl)-[:INVOLVES_BUILDING]->(Building)` | MERGE (reified) |
| `(Relationship:ManagedBy)-[:INVOLVES_ACTOR]->(Actor)` | MERGE (reified) |
| `(Relationship:ManagedBy)-[:INVOLVES_BUILDING]->(Building)` | MERGE (reified) |
| `(Relationship:ProbableAffiliation)-[:INVOLVES_ACTOR]->(Actor)` | MERGE (reified) |

### 6. Ingestion Mechanics

- **Driver:** Neo4j Python driver (`neo4j` package), synchronous sessions.
- **Batching:** Variable by pipeline: 500 (HPD buildings), 500 (violations), 200 (portfolio store, BATCH_SIZE inner UNWIND multiplies row count). No consistent batch size constant.
- **Cursors:** Server-side named cursors (`cursor_factory=RealDictCursor`, named cursor string) used in HPD/DOB/ECB violation and portfolio load pipelines. `itersize` varies: 2000 (portfolio), 2000 (HPD violations), 5000 (rentstab). Agents pipeline uses `cur.fetchall()` (no server-side cursor — potentially large in-memory fetch).
- **Idempotency:** MERGE on business keys throughout; `created_at = CASE WHEN IS NULL` / `updated_at = always` pattern used consistently.
- **Transactions:** Single auto-commit session per batch (no explicit transaction blocks). Portfolio store uses one session for the entire run; violation pipelines open/close per step.

### 7. Config/Connections

- **PostgreSQL:** `pg_conn()` reads `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. The source database is referred to as `deedwatch` in the HPD/DOB/ECB/litigations pipeline docstrings ("Ingests from the deedwatch PostgreSQL database"), though the actual connection uses whatever `PGDATABASE` is set to.
- **Neo4j:** `neo4j_driver()` reads `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. Database name: `NEO4J_DATABASE` with fallback `"neo4j"`.
- **BROKEN:** The `.env` now uses `NEO4J_EVIDENTIARY_DATABASE` and `NEO4J_DISCOVERY_DATABASE` instead of `NEO4J_DATABASE`. All evidentiary pipelines will fall through to the `"neo4j"` default. This is a live breakage.
- **Framework (fw/):** Uses separate vars `NEO4J_EPISTEMIC_URI`, `NEO4J_EPISTEMIC_USER`, `NEO4J_EPISTEMIC_PASSWORD`, `NEO4J_EPISTEMIC_DATABASE` — a third naming scheme distinct from both ingestion codebases.
- **Makefile-stash CYPHER_ARGS** still passes `-d "$(NEO4J_DATABASE)"` which is also gone from `.env`.

### 8. Graph Type / Schema

No GQL graph type file found in the evidentiary codebase. Schema is enforced via:
- `CREATE CONSTRAINT landlord_nodeid IF NOT EXISTS FOR (n:Landlord) REQUIRE n.nodeid IS UNIQUE` in `load.py`
- A `scripts/01_schema.cypher` referenced by `make schema` in Makefile-stash (file not read — outside ingestion tree; contents unknown from this inventory).

No `ALTER CURRENT GRAPH TYPE SET` is used; schema enforcement is manual and partial.

### 9. Source Tables (PostgreSQL)

| Pipeline | Tables read |
|---|---|
| portfolio | `wow_landlords`, `landlords_with_connections` (via `sql/landlords_with_connections.sql`) |
| agents | `wow_bldgs.allcontacts` (JSONB column) |
| hpd_violations | `hpd_violations`, `pluto_latest` |
| dob_violations | `dob_violations`, `pluto_latest` |
| ecb_violations | `ecb_violations`, `pluto_latest` |
| hpd_litigations | `hpd_litigations` |
| rentstab | `rentstab_v2`, `pluto_latest` |
| phc001 | (graph only — no Postgres) |
| acris | `real_property_master`, `real_property_legals`, `real_property_parties` |

---

## Discovery KG

### 1. Project Layout

```
watchline/discovery/
├── schema/
│   └── graph_type.cypher   GQL graph type — single source of truth, enforced
└── ingest/
    ├── buildings/          PLUTO → full Building substrate (~858K lots)
    │   └── pipeline.py     pluto + backfill for registration BBLs missing from PLUTO
    ├── hpd_registrations/  Actor nodes + REGISTERED_FOR edges
    │   └── pipeline.py     landlords_with_connections → Actor:LandlordActor; wow_landlords JOIN → edges
    ├── hpd_violations/     HPD violation events
    │   └── pipeline.py     hpd_violations → Event(Violation, HPD) + HAS_EVENT
    ├── dob_violations/     DOB violation events
    │   └── pipeline.py     dob_violations → Event(Violation, DOB) + HAS_EVENT
    ├── ecb_violations/     ECB judgment events
    │   └── pipeline.py     ecb_violations → Event(Judgment, ECB) + HAS_EVENT
    ├── hpd_litigations/    HPD court filing events
    │   └── pipeline.py     hpd_litigations → Event(CourtFiling, HPD) + HAS_EVENT
    ├── marshal_evictions/  Marshal eviction events
    │   └── pipeline.py     marshal_evictions_all → Event(Eviction, Marshal) + HAS_EVENT
    ├── acris_deeds/        ACRIS deed transfer events + grantor/grantee Actor nodes
    │   └── pipeline.py     real_property_master + legals + parties → Event(DeedTransfer) + Actor:ACRIS + PARTY_TO
    └── portfolio/          WCC/Louvain clustering → Portfolio nodes + APPARENT_CONTROL
        ├── pipeline.py     schema/edges/reconcile steps; loads Actor.bbls + connection edges
        └── algorithms.py   GDS WCC + recursive Louvain; yields (portfolio_id, frozenset)
```

### 2. Building Modeling

**Source tables:** `pluto_latest` (primary, full ~858K lots). `hpd_registrations` used for backfill of BBLs missing from PLUTO (~1,032 records).

**Properties written:** `bbl`, `address`, `borough` (derived from BBL first digit via `BOROUGH_FROM_BBL` dict — deterministic, source-independent), `latitude`, `longitude`, `residential_units`, `year_built`, `building_class`, `created_at`, `updated_at`.

**MERGE key:** `bbl` (string, `Building:WatchlineNode {bbl: ...}`).

**BBL normalization:** In SQL via `trim(bbl)` on `pluto_latest.bbl` (CHAR(n) field). Borough is derived from the first character of the trimmed BBL — not from any source borough string. For HPD violations and other downstream event pipelines:
```sql
COALESCE(
    NULLIF(trim(bbl), ''),
    trim(boroid) || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
) AS bbl
```
DOB and ECB do not reconstruct from components (blank BBL rows are skipped).

**Coverage:** Full PLUTO — all ~858K lots, including buildings with no violations. Buildings are created independently of events (separate pipeline step, runs first).

### 3. Actor Modeling

Three distinct Actor sub-types in the discovery graph:

**LandlordActor (HPD registrations):**
- Labels: `:Actor:WatchlineNode:LandlordActor`
- Key property: `actor_id = "ACT-<nodeid>"` — deterministic, from `landlords_with_connections.nodeid`.
- Properties: `nodeid` (int), `name`, `bizaddr`, `bbls` (list of strings, set by portfolio pipeline).
- Source: `landlords_with_connections` (one row per distinct `(name, bizaddr)` identity).

**ACRIS Actors:**
- Labels: `:Actor:WatchlineNode` (no `:LandlordActor` — deliberately excluded from GDS projection)
- Key property: `actor_id = "ACT-ACRIS-<sha1>"` — SHA-1 of `normalize(name|address1|address2|city|state|zip)`.
- Properties: `name`, `bizaddr`, `origin = 'ACRIS'`.
- Source: `real_property_parties` (partytype 1/2/3).

**Portfolio / anchor actor:** Not a separate node type — the portfolio pipeline promotes one `LandlordActor` (most BBLs) as the `APPARENT_CONTROL` anchor for a Portfolio. No synthetic "OwnershipNetwork" Actor is created.

The GDS projection in `discovery/ingest/portfolio/algorithms.py` explicitly projects `:LandlordActor` (not `:Actor`) to exclude ACRIS actors from clustering.

### 4. Event Modeling

All events use `:Event:WatchlineNode` with MERGE on `event_id`. No secondary labels. No Observation or Source nodes written (discovery layer has no evidentiary overlay).

| Pipeline | event_type | source_name | event_id scheme | Source PK column |
|---|---|---|---|---|
| hpd_violations | Violation | HPD | `EVT-HPD-<violationid>` | `violationid` (integer) |
| dob_violations | Violation | DOB | `EVT-DOB-<isndobbisviol>` | `isndobbisviol` (integer) |
| ecb_violations | Judgment | ECB | `EVT-ECB-<ecbviolationnumber>` | `ecbviolationnumber` (string) |
| hpd_litigations | CourtFiling | HPD | `EVT-HPD-LIT-<litigationid>` | `litigationid` (integer) |
| marshal_evictions | Eviction | Marshal | `EVT-MARSHAL-<courtindexnumber>-<docketnumber>` | composite |
| acris_deeds | DeedTransfer | ACRIS | `EVT-ACRIS-<documentid>` | `documentid` |

Note: `source_name` for HPD litigations is `'HPD'` in discovery, vs `'HPD-Litigations'` in evidentiary.

### 5. Relationships

| Relationship | How written |
|---|---|
| `(Building)-[:HAS_EVENT]->(Event)` | MERGE inline with Event creation |
| `(Actor:LandlordActor)-[:REGISTERED_FOR]->(Building)` | MERGE in hpd_registrations pipeline; edge carries `registrationid`, `registration_end_date` |
| `(Actor)-[:PARTY_TO {role}]->(Event)` | MERGE in acris_deeds pipeline; role = Grantor/Grantee/Other |
| `(Actor)-[:CONNECTED_BY_NAME {weight}]->(Actor)` | MERGE in portfolio edges step; undirected MERGE |
| `(Actor)-[:CONNECTED_BY_ADDRESS {weight}]->(Actor)` | MERGE in portfolio edges step; undirected MERGE |
| `(Actor)-[:MEMBER_OF]->(Portfolio)` | MERGE in portfolio reconcile step |
| `(Building)-[:IN_PORTFOLIO]->(Portfolio)` | MERGE in portfolio reconcile step |
| `(Actor)-[:APPARENT_CONTROL {heuristic:true, method, run_id, generated_at}]->(Building)` | MERGE; flagged heuristic |

### 6. Ingestion Mechanics

- **Driver:** Neo4j Python driver, synchronous sessions.
- **Batching:** More consistent than evidentiary: 2000 (buildings, actors, events), 5000 (cursor `itersize`), 1000 (actor edges), 5000 (portfolio edges).
- **Cursors:** Server-side named cursors throughout, with `itersize = 5000` consistently. Exception: portfolio edges reads from `landlords_with_connections` with `itersize = 2000`.
- **Idempotency:** MERGE on business keys; same `created_at = CASE WHEN IS NULL` / `updated_at = always` pattern.
- **Portfolio:** Fully rebuilt each run (Portfolio nodes and APPARENT_CONTROL edges are DETACHed/DELETEd then recreated). No versioned update protocol.
- **ACRIS dedup:** `DISTINCT ON (documentid) ORDER BY documentid, modifieddate DESC` handles 4,664 duplicate master rows.

### 7. Config/Connections

- **PostgreSQL:** Same `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` env vars. Source database referred to as `wow` (port 5434) in all discovery docstrings — explicitly NOT `deedwatch`.
- **Neo4j:** `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`; database: `NEO4J_DATABASE` with fallback `"neo4j"`.
- **BROKEN:** Same issue as evidentiary — `NEO4J_DATABASE` is no longer in `.env`. Discovery Makefile's `check` target even validates `"wow"` as the expected Postgres database name (line 40).
- **Connection helpers:** Each pipeline defines its own `pg_conn()` and `neo4j_driver()` locally; no shared config module (unlike evidentiary which centralises in `portfolio/config.py`).

### 8. Graph Type / Schema

Discovery has a machine-enforced GQL graph type at `watchline/discovery/schema/graph_type.cypher`. Applied via `ALTER CURRENT GRAPH TYPE SET` (replaces entire type). Requires Neo4j 2026.06+ Enterprise.

The type declares:
- `(:Building => :WatchlineNode)` — IS KEY on `bbl`
- `(:Actor => :WatchlineNode)` — IS KEY on `actor_id`
- `(:Event => :WatchlineNode)` — IS KEY on `event_id`
- `(:Portfolio => :WatchlineNode)` — IS KEY on `portfolio_id`
- All relationship types with their required properties

Secondary labels (`:LandlordActor`, `:AcrisParty`) are NOT declared in the graph type — they are open-schema extensions that survive because `ALTER CURRENT GRAPH TYPE SET` uses open-schema mode.

Evidentiary has no equivalent graph type.

### 9. Source Tables (PostgreSQL)

| Pipeline | Tables read |
|---|---|
| buildings | `pluto_latest`, `hpd_registrations` (backfill only) |
| hpd_registrations | `landlords_with_connections`, `wow_landlords`, `hpd_registrations` |
| portfolio | `landlords_with_connections` |
| hpd_violations | `hpd_violations` |
| dob_violations | `dob_violations` |
| ecb_violations | `ecb_violations` |
| hpd_litigations | `hpd_litigations` |
| marshal_evictions | `marshal_evictions_all` |
| acris_deeds | `real_property_master`, `real_property_legals`, `real_property_parties` |

---

## Side-by-Side Comparison Table

| Dimension | Evidentiary | Discovery | Divergence? |
|---|---|---|---|
| **Building coverage** | ~444K (violations-only; PLUTO enrichment is secondary) | ~858K (full PLUTO; violations are secondary events) | YES — critical |
| **Building MERGE key** | `bbl` (STRING) | `bbl` (STRING) | Identical |
| **BBL construction (missing)** | Python: `boroid.zfill(1)+block.zfill(5)+lot.zfill(4)` and SQL inline version | SQL: `trim(boroid)||lpad(block,5,'0')||lpad(lot,4,'0')` | Equivalent but differently expressed |
| **Borough derivation** | String map on source borough field (HPD/DOB/ECB text) | First digit of BBL → `BOROUGH_FROM_BBL` dict | YES — source-dependent vs. BBL-derived |
| **HPD event_id** | `EVT-HPD-<violationid>` | `EVT-HPD-<violationid>` | Identical |
| **DOB event_id** | `EVT-DOB-<number>` (string field) | `EVT-DOB-<isndobbisviol>` (numeric field) | YES — COLLISION. Different columns |
| **ECB event_id** | `EVT-ECB-<ecbviolationnumber>` | `EVT-ECB-<ecbviolationnumber>` | Identical |
| **Litigations event_id** | `EVT-HPD-LIT-<litigationid>` | `EVT-HPD-LIT-<litigationid>` | Identical |
| **Litigations source_name** | `'HPD-Litigations'` | `'HPD'` | YES — minor |
| **ACRIS event_id** | `EVT-ACRIS-<documentid>` (DEED + CORRD, since 2010) | `EVT-ACRIS-<documentid>` (all DEED%, any date) | Same scheme; different scope |
| **ACRIS parties** | Strings on Event node (no Actor nodes) | Actor nodes + PARTY_TO edges | YES — significant |
| **Marshal evictions** | Not ingested | `EVT-MARSHAL-<courtindex>-<docket>` | Discovery-only |
| **Actor key (landlord)** | `canonical_id = ACT-<uuid4>` (random, cross-run Jaccard matching) | `actor_id = ACT-<nodeid>` (deterministic, WoW nodeid) | YES — intentional (Principle 3) but prefix collision |
| **Actor key (managing agent)** | `canonical_id = MGT-<uuid5>` (stable) | Not ingested | Evidentiary-only |
| **Actor key (ACRIS)** | Not created (names as strings on Event) | `actor_id = ACT-ACRIS-<sha1>` | YES |
| **Actor labels** | `:Actor:WatchlineNode` (no sub-type label) | `:Actor:WatchlineNode:LandlordActor` or `:Actor:WatchlineNode` (ACRIS) | YES |
| **Portfolio/clustering output** | OwnershipNetwork Actors + PBC-001 Claims + BeneficialControl Relationships + ProbableAffiliation | Portfolio nodes + MEMBER_OF + IN_PORTFOLIO + APPARENT_CONTROL edges | YES — intentional |
| **Evidentiary overlay** | Source, Observation, IdentityObservation, IdentityAssertion, Evidence, Claim, Rule, Relationship (reified) | Not present | Intentional |
| **Graph type enforcement** | None (manual CONSTRAINT statements) | GQL graph type via ALTER CURRENT GRAPH TYPE SET | YES |
| **Neo4j database var** | `NEO4J_DATABASE` → fallback `"neo4j"` | `NEO4J_DATABASE` → fallback `"neo4j"` | Identical (both BROKEN by .env rename) |
| **fw/ connection vars** | `NEO4J_EPISTEMIC_URI/USER/PASSWORD/DATABASE` | N/A | Third distinct naming scheme |
| **PG source name in docstrings** | `deedwatch` | `wow` | YES — same source, different name |
| **PG connection vars** | `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` | Same | Identical |
| **Batching (buildings)** | 500 | 2000 | Differs (discovery 4× larger) |
| **Batching (events)** | 500 | 2000 | Differs |
| **Server-side cursor itersize** | 2000 (HPD violations) | 5000 (consistently) | Differs |
| **Shared config module** | Yes (`portfolio/config.py`; re-exported by agents + acris) | No (each pipeline defines own helpers) | YES |
| **Rent stabilization** | Ingested (Building property enrichment) | Not ingested | Evidentiary-only |
| **PHC-001 Claim evaluation** | Yes (phc001 pipeline) | No | Evidentiary-only |
