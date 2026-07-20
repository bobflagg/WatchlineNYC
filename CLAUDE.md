# CLAUDE.md — WatchlineNYC Development Guide

This file guides Claude Code when working on the WatchlineNYC project. Read it
fully before writing any code. It covers the two-graph architecture and
reconciliation principles, the evidentiary project philosophy, and detailed
specifications for implementing the remaining investigative intents.

---

## Repository Architecture — Two KGs, One Codebase

WatchlineNYC maintains two separate Neo4j knowledge graphs built from the same
source (WoW PostgreSQL, database `wow`, port 5434):

- **Discovery KG** (`discovery` database) — lean, fast, rebuildable. Full PLUTO
  building substrate (~858K lots). Ingestion: `watchline/discovery/ingest/`.
- **Evidentiary KG** (`evidentiary` database) — defensible, audited, versioned.
  Adds `Observation`, `Evidence`, `Claim`, `Rule`, and reified `Relationship`
  nodes on top of the discovery substrate. Ingestion: `watchline/evidentiary/ingest/`.

**The graphs are intentionally separate.** Never merge their storage.
Cross-graph bridging happens at query/agent time over conformed `Building.bbl`
and `Event.event_id` keys — not in the data layer.

### Target layout

```
watchline/
├── shared/              # Shared helpers: connections, BBL normalization, batch constants
├── discovery/           # Canonical building/event substrate + discovery overlay
│   ├── schema/          # graph_type.cypher — enforced via ALTER CURRENT GRAPH TYPE SET
│   └── ingest/          # buildings, hpd_violations, dob_violations, ecb_violations,
│                        # hpd_litigations, hpd_registrations, portfolio,
│                        # marshal_evictions, acris_deeds
├── evidentiary/         # Evidentiary overlay — builds on the discovery substrate
│   ├── schema/          # graph_type.cypher (authoritative, captured from live DB)
│   └── ingest/          # OwnershipNetwork (portfolio/), PHC-001 (phc001/),
│                        # managing agents (agents/), ACRIS overlay (acris/)
├── fw/                  # Evidentiary query framework (FastAPI + LangGraph)
└── ui/                  # Streamlit frontend
```

### Reconciliation principles

These govern all structural decisions. Cite the principle number in every ADR.

1. **Separate the overlays; conform the substrate.** Discovery and evidentiary
   reasoning layers differ intentionally. The domain substrate (`Building`,
   `Event`, raw facts) describes the same reality and must not diverge.
2. **`Building.bbl` and `Event.event_id` are the cross-graph vocabulary.**
   Identical in both graphs so a query-time join needs no transformation.
3. **Actor identity is intentionally different between the graphs.** Discovery
   holds raw, unresolved actors (namespaced keys); evidentiary holds resolved
   actors (IdentityAssertion + ResolutionMethod). Do not force a single model.
   Namespace keys explicitly so regimes never collide.
4. **Single `Event` supertype.** Discriminate via `event_type` and `source_name`.
5. **One source of truth for domain-fact ingestion.** Both graphs call the same
   discovery substrate pipelines for `Building` and `Event` ingestion.
6. **Graph types are the enforced schema.** Each graph has an authoritative
   `graph_type.cypher`. Schema changes go there first.
7. **Idempotency everywhere.** `MERGE` on stable business keys;
   `created_at`-if-null / `updated_at`-always; server-side cursors + `UNWIND`.
8. **Reconcile by principle, not by author.** Decide by the principles above;
   record every decision in `docs/decisions/ADR-000-skeleton.md`.
9. **Verify columns against the live schema before writing SQL.** Source of
   record is WoW PostgreSQL (`wow`, port 5434). Never assume column names.
10. **Quality gates.** Run `/code-review` on pipeline diffs (MERGE/idempotency);
    `security-review` on anything touching credentials or dynamic SQL.
11. **Leave the graphs agent-ready.** Stable documented query surfaces per graph;
    preserve the evidentiary provenance boundary (no discovery heuristic may
    appear in an evidentiary claim's justification chain).

### Canonical identifier conventions

| Key | Scheme | ADR |
|-----|--------|-----|
| `Building.bbl` | 10-digit string; borough from BBL first digit (not source string) | ADR-002 |
| HPD `event_id` | `EVT-HPD-{violationid}` | — |
| DOB `event_id` | `EVT-DOB-{isndobbisviol}` (not `number` — has duplicates) | ADR-003 |
| ECB `event_id` | `EVT-ECB-{ecbviolationnumber}` | — |
| HPD litigations | `EVT-HPD-LIT-{litigationid}`, `source_name='HPD-Litigations'` | ADR-004 |
| ACRIS `event_id` | `EVT-ACRIS-{documentid}` | — |
| Marshal `event_id` | `EVT-MARSHAL-{courtindexnumber}-{docketnumber}` | — |
| Discovery Actor (landlord) | `ACT-LL-{nodeid}` | ADR-006 |
| Discovery Actor (ACRIS) | `ACT-ACRIS-{sha1}` | ADR-006 |
| Evidentiary Actor (OwnershipNetwork) | `ACT-{uuid4}` | ADR-006 |
| Evidentiary Actor (ManagingAgent) | `MGT-{uuid5}` | ADR-006 |

### Decision log

All substrate divergence decisions: `docs/decisions/ADR-000-skeleton.md`.
Read before making any structural change to `Building`, `Actor`, or `Event`
modeling. If a decision contradicts this table, the ADR takes precedence.

---

## Project Philosophy

WatchlineNYC is accountability infrastructure for NYC housing enforcement. Every
architectural decision flows from one principle: **answers must be defensible,
not merely plausible**. This means:

- Claims are produced by named, versioned Rules — never by LLM reasoning
- Every conclusion is traceable to primary source records
- Uncertainty is represented explicitly (Interpretive Status: Observed, Derived,
  Inferred, Stipulated, Disputed) — never hidden
- The LLM is called exactly twice per pipeline run: once to extract intent,
  once to narrate results (Charter Principle 17)

Never write code that has the LLM produce a conclusion directly. The LLM
explains what the graph found. The graph does the reasoning.

---

## Repository Structure (Evidentiary Layer)

The sections below describe the evidentiary query framework and overlay
ingestion pipelines. For the full two-graph layout see the Repository
Architecture section above.

```
watchline/
├── fw/                         # Evidentiary query framework (FastAPI + LangGraph)
│   ├── investigator.py         # LangGraph graph definition only — keep slim
│   ├── state.py                # WatchlineState TypedDict
│   ├── connections.py          # get_llm(), neo4j_query(), normalize_address()
│   ├── resolver.py             # resolve_building(), resolve_actor()
│   ├── intent.py               # identify_intent node + INTENT_SYSTEM_PROMPT
│   ├── router.py               # select_rules, execute_traversal, routing fns
│   ├── narrator.py             # present_results node + PRESENT_SYSTEM_PROMPT
│   ├── renderer.py             # render_dashboard node + panel dispatch
│   ├── server.py               # FastAPI SSE endpoints
│   ├── explorer.py             # DeedWatch conversational agent (separate)
│   ├── intents/
│   │   ├── base.py             # IntentHandler ABC
│   │   ├── deterioration.py    # DT-001 — FULLY IMPLEMENTED
│   │   ├── stubs.py            # Stub handlers for unimplemented intents
│   │   └── __init__.py         # REGISTRY dict — update when adding intents
│   └── templates/
│       ├── base.html           # Shared dashboard chrome + tab structure
│       ├── logo_b64.txt        # Base64-encoded logo — injected into dashboard header
│       ├── watchline.css       # Single CSS source — injected inline at render
│       └── intents/
│           ├── deterioration.html   # DT-001 panels — FULLY IMPLEMENTED
│           └── stub.html            # Fallback for unimplemented intents
├── evidentiary/
│   ├── schema/                 # graph_type.cypher — authoritative evidentiary schema
│   └── ingest/                 # Evidentiary overlay pipelines
│       ├── portfolio/          # OwnershipNetwork detection (WCC + Louvain)
│       │   ├── config.py       # PG + Neo4j connection helpers (reads NEO4J_EVIDENTIARY_DATABASE)
│       │   ├── load.py         # PostgreSQL → Landlord nodes + edges
│       │   ├── store.py        # GDS → OwnershipNetwork Actors + Claims
│       │   ├── algorithms.py   # WCC + recursive Louvain splitting
│       │   ├── pipeline.py     # Entry point: --step init/load/store/reconcile
│       │   └── sql/
│       │       └── landlords_with_connections.sql
│       ├── agents/             # ManagingAgent ingestion
│       │   ├── config.py       # Re-exports portfolio.config
│       │   ├── load.py         # wow_bldgs.allcontacts → deduped agent list
│       │   ├── store.py        # ManagingAgent Actors + ManagedBy Relationships
│       │   └── pipeline.py     # Entry point: --step load/store
│       ├── hpd_violations/     # HPD violation events (temporary — will call discovery substrate)
│       ├── dob_violations/     # DOB violation events (temporary — will call discovery substrate)
│       ├── ecb_violations/     # ECB/OATH judgment events (temporary)
│       ├── hpd_litigations/    # HPD housing court filings (temporary)
│       ├── rentstab/           # DHCR rent stabilization data (temporary)
│       ├── acris/              # ACRIS deed transfers with evidentiary overlay
│       └── phc001/             # PHC-001 Rule evaluation pipeline
│           └── pipeline.py     # Queries graph, writes PersistentHazardousConditions Claims
└── ui/                         # Frontend (Streamlit)
    ├── app.py                  # Main app — handles SSE stream + dashboard render
    └── sidebar.py              # Mode selector, sample questions, model picker
```

---

## Adding a New Intent — The Pattern

Every intent follows the same four-step pattern. Do not deviate.

### Step 1: Create `watchline/fw/intents/<name>.py`

```python
from watchline.fw.intents.base import IntentHandler

class MyIntentHandler(IntentHandler):
    intent_category = "MyIntent"   # must match INTENT_SYSTEM_PROMPT exactly
    entity_class    = "building"   # or "actor"

    def get_cypher(self) -> str:
        return _CYPHER             # module-level constant

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}   # or {"canonical_id": intent["canonical_id"]}

    def evaluate(self, raw_results: list) -> dict | None:
        # Return a rule_evaluation dict if a formal Rule applies, else None
        return None
```

Rules for `evaluate()`:
- Return `None` for pure data-retrieval intents (no rule to evaluate)
- When a rule applies, always include: `rule_id`, `rule_version`,
  `interpretive_status`, `threshold_statement`, `insufficient_data`
- `threshold_statement` must be quoted verbatim in the narrator output

### Step 1b: Register the Rule in the graph (Charter §11 + §15)

If your intent applies a named Rule, you must create a `Rule` node in the
epistemic Neo4j database **before** writing any Python. Rules are ontological
objects, not code. A rule that exists only in Python violates the Charter.

Required Rule node properties (match the schema of existing Rule nodes):

```cypher
MERGE (r:Rule:WatchlineNode:AuditableRecord:VersionedObject {rule_id: "RUL-000XX"})
SET r += {
  name:                     "XX-001",          // short code e.g. "FE-001"
  title:                    "Full Rule Title",
  version:                  "1.0",
  interpretive_concept:     "MyIntentConcept", // matches intent_category
  effective_date:           "YYYY-MM-DD",
  author:                   "Watchline NYC project team",
  deprecated:               false,
  authority:                "...",             // legal/methodological basis
  threshold_description:    "...",             // plain-language threshold
  threshold_logic:          "...",             // formal logic expression
  input_types:              "...",             // e.g. "Building|Event[HPD Violation]"
  output_interpretive_status: "Inferred",
  explanation_template:     "...",             // template for claim_text
  falsification_conditions: "...",             // what would overturn this rule
  amendment_notes:          "..."              // rationale for initial thresholds
}
```

After running the Cypher, verify with:
```cypher
MATCH (r:Rule {rule_id: "RUL-000XX"}) RETURN r
```

Then update your handler's `evaluate()` to call `_load_rule_from_graph()` 
(follow the pattern in `deterioration.py`) so the threshold statement and
metadata are read from the graph at runtime, not hardcoded in Python.

Increment `RUL-000XX` from the current highest rule_id in the graph.
Current highest as of July 2026: `RUL-00014` (OC-001) — corrected 2026-07-16;
see the full "Rules in the graph" table below for all 14.

### Step 2: Create `watchline/fw/templates/intents/<name>.html`

- Use `%%SECTIONNAME%%` markers (e.g. `%%EVIDENCE%%`, `%%RULES%%`) to delimit sections
- **Critical:** Do NOT use `%%` anywhere else in the file — not in comments,
  not in examples. The renderer splits on `%%` literally.
- Write marker names in a known set only: `EVIDENCE`, `RULES`
- If in doubt, write the file in Python rather than a shell heredoc to avoid
  `%%` escaping issues (see renderer.py for the pattern)
- Summary panel is built entirely in renderer.py — do not include it here

### Step 3: Register in `watchline/fw/intents/__init__.py`

```python
from watchline.fw.intents.myintent import MyIntentHandler
# Add to the list in REGISTRY
```

Remove the corresponding stub from `stubs.py`.

### Step 4: Add a panel renderer to `renderer.py`

```python
def _render_myintent(tr: dict, prose: str) -> dict:
    tmpl = _intent_tmpl("myintent")
    sections = tmpl.split("%%")
    _KNOWN = {"EVIDENCE", "RULES"}
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN:
            tmpl_map[key] = sections[i + 1]
    # ... populate placeholders ...
    return {
        "SUMMARY_PANEL": f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": tmpl_map.get("EVIDENCE", ""),
        "RULES_PANEL":    tmpl_map.get("RULES", ""),
    }

# Add to _PANEL_RENDERERS dict
_PANEL_RENDERERS = {
    "DeteriorationTrajectory": _render_deterioration,
    "MyIntent":                _render_myintent,
}
```

---

## Neo4j Graph — What's Available

**Connection:** via `neo4j_query()` in `connections.py`. Credentials in `.env`.

**Node types:** Building, Actor, Event, Relationship, Claim, Observation,
Evidence, Source, IdentityObservation, IdentityAssertion, Rule,
ResolutionMethod, InvestigativeIntent, CanonicalQuestion

**Key Event properties by type:**

| event_type  | source_name      | Key properties |
|-------------|-----------------|----------------|
| Violation   | HPD             | violation_class (A/B/C), status (Open/Closed), open_date, current_status_date, current_status, description, violation_code |
| Violation   | DOB             | status (Active/Resolved), open_date, description |
| Judgment    | ECB             | penalty_imposed, amount_paid, balance_due, hearing_status, infraction_codes, issue_date, violation_description |
| CourtFiling | HPD-Litigations | case_type, status, finding_of_harassment, is_harassment_finding, open_judgement, respondent |

**Key Building properties:** bbl, address, borough, bin, residential_units,
building_class, year_built, latitude, longitude, rs_units_current,
rs_units_2018..2023, rs_units_change, rs_deregulating, rs_pdfsoa_2023

**Key Actor properties:** canonical_id, display_name, actor_type

**Key Relationship properties:** relationship_type (BeneficialControl,
ProbableAffiliation), involves_building →, involves_actor →

**Key Claim properties:** claim_id, subject_id, subject_type (Building,
OwnershipNetwork), interpretive_concept (PersistentHazardousConditions,
ProbableBeneficialControl), interpretive_status, claim_text

**Existing Rules in graph** (all 14; see "Current Graph State" below for
implementation status per rule):
- RUL-00001: PersistentHazardousConditions (PHC-001) — ≥3 open Class C, oldest >180 days
- RUL-00002: ProbableBeneficialControl (PBC-001) — shared address/name connections
- RUL-00003: NameBasedOwnershipConnection (RMT-001)
- RUL-00004: AddressBasedOwnershipConnection (RMT-002)
- RUL-00005: CandidateOwnershipNetwork (RMT-003 — Weakly Connected Components)
- RUL-00006: RefinedOwnershipNetwork (RMT-004 — Louvain Community Detection)
- RUL-00007: DeteriorationTrajectory (DT-001) — rising violations + falling resolution rate
- RUL-00008: NetworkExposure (NE-001) — ProbableAffiliation between split WCC siblings
- RUL-00009: ManagementDifferential (MA-001) — stub, no handler or pipeline yet
- RUL-00010: RentStabilizationLoss (RS-001) — falling RS units + active deregistration
- RUL-00011: FineEvasion (FE-001) — outstanding ECB/OATH balance over $10,000
- RUL-00012: EnforcementAccountabilityGap (EA-001) — long-open Class C, no court filing
- RUL-00013: Recidivism (RCV-001) — multi-borough or multi-year persistent Class C
- RUL-00014: OwnershipChangeDeterioration (OC-001) — violation rate jump after arm's-length deed transfer

**Cypher date notes:**
- `open_date` is a native date type — use `e.open_date.year` for year extraction
- Use `duration.inDays(date1, date2).days` for total elapsed days (not
  `duration.between().days` which returns the days component only)
- `current_status_date` is the resolution date for closed HPD violations
  (`closed_date` is always null)

---

## Remaining Intents — Implementation Specifications

### 1. PortfolioIdentification
**Question:** Who actually controls this building?

**Entity class:** building  
**Rule:** RUL-00002 (ProbableBeneficialControl / PBC-001)

**Cypher approach:**
1. Look up BeneficialControl Relationship nodes involving the building
2. Follow to Actor node(s)
3. Fetch the ProbableBeneficialControl Claim for that actor
4. Return actor name, canonical_id, portfolio size, confidence, claim_text

```cypher
MATCH (b:Building {bbl: $bbl})
MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_BUILDING]->(b)
MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)
OPTIONAL MATCH (c:Claim {
  interpretive_concept: "ProbableBeneficialControl",
  subject_id: a.canonical_id
})
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions",
  subject_id: b.bbl
})
RETURN a.display_name      AS controller_name,
       a.canonical_id      AS controller_id,
       a.actor_type        AS actor_type,
       c.claim_text        AS pbc_claim,
       c.interpretive_status AS interpretive_status,
       phc IS NOT NULL     AS building_has_phc
```

**evaluate():** Not needed — claim_text carries the rule citation already.  
**Dashboard Evidence tab:** Actor name, portfolio size (from claim_text), 
connection type (address/name-based), confidence.  
**Dashboard Rules tab:** RUL-00002 metadata + claim_text quoted verbatim.

---

### 2. BuildingDueDiligence
**Question:** What is the full record on this building?

**Entity class:** building  
**Rule:** None (data retrieval only)

**Cypher approach:** Single query returning violation summary, court filings,
ECB judgments, and ownership — aggregated, not raw rows.

```cypher
MATCH (b:Building {bbl: $bbl})

// Violation summary by class and status
OPTIONAL MATCH (b)-[:HAS_EVENT]->(v:Event {event_type: "Violation", source_name: "HPD"})
WITH b,
  sum(CASE WHEN v.violation_class = "C" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_c,
  sum(CASE WHEN v.violation_class = "B" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_b,
  sum(CASE WHEN v.violation_class = "A" AND v.status = "Open" THEN 1 ELSE 0 END) AS open_a,
  count(DISTINCT v) AS total_violations

// Court filings
OPTIONAL MATCH (b)-[:HAS_EVENT]->(cf:Event {event_type: "CourtFiling"})
WITH b, open_c, open_b, open_a, total_violations,
  count(DISTINCT cf) AS total_filings,
  sum(CASE WHEN cf.status = "OPEN" THEN 1 ELSE 0 END) AS open_filings,
  sum(CASE WHEN cf.is_harassment_finding = true THEN 1 ELSE 0 END) AS harassment_findings

// ECB judgments
OPTIONAL MATCH (b)-[:HAS_EVENT]->(ecb:Event {event_type: "Judgment", source_name: "ECB"})
WITH b, open_c, open_b, open_a, total_violations,
  total_filings, open_filings, harassment_findings,
  count(DISTINCT ecb) AS total_ecb,
  sum(CASE WHEN ecb.balance_due > 0 THEN ecb.balance_due ELSE 0 END) AS total_balance_due

// PHC claim
OPTIONAL MATCH (phc:Claim {interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl})

// Ownership
OPTIONAL MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_BUILDING]->(b)
OPTIONAL MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor)

RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
       b.residential_units AS residential_units, b.year_built AS year_built,
       b.building_class AS building_class,
       b.rs_units_current AS rs_units_current, b.rs_deregulating AS rs_deregulating,
       open_c, open_b, open_a, total_violations,
       total_filings, open_filings, harassment_findings,
       total_ecb, total_balance_due,
       phc.claim_text AS phc_claim,
       a.display_name AS controller_name,
       a.canonical_id AS controller_id
```

**evaluate():** Return None.  
**Dashboard Evidence tab:** Summary cards — Open C/B/A violations, court filings,
ECB balance, PHC status, controller. Clean grid layout, not a raw table.

---

### 3. FineEvasion
**Question:** Does this landlord have outstanding ECB fines?

**Entity class:** building or actor  
**Rule:** Define FE-001: an actor has outstanding ECB balance > $0 across 
≥2 buildings, or a single building has balance > $10,000.

**Key ECB properties:** `penalty_imposed`, `amount_paid`, `balance_due`,
`hearing_status`, `violation_description`, `infraction_codes`

**Cypher (building-level):**
```cypher
MATCH (b:Building {bbl: $bbl})-[:HAS_EVENT]->(e:Event {
  event_type: "Judgment", source_name: "ECB"
})
WITH b, e
WHERE e.balance_due IS NOT NULL
RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
  count(e) AS total_judgments,
  sum(CASE WHEN e.balance_due > 0 THEN 1 ELSE 0 END) AS judgments_with_balance,
  sum(CASE WHEN e.balance_due > 0 THEN e.balance_due ELSE 0 END) AS total_balance_due,
  sum(e.penalty_imposed) AS total_penalties_imposed,
  sum(e.amount_paid) AS total_paid,
  collect(CASE WHEN e.balance_due > 0 THEN {
    date: e.issue_date,
    description: e.violation_description,
    penalty: e.penalty_imposed,
    paid: e.amount_paid,
    balance: e.balance_due,
    status: e.hearing_status
  } END) AS outstanding_items
```

**evaluate():** Apply FE-001 threshold. Return `evasion_flagged: bool`,
`total_balance_due`, `judgment_count`, `threshold_statement`.

---

### 4. RentStabilization
**Question:** Is this building losing rent-stabilized units?

**Entity class:** building  
**Rule:** Define RS-001: a building is deregulating if rs_units_change < 0
over the available history AND rs_deregulating flag is true.

**Key Building properties available:** rs_units_2018, rs_units_2019,
rs_units_2020, rs_units_2021, rs_units_2022, rs_units_2023, rs_units_current,
rs_units_change, rs_deregulating

**Cypher:**
```cypher
MATCH (b:Building {bbl: $bbl})
RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
  b.residential_units AS residential_units,
  b.rs_units_2018 AS rs_2018, b.rs_units_2019 AS rs_2019,
  b.rs_units_2020 AS rs_2020, b.rs_units_2021 AS rs_2021,
  b.rs_units_2022 AS rs_2022, b.rs_units_2023 AS rs_2023,
  b.rs_units_current AS rs_current,
  b.rs_units_change AS rs_change,
  b.rs_deregulating AS rs_deregulating,
  b.rs_pdfsoa_2023 AS pdfsoa_url
```

**evaluate():** Return RS-001 evaluation: `deregulating` bool, `units_lost`,
`pct_lost`, `earliest_year`, `latest_year`, `threshold_statement`.  
**Dashboard Evidence tab:** Year-by-year RS unit count table with a trend
indicator column (↑↓ per year), total units lost, percentage lost.  
**Note:** `rs_pdfsoa_2023` is a PDF Statement of Account URL — link it in
the Evidence tab as a primary source citation.

---

### 5. PortfolioCondition
**Question:** How bad is this landlord's record across all their buildings?

**Entity class:** actor  
**Rule:** Uses RUL-00001 (PHC-001) — count buildings satisfying PHC

**Cypher:**
```cypher
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(b:Building)
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions",
  subject_id: b.bbl
})
OPTIONAL MATCH (pbc:Claim {
  interpretive_concept: "ProbableBeneficialControl",
  subject_id: a.canonical_id
})
WITH a, pbc, b, phc
RETURN a.display_name AS name,
  a.canonical_id AS canonical_id,
  pbc.claim_text AS pbc_claim,
  count(DISTINCT b.bbl) AS portfolio_size,
  count(DISTINCT CASE WHEN phc IS NOT NULL THEN b.bbl END) AS phc_buildings,
  collect(DISTINCT CASE WHEN phc IS NOT NULL THEN {
    bbl: b.bbl, address: b.address, borough: b.borough,
    units: b.residential_units, claim: phc.claim_text
  } END) AS phc_building_list
```

**evaluate():** Return PHC rate (`phc_buildings / portfolio_size`), flag if > 50%.  
**Dashboard Evidence tab:** Portfolio summary card + sortable table of PHC
buildings with address, borough, unit count.

---

### 6. Recidivism
**Question:** Has this landlord let hazardous conditions persist repeatedly?

**Entity class:** actor  
**Rule:** Define RCV-001: actor has PHC-flagged buildings in >1 borough OR
has had PHC conditions for >3 consecutive years across their portfolio.

**Cypher approach:** For each building in portfolio, get annual Class C
open counts (same trajectory query as DT-001 but aggregated across all
buildings). Identify buildings with multi-year persistent open violations.

This is the most complex intent. Suggested approach:
1. First query: get all BBLs in actor's portfolio
2. Second query (with collected BBLs): aggregate PHC trajectory across portfolio
3. Python rule evaluation: identify multi-year persistence patterns

**evaluate():** Return `recidivist` bool, `affected_buildings` list,
`persistence_years` per building, `threshold_statement` for RCV-001.

---

### 7. EnforcementAccountability
**Question:** Is HPD following up on violations at this building?

**Entity class:** building  
**Rule:** Define EA-001: building has ≥3 open Class C violations older than
365 days with no associated CourtFiling in the same period.

**Cypher:**
```cypher
MATCH (b:Building {bbl: $bbl})

// Long-open Class C violations
MATCH (b)-[:HAS_EVENT]->(v:Event {
  event_type: "Violation", source_name: "HPD",
  violation_class: "C", status: "Open"
})
WHERE v.open_date IS NOT NULL
  AND duration.inDays(v.open_date, date()).days > 365

// Court filings in same period
OPTIONAL MATCH (b)-[:HAS_EVENT]->(cf:Event {event_type: "CourtFiling"})
WHERE cf.event_date >= v.open_date

WITH b,
  count(DISTINCT v) AS long_open_c,
  count(DISTINCT cf) AS court_actions_in_period,
  collect({
    date: v.open_date,
    days_open: duration.inDays(v.open_date, date()).days,
    description: v.description
  }) AS stale_violations

RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
  long_open_c, court_actions_in_period, stale_violations
```

**evaluate():** Apply EA-001. Return `accountability_gap` bool, 
`long_open_c_count`, `court_actions`, `threshold_statement`.

---

### 8. WorstFirst
**Question:** Which landlords should be investigated first?

**Entity class:** actor (no specific entity — dataset-level query)  
**Special case:** This intent has no named entity. The intent extractor will
return `entity_type: "Unknown"`. The router's clarification gate normally
fires for Unknown — add a special case: if `intent_category == "WorstFirst"`,
bypass entity resolution and run the dataset-level query directly.

**Cypher:** Rank actors by PHC building count, weighted by portfolio size.
```cypher
MATCH (c:Claim {
  interpretive_concept: "ProbableBeneficialControl",
  subject_type: "OwnershipNetwork"
})
MATCH (a:Actor {canonical_id: c.subject_id})
MATCH (rel:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
MATCH (rel)-[:INVOLVES_BUILDING]->(b:Building)
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions",
  subject_id: b.bbl
})
WITH a, count(DISTINCT b.bbl) AS portfolio_size,
  count(DISTINCT CASE WHEN phc IS NOT NULL THEN b.bbl END) AS phc_count
WHERE portfolio_size >= 5
RETURN a.display_name AS name, a.canonical_id AS canonical_id,
  portfolio_size, phc_count,
  toFloat(phc_count) / portfolio_size AS phc_rate
ORDER BY phc_count DESC
LIMIT 20
```

**evaluate():** None — ranking is the output.  
**router.py change required:** Add to `select_rules()`:
```python
if intent_cat == "WorstFirst":
    # No entity resolution needed — dataset-level query
    return {
        "needs_clarification": False,
        "traversal_results": {
            "handler": handler,
            "traversal_type": handler.traversal_key(),
            "params": {},
            "resolved_entity": None,
        }
    }
```

---

### 9. ConcealmentDetection
**Question:** Is someone using LLCs or name variations to hide their identity?

**Entity class:** actor  
**Rule:** Uses RUL-00003/RUL-00004 (name/address connection rules). High
concealment signal = connections primarily address-based (not name-based).

**Cypher:** Fetch IdentityObservation and IdentityAssertion nodes for the actor.
```cypher
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (ia:IdentityAssertion)-[:INVOLVES_ACTOR]->(a)
OPTIONAL MATCH (io:IdentityObservation)-[:SUPPORTS]->(ia)
RETURN a.display_name AS name, a.canonical_id AS canonical_id,
  count(DISTINCT io) AS observation_count,
  collect(DISTINCT {
    type: io.observation_type,
    value: io.observed_value,
    source: io.source_name
  }) AS observations,
  ia.assertion_type AS assertion_type,
  ia.confidence AS confidence
```

**Note:** Also query the PBC claim_text — it includes shared address vs name
connection counts which are the primary concealment signals.  
**evaluate():** Flag if address-based connections > 10x name-based connections.

---

### 10. GeographicConcentration
**Question:** Are there clusters of troubled buildings in a neighborhood?

**Entity class:** unknown/geographic (no named entity)  
**Special case:** Like WorstFirst, bypass entity resolution. The intent
extractor should return a borough or neighborhood name in `entity_raw`.

**Cypher:** Group PHC buildings by community district or NTA.
```cypher
MATCH (c:Claim {interpretive_concept: "PersistentHazardousConditions"})
MATCH (b:Building {bbl: c.subject_id})
WHERE ($borough IS NULL OR b.borough = $borough)
RETURN b.borough AS borough,
  count(DISTINCT b.bbl) AS phc_building_count,
  sum(b.residential_units) AS affected_units
ORDER BY phc_building_count DESC
LIMIT 20
```

**Note:** Geographic clustering requires lat/lon — Building nodes have
`latitude` and `longitude`. A future version could use spatial clustering.
For now, borough/community-district aggregation is sufficient.

---

### 11. OwnershipChange
**Question:** Did conditions change after this building was sold?

**Data constraint:** The current graph does not store historical HPD registration
snapshots — only current registrations. This intent is **data-constrained** and
should remain a stub until historical registration data is ingested.

When implementing, the approach will be:
1. Detect registration changes from IdentityObservation timestamps
2. Compare violation trajectory before/after the change date
3. Apply DT-001-style signal evaluation to each period separately

Do not implement this intent until historical registration data is confirmed
available in the graph.

---

### 13. NetworkExposure
**Question:** Are two or more apparently separate landlords actually operating as a coordinated network, and what does their combined record look like?

**Why this is novel:** JustFix clusters buildings under a single inferred owner using shared HPD registration data. It cannot model actor-to-actor affiliations — so a journalist looking at Michael Bennett in JustFix sees 175 buildings. They would never see that Ryan Hiller's 141 buildings are part of the same probable network: 316 buildings combined, 124 with persistent hazardous conditions. Watchline surfaces this because it models ProbableAffiliation relationships between Actor nodes — a graph-native construct that requires traversing actor-to-actor edges, then fanning out to each actor's portfolio, then aggregating.

**Entity class:** actor (one named actor; affiliates are discovered from the graph)

**Rule:** Define NE-001: two or more actors form a probable coordinated network if they are connected by ProbableAffiliation relationships derived from shared WCC component membership (RUL-00005/RUL-00006). The combined PHC rate across the unified portfolio is the primary accountability signal.

**Graph structure:** ProbableAffiliation Relationship nodes connect Actor nodes and carry:
- `basis`: text describing the WCC component that originally connected the networks
- `interpretive_status`: "Inferred"
- `effective_from`: date the affiliation was asserted

**Cypher:**
```cypher
MATCH (a:Actor {canonical_id: $canonical_id})
MATCH (aff:Relationship {relationship_type: "ProbableAffiliation"})
MATCH (aff)-[:INVOLVES_ACTOR]->(a)
MATCH (aff)-[:INVOLVES_ACTOR]->(affiliated:Actor)
WHERE affiliated.canonical_id <> a.canonical_id

WITH a, collect(DISTINCT affiliated) AS affiliates,
     collect(DISTINCT aff.basis) AS affiliation_bases,
     [a] + collect(DISTINCT affiliated) AS all_actors

UNWIND all_actors AS member
MATCH (bc:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(member)
MATCH (bc)-[:INVOLVES_BUILDING]->(b:Building)
OPTIONAL MATCH (phc:Claim {
  interpretive_concept: "PersistentHazardousConditions", subject_id: b.bbl
})
OPTIONAL MATCH (pbc:Claim {
  interpretive_concept: "ProbableBeneficialControl", subject_id: member.canonical_id
})
RETURN member.display_name           AS actor_name,
       member.canonical_id           AS actor_id,
       member.canonical_id = a.canonical_id AS is_named_actor,
       count(DISTINCT b.bbl)         AS portfolio_size,
       count(DISTINCT phc.claim_id)  AS phc_buildings,
       sum(b.residential_units)      AS total_units,
       left(pbc.claim_text, 300)     AS pbc_summary,
       affiliation_bases[0]          AS affiliation_basis
ORDER BY portfolio_size DESC
```

**evaluate():** Apply NE-001. Return `network_size`, `combined_portfolio`, `combined_phc`, `combined_units`, `combined_phc_rate`, `affiliation_basis`, `confidence: "Medium"`, `threshold_statement`, `insufficient_data: True if network_size < 2`.

**Threshold statement for NE-001:**
"Two or more actors satisfy Watchline Rule NE-001 (Network Exposure) if they are connected by ProbableAffiliation relationships derived from shared Weakly Connected Component membership in HPD registration data (RUL-00005 and RUL-00006). This is a weaker signal than Probable Beneficial Control: it indicates that the two ownership networks were originally part of the same registration graph before community detection split them. Confidence is Medium. A different community detection threshold would produce a different network boundary."

**Dashboard Evidence tab:** Table of each actor with individual portfolio size, PHC count, and unit total. Combined summary row at the bottom. Affiliation basis quoted verbatim as primary source citation.

**Dashboard Rules tab:** NE-001 metadata. Plain-language explanation of WCC and Louvain community detection. Explicit confidence caveat distinguishing ProbableAffiliation (weaker) from BeneficialControl (stronger).

**Critical narrator instruction:** Never present the combined portfolio as a single proven ownership structure. Clearly distinguish what is Inferred from PBC-001 (each actor's individual portfolio) from what is additionally Inferred from NE-001 (that the two networks are affiliated).

**Graph registration:** Register as RUL-00008 before implementing, using the pattern in `register_dt001.cypher`.

**Known limitation — management-mediated bridges:**
ProbableAffiliation edges can be false positives when the WCC link between two
networks is mediated primarily through a high-degree address belonging to a
property management company rather than a common owner. The Michael Bennett /
Ryan Hiller affiliation (July 2026) is a confirmed example: investigation
determined the connection was an artifact of shared management infrastructure,
not common ownership. NE-001 correctly surfaced it as a lead; investigation
correctly resolved it. The epistemic discipline works, but signal-to-noise
would improve with the following ingestion-time refinement.

**Required ingestion-time refinement (not yet implemented):**
When the WCC/Louvain pipeline creates ProbableAffiliation relationships, each
relationship must be evaluated for management mediation before being written to
the graph:

1. For each ProbableAffiliation edge, identify the bridging IdentityObservation
   records — the specific shared address or name records whose graph edges connect
   the two WCC components.
2. For each bridging address, query its degree: how many distinct buildings in the
   graph share that address in HPD registration records.
3. If the sole or dominant bridge passes through an address with degree above a
   calibration threshold (suggested starting point: 50 distinct buildings), set
   `management_mediated: true` on the ProbableAffiliation relationship node.
4. Update NE-001 `evaluate()` to suppress or downgrade (confidence: Low) any
   affiliation where `management_mediated` is true.
5. The degree threshold must be calibrated against a labeled set of known
   management company addresses before deployment. Document the threshold and
   calibration rationale as an amendment to RUL-00008.

Until this refinement is implemented, NE-001 results must be treated as
preliminary leads requiring investigation, not findings. This is already
reflected in the narrator instructions and the Rules tab epistemic note.

---
## Narrator Guidelines

The narrator system prompt (`narrator.py`) forbids all Markdown. Enforce this:
- No `**bold**`, `*italic*`, `##` headings, `---` dividers, `> blockquotes`
- No bullet points or numbered lists
- No backticks or code formatting
- Plain sentences and paragraphs only

The LLM will try to use Markdown anyway. `_prose_to_html()` in `renderer.py`
strips common Markdown artifacts as a safety net, but fix at source (narrator
prompt) rather than relying on the strip.

The narrator must always:
1. State the Rule ID and whether it was satisfied
2. State interpretive_status (Inferred/Observed/Stipulated/Disputed)
3. Name the source agency for every data point
4. Quote `threshold_statement` verbatim when a rule fires
5. End with the epistemic disclaimer

---

## Dashboard Template Rules

- `%%` is the section delimiter — never use it in comments or examples
- Write templates in Python (`fw/intents/base.py` style) if heredoc issues arise
- The renderer splits on `%%` and accepts only `EVIDENCE` and `RULES` as keys
- Summary panel is always built in Python from prose — never in the template
- CSS changes go in `templates/watchline.css` — never inline in templates
- Design tokens: navy `#0a1629`, gold `#d4a017`, body `#2b2b2b`, bg `#f8f9fb`
- Fonts: Inter (body), Fraunces (display/headers) — loaded via Google Fonts

---

## Current Graph State (July 2026)

The epistemic KG was last fully rebuilt in July 2026. Current node counts:

| Label | Count | Source |
|-------|-------|--------|
| Event (HPD violations) | 11.1M | `make hpd` |
| Event (DOB violations) | 2.5M | `make dob` |
| Event (ECB judgments) | 1.8M | `make ecb` |
| Event (HPD litigations) | 239K | `make hpd-lit` |
| Building | 444K | derived from HPD |
| Actor (OwnershipNetwork) | 7,707 | `make portfolio` |
| Actor (ManagingAgent) | 76,697 | `make agents` |
| Claim (PHC-001) | 41,897 | `make phc001` |
| Claim (PBC-001) | 3,365 | `make portfolio` |
| Rule | 14 | `make seed-rules` |

**Rules in the graph** (corrected 2026-07-16 — this table previously stopped at RUL-00009 and was stale; verified against live `MATCH (r:Rule) RETURN ...` and against each `_GRAPH_RULE_ID` constant in `watchline/fw/intents/*.py`):

| Rule ID | Name | Title | Status |
|---------|------|-------|--------|
| RUL-00001 | PHC-001 | Persistent Hazardous Conditions | Active — batch-evaluated by `make phc001`, writes Claims |
| RUL-00002 | PBC-001 | Probable Beneficial Control | Active — batch-evaluated by `make portfolio`, writes Claims |
| RUL-00003 | RMT-001 | HPD Name-Based Connection | Active — Identity layer, used in portfolio load/matching |
| RUL-00004 | RMT-002 | HPD Address-Based Connection | Active — Identity layer, used in portfolio load/matching |
| RUL-00005 | RMT-003 | WCC Portfolio Detection | Active — Identity layer, `algorithms.py` |
| RUL-00006 | RMT-004 | Louvain Community Splitting | Active — Identity layer, `algorithms.py` |
| RUL-00007 | DT-001 | Deterioration Trajectory | Active — evaluated at query time by `fw/intents/deterioration.py` |
| RUL-00008 | NE-001 | Network Exposure | Active — evaluated at query time by `fw/intents/network_exposure.py` |
| RUL-00009 | MA-001 | Management Differential | Stub — Rule node registered (deprecated=false) but no `fw/intents` handler exists and no evaluation pipeline has been built; still the one true stub in this table |
| RUL-00010 | RS-001 | Rent Stabilization Loss | Active — evaluated at query time by `fw/intents/rent_stabilization.py` |
| RUL-00011 | FE-001 | Fine Evasion | Active — evaluated at query time by `fw/intents/fine_evasion.py` |
| RUL-00012 | EA-001 | Enforcement Accountability Gap | Active — evaluated at query time by `fw/intents/enforcement_accountability.py` |
| RUL-00013 | RCV-001 | Recidivism | Active — evaluated at query time by `fw/intents/recidivism.py` |
| RUL-00014 | OC-001 | Ownership Change Deterioration | Active — evaluated at query time by `fw/intents/ownership_change.py`. Note: this contradicts the "OwnershipChange is data-constrained" guidance later in this file (Remaining Intents §11) — the handler is registered and implemented despite that guidance saying it should remain a stub pending ACRIS history. Not reconciled as of this edit; see ADR-015. |

Rules with "evaluated at query time" status produce a `rule_evaluation` dict returned to the narrator per request (per the `IntentHandler.evaluate()` pattern) rather than persisting Claim nodes via a standalone batch pipeline the way PHC-001 and PBC-001 do — both are valid implementations of "Rules as first-class objects," just at different points in the pipeline.

**Next available rule ID:** `RUL-00015`

**Data sources not yet ingested** (see `next-steps.md` for specifications):
- OCA housing court data (`oca_index`, `oca_judgments`, `oca_warrants`, `oca_parties`)
- Marshal evictions (`marshal_evictions_all`)
- HPD vacate orders (`hpd_vacateorders`)
- ACRIS deed records (`real_property_master`, `real_property_parties`, `real_property_legals`)
- HPD complaints (`hpd_complaints_and_problems`)

---

## Testing a New Intent

1. Write a diagnostic Cypher query directly against Neo4j (via MCP or Neo4j
   Browser) to verify the data shape before writing Python
2. Add a smoke test to `scripts/diagnose.py` checking the full pipeline invoke
3. Test the natural-language question in the Streamlit app
4. Download the dashboard HTML and verify all four tabs have content

Good test questions:
- DeteriorationTrajectory: "Is 122 West 97th Street in Manhattan getting worse?"
- PortfolioIdentification: "Who controls 530 East 169th Street in the Bronx?"
- FineEvasion: "What are the ECB violations at 1459 Wythe Place Bronx?"
- RentStabilization: "Is 1380 White Plains Road Bronx losing rent stabilized units?"
- PortfolioCondition: "How many of Mark Engel's buildings have persistent hazardous conditions?"
- WorstFirst: "Who is the worst landlord in NYC?"
- NetworkExposure: "Is Michael Bennett connected to other landlords with bad records?"

---

## Common Pitfalls

**Don't use `duration.between().days`** — it returns the days component of a
Duration object, not total elapsed days. Use `duration.inDays(d1, d2).days`.

**Don't trust `closed_date`** — it is always null in HPD violation data. The
resolution date is `current_status_date`.

**Don't let the narrator produce conclusions** — it narrates what the graph
found. If `rule_evaluation` is absent, there is no rule conclusion to state.

**Don't skip the defensive section guard in renderer.py** — always filter
`tmpl_map` to only known section names. Stray `%%` will silently corrupt
panel assignment otherwise.

**Don't store handler objects in JSON** — strip the `handler` key from
`traversal_results` before passing to the narrator LLM call (see narrator.py).

**OwnershipChange is data-constrained** — the graph currently lacks deed transfer history. ACRIS data (`real_property_master`, `real_property_parties`, `real_property_legals`) is in the PostgreSQL source database and is the planned data source. See `next-steps.md` for the ingestion specification. Do not attempt to implement this intent until ACRIS ingestion is complete.

**Louvain resolution parameter** — Watchline uses the Neo4j GDS default
resolution of `1.0` (after the explicit parameter was removed in GDS 2026.x).
JustFix WOW uses `resolution=0.1`. This is why Watchline produces smaller,
tighter portfolio communities than WOW for the same input data — particularly
for large management company hubs like Brown Harris Stevens (770 Lexington Ave)
which WOW keeps as a single 446-building portfolio but Watchline splits into
sub-communities. This difference is intentional for Watchline's epistemic
goals (Probable Beneficial Control requires tighter evidence than portfolio
association) but should be documented as an explicit editorial choice if the
resolution parameter becomes configurable again. See `algorithms.py` comment.

**Register Rules in the graph before writing Python** — Charter §11 and §15
require every Rule to be a versioned graph object with author, authority,
thresholds, effective date, and falsification conditions. A Rule that exists
only as a Python constant violates the Charter. Run the MERGE Cypher first,
then write the handler. See the DT-001 registration in `register_dt001.cypher`
in the project scripts/ directory as the canonical example.

**Agents pipeline runs after HPD ingestion** — `make agents` creates
ManagedBy Relationship nodes that join ManagingAgent Actors to Building nodes.
Building nodes must already exist (created by HPD violations ingestion) before
agents can be run. The correct build order is enforced by `make build` but
if running steps manually: `hpd` before `agents`.

**ManagingAgent canonical_id uses UUID5** — derived from `(normalized_name,
normalized_address)` via `uuid.uuid5(uuid.NAMESPACE_DNS, key)`, prefixed
`MGT-`. This makes the ID stable across pipeline re-runs. OwnershipNetwork
Actor IDs use UUID4 (random) and are matched across runs via Jaccard similarity
on BBL sets. Do not mix these patterns.

**Load Rule metadata from the graph at runtime** — follow `_load_rule_from_graph()`
in `deterioration.py`. The fallback constants exist only for resilience, not
as a substitute for proper graph registration. The narrator must cite live
graph state, not hardcoded strings.
