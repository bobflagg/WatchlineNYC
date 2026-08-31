# Watchline Discovery Agent — Development Roadmap

**Status:** agreed 2026-07-29; revised 2026-07-30 (Geosupport address
resolution). **Phase 0 complete 2026-07-31. Phase 1 complete 2026-08-01.
Phase 2 complete 2026-08-01** — the Geosupport sidecar, `resolve_address`,
`resolve_landlord_name`, session state, and deterministic reference resolution.
**Phase 3 complete 2026-08-02** — the nine Tier 1–2 tools, the first production
consumers of `vocab.py`. **Phase 4 complete 2026-08-02** — the nine Tier 3
multi-hop tools (deed/mortgage chains, control networks, sister buildings,
portfolio detail, the registration diff, the honest actor→landlord gap, and
cross-entity comparison). **Phase 5 complete 2026-08-02** — the real Tier-4 deep
agent (`deep_investigation`): a Deep Agents subagent with the Tier 1–3 library,
self-generated Cypher (Type III), and web search (Type IV), gated to `vetted`.
**Phase 6 complete 2026-08-04** — the LangSmith eval harness (deterministic code
evaluators over the 40 example queries), the worked-example threads, the indexed
adversarial suite, and the public library API. **All roadmap tiers are built and
the project is complete.**
**Scope:** `watchline/discovery/agent/` — the conversational query/agent tool
library over the `watchline-discovery` Neo4j graph.
**Authority:** `CLAUDE.md` is the spec of record; `graph_type.cypher` is schema
truth, with the `discovery-schema-reference` skill as its fast-lookup summary
and the `discovery-example-queries` skill as acceptance criteria. This roadmap
sequences the work — it does not re-decide the design.

---

## 1. Deliverable

A LangGraph-based conversational agent plus the parameterized Cypher tool
library it calls, exposed so a calling application can create a session, pass
turns in, and get back structured, cited answers. **Not** a UI, not
authentication, not the evidentiary graph.

Layer choices, confirmed against `ecosystem-primer`:

- **LangGraph** for the top-level agent — required by custom control flow:
  tier routing, session-state reference resolution, tool-visibility middleware.
- **Deep Agents** for the Tier-4 investigator, as a delegated subagent with
  isolated context.
- **LangSmith** tracing from Phase 0 (`LANGSMITH_TRACING`, `LANGSMITH_PROJECT`,
  `LANGSMITH_API_KEY`).
- **Session = LangGraph thread.** No separate session concept; a new
  conversation is a new `thread_id`.

---

## 2. Verified ground truth

Confirmed by read-only query against the live `discovery` database on
2026-07-29. Re-verify before relying on any of it later.

### 2.1 Scale — every query must be bounded

| Label | Count |
|---|---|
| `Event` | 42,296,617 |
| `Actor` | 14,821,930 |
| `Building` | 859,794 |
| `Landlord` | 118,493 |
| `Portfolio` | 97,863 |

Labels and all nine relationship types match `graph_type.cypher` exactly. No
`Lead`, no `LandlordActor` — the schema file and the live graph agree.

**97,863 portfolios across 118,493 landlords** means most portfolios are
near-singletons. Any Tier-4 feature about "portfolios of a given size class"
must filter on `member_count` / `building_count` or it will drown in
one-member clusters.

### 2.2 The event vocabulary is the biggest correctness trap

> **Corrected 2026-07-31.** This section previously described a "7-pair
> matrix" and omitted ACRIS entirely. The full matrix has **11 pairs**; the
> earlier `DISTINCT` result was incomplete. Per-type counts sum to exactly
> 42,296,617, matching the original total, so the data had not changed — the
> survey was wrong, not the graph. Full vocabularies now live in
> `watchline/discovery/agent/vocab.py`, derived by full scan and guarded by a
> drift detector.

`source_name` × `event_type` is an 11-pair matrix:

| `source_name` | `event_type` | events |
|---|---|---|
| HPD | `Complaint` | 16,143,104 |
| HPD | `Violation` | 11,082,793 |
| HPD | `VacateOrder` | 8,732 |
| DOB | `Violation` | 2,267,700 |
| ECB | `Judgment` | 1,699,561 |
| HPD-Litigations | `CourtFiling` | 239,367 |
| Marshal | `Eviction` | 100,706 |
| ACRIS | `DeedTransfer` | 3,018,093 |
| ACRIS | `Mortgage` | 3,551,213 |
| ACRIS | `MortgageAssignment` | 1,926,946 |
| ACRIS | `MortgageSatisfaction` | 2,258,402 |

Five traps follow, and all five silently produce *wrong numbers* rather than
errors:

1. **`event_type` is coarse.** `'Violation'` spans both HPD and DOB. Every
   violation tool must constrain `source_name`.
2. **`violation_class` codebooks collide.** DOB's 56 codes include `'A'`,
   `'B'`, `'C'`, `'E'` alongside `'7S'`, `'ACC1'`, `'AEUHAZ1'`, `'FISP'` —
   colliding with HPD's A/B/C/I, which mean something entirely different.
   Measured: `violation_class = 'C'` unscoped returns 2,547,016 HPD rows
   **plus** 179,658 DOB rows.
3. **`violation_class` is a repurposed field.** Only HPD `Violation` uses
   hazard classes. Elsewhere it holds ACRIS document type (`DEED`/`SAT`), HPD
   complaint urgency (`EMERGENCY`), vacate-order cause (`Fire Damage`),
   litigation case type (`Tenant Action`), or Marshal property type
   (`RESIDENTIAL`).
4. **`status` casing differs by event type, not at random.** HPD `Complaint`
   stores `'OPEN'`/`'CLOSE'`; HPD `Violation` stores `'Open'`/`'Close'`. So
   `status = 'Open'` is correct for violations but returns **0 of 32,055**
   open complaints. Normalization must be keyed on `(source, event_type)`.
5. **`HPD-Litigations.status` is not a controlled vocabulary.** It embeds a
   date with inconsistent separators — `'GRANTED - 02/08/2022'`,
   `'Exempt- 08/29/2022'`, `'DENIED , 10/31/2016'` — giving 1,580 distinct
   values that reduce to 10 outcomes once the date is stripped. Matched by
   prefix, not enumeration.

**Also corrected:** the `discovery-example-queries` skill described HPD
Class A as "immediately hazardous". Per HPD's published definitions, A is
*non*-hazardous and **C** is immediately hazardous. Answering a life-safety
question with Class A rows would report non-hazardous conditions as immediate
hazards. `vocab.py` encodes the correct semantics and the skill is fixed.
Class `I` (804,440 rows) is outside HPD's published A/B/C scheme and is left
deliberately unranked — see open question 7.

Hence **D6** (canonicalization module).

### 2.3 Address resolution — Geosupport, not string matching

Present indexes: uniqueness-backing RANGE on the four keys; RANGE on
`Event(event_type)` and `Event(event_type, event_date)`; two token LOOKUPs.
Nothing on `Building.address`, nothing on any name property, no fulltext.

**Addresses are resolved through NYC DCP Geosupport** (Desktop Edition **25b**,
matching the ingestion pipeline's pinned release), the same geocoder
WoW/JustFix uses. Typed address → Geosupport → BBL → direct hit on the
existing `bbl` uniqueness index. `Building.bbl` is verified 10 characters on
all 859,794 rows, with the borough digit mapping cleanly to `borough`
(1 Manhattan / 2 Bronx / 3 Brooklyn / 4 Queens / 5 Staten Island), so the join
needs no reformatting beyond zero-padding Geosupport's block/lot components
to 5 and 4 digits.

This replaces the measured **~2.9s** unindexed address scan with an O(1) key
lookup, and handles what string normalization got wrong on this exact data:
Queens hyphenated house numbers (`'232-05 87 AVENUE'`), stripped ordinals
(`'WEST 120 STREET'`), rows with a street and no house number
(`'CARDER ROAD'`), and vanity/alias addresses. Because normalization now lives
in DCP's dictionary rather than agent code, agent-vs-pipeline drift disappears.

Two indexes remain genuinely required — **`FULLTEXT Landlord.name`** and
**`Event(source_name, event_type, event_date)`** — because Geosupport does
nothing for names, and §2.2 makes source-constrained event queries mandatory.
See [`specs/required_indexes.cypher`](./required_indexes.cypher), which also
withdraws the three address-related requests the earlier revision made.

**`Building.bin` is populated on 0 of 859,794 rows** despite being declared in
`graph_type.cypher`. BBL is the only viable join key; Geosupport can supply
BIN on demand if that ever changes.

### 2.4 Data shape findings that change tool design

**`Building.address` is PLUTO-normalized uppercase** with ordinals stripped —
`'232-05 87 AVENUE'`, `'WEST 120 STREET'` — not unique, and sometimes lacking a
house number entirely (`'CARDER ROAD'`). It is therefore a **display field
only**; never a lookup key (§2.3).

**`Landlord.bizaddr` is only partly standardized, and `CONNECTED_BY_ADDRESS`
silently under-connects because of it.** 105,626 values carry a
`, <BOROUGH> NY` suffix; 12,867 do not. Real values:

```
'724 724 ELTON AVENUE UNIT 1, BRONX NY'   ← house number duplicated
'724 ELTON AVENUE 1, BRONX NY'            ← same address, different form
'320 320 ROEBLING STREET STE 2, BROOKLYN NY'
'333 PEARSALL AVENUE 207, C NY'           ← borough rendered as 'C'
'1940 EAST SEVENTH STREET, BROOKLYN NY'   ← spelled-out ordinal
'25 EAST 21 STREET 10 FL, MANHATTAN NY'   ← numeric ordinal
'3232 NEWMARK, MIAMISBURG OH'             ← out of city, unresolvable
```

Rows 1–2 are the same physical address stored two ways as two separate
`Landlord` records, so the clustering does **not** link them. The
`CONNECTED_BY_ADDRESS` caveat warns only that it can *over*-connect; this
shows it also *under*-connects, which is the more damaging direction — a
missing edge is invisible, while a spurious one gets scrutinized. The caveat's
long form has been amended accordingly (D10, **done** 2026-07-30); the
remaining follow-up is requesting `bizaddr_bbl` from the pipeline (D11). Unit
and floor
designators are inline and inconsistent (`UNIT 1`, `STE 9`, `10 FL`, `BSMT`),
confirming the right grain for "same business address" is the **building**,
not the string.

**Names are dirty.** Real `Landlord.name` values: `',MARIA CROSS'`,
`'.ARSILLO ANGELO'`, `'(LARS) PETER LIBERT'`, `'.XI MEI LI'` — leading
punctuation, parentheticals, frequently surname-first.

**`APPARENT_CONTROL` reaches 171,347 of 859,794 buildings (~20%).** "No
apparent controller found" is the **majority** outcome for the flagship tool.
Build and test it as the common path, not an edge case.

**The comparison verdicts were measured across all 171,347 controlled buildings**
(2026-08-01, `scripts/measure_verdicts.py`): `differs` 66.70%, `agrees` 18.53%,
`indeterminate` 14.75%, `not_comparable` 0.02%. Across the whole stock,
**80.07% of ownership lookups return "no apparent controller"** — the single
most load-bearing number for how the flagship tool must read. Full analysis in
[`specs/2026-07-31-phase-1-ownership-slice/verdict-distribution.md`](./2026-07-31-phase-1-ownership-slice/verdict-distribution.md).

**And it is strictly 1:1** — verified 2026-07-31, every one of those 171,347
buildings has exactly **one** apparent controller. `graph_type.cypher` does not
constrain it to one, so tools should still return a collection rather than
assume a scalar, but there is no data to exercise a multiple-controller path and
no fixture can be built for it.

**The dual ownership answer cannot be string-compared.** Real rows:

| `dof_ownername` (recorded) | `Landlord.name` (apparent) |
|---|---|
| `'LIBERT, LARS PETER'` | `'(LARS) PETER LIBERT'` |
| `'ANGELO MARSILLO'` | `'.ARSILLO ANGELO'` |
| `'3071 HULL REALTY LLC'` | `',MARIA CROSS'` |

Rows 1–2 are plausibly the same party in different formats; row 3 is a genuine
shell-LLC-vs-inferred-controller divergence. Naive equality reports "they
disagree" on all three. Hence **D2**.

**Portfolios are fully regenerated per run.** All 97,863 came from a single
`run_id` `20260729T002106Z` (method `GDS WCC+Louvain`), generated the same day
as this survey. `portfolio_id` is therefore not stable across runs. See **D7**.

**Example-query parameters are illustrative, not resolvable.** Tier 1 #1's
`456 West 24th Street, Manhattan` returns **zero rows**. The 40 examples stay
the acceptance criteria, but every literal value must be re-baselined against
real entities before use as a test.

### 2.5 Repo state

- `watchline/shared/connections.py` returns an unrestricted **read-write**
  driver, and its docstring references an undefined
  `NEO4J_EVIDENTIARY_DATABASE`. Read-only enforcement is ours to add in a
  wrapper — do not edit shared code out from under other consumers.
- No Neo4j MCP connector is configured, though `neo4j-discovery-query` expects
  one. Phase 0 task.
- `graph_type.cypher` sits at the repo root; the schema skill cites
  `watchline/discovery/schema/graph_type.cypher`. Harmless, worth aligning.

---

## 3. Decisions

| # | Decision |
|---|---|
| **D1** | **Index DDL authored here, applied by the pipeline.** `specs/required_indexes.cypher` is the deliverable; the ingestion pipeline owns execution. This module performs no writes of any kind. |
| **D2** | **Dual ownership answer = both values verbatim + a 3-state comparison** (`agrees` / `differs` / `indeterminate`), using punctuation and surname-order normalization only. No fuzzy scoring — a similarity score is a quasi-identity claim the guardrails forbid. `indeterminate` is first-class and common. |
| **D3** | **Tier 4 is in v1 scope, sequenced after the Tier 1–3 library is complete.** The deep agent's value depends entirely on those tools being trustworthy. |
| **D4** | **Read-only by defense in depth:** a dedicated read-only Neo4j role (to confirm or request) **and** `RoutingControl.READ` on every call **and** a pre-execution Cypher validator. All three — no single point of failure. |
| **D5** | **Phase 1 is one vertical slice end to end**, not breadth. |
| **D6** | **A canonicalization module owns event vocabularies.** `(source_name, raw value) → canonical enum` for status and violation class. Every event tool requires `source_name`. Unknown codes surface explicitly rather than being silently dropped. |
| **D7** | **Portfolios: always read the latest run; do not track `run_id`.** Chosen for simplicity. *Accepted risk:* a portfolio pinned in `focus_entities` or a `working_set` early in a session may silently denote a different set of buildings after a pipeline regeneration mid-session. Mitigation kept cheap — tools return `Portfolio.run_id` and `generated_at` in their payload as informational provenance, so a UI or a later debug session can spot the shift, but no handle invalidation logic is built. Revisit if regeneration frequency rises. |
| **D8** | **Tier 4 returns one synthesized report as the contract**, plus coarse optional progress events a UI may ignore. Partial findings never become part of the public surface. |
| **D9** | **Addresses resolve via NYC DCP Geosupport, pinned to release 25b** — the same release the ingestion pipeline uses, so agent-side and pipeline-side geocoding cannot disagree. Deployed by **extending the existing `linux/amd64` pipeline image into a sidecar HTTP service**, keeping the version pin in one Dockerfile and leaving the agent on native Python 3.13 so `langgraph dev` and Studio work normally on Apple Silicon. (python-geosupport is Windows/Linux only and the binaries are x86_64.) |
| **D10** | **Geosupport is tagged Type I, with an explicit carve-out in `CLAUDE.md`.** It is a local, deterministic, offline, city-official canonicalizer — the same authority PLUTO derives from — categorically unlike the open-web search that Type IV covers. The carve-out is written down so the "external lookups are Tier-4 only" rule isn't silently broken. Separately, the `CONNECTED_BY_ADDRESS` long-form caveat has been extended to acknowledge under-connection as well as over-connection, with the supporting evidence recorded alongside it (§2.4) — **done** 2026-07-30 in `discovery-schema-reference`. Short forms unchanged in both that skill and `CLAUDE.md`. |
| **D11** | **Request `Landlord.bizaddr_bbl` as a pipeline field** rather than geocoding business addresses at query time. Fixes `CONNECTED_BY_ADDRESS` at the source for every consumer, not just this agent, and reduces Tier 3 #1 to an indexed BBL equality match. NULL where Geosupport returns a non-zero GRC — out-of-city addresses legitimately can't resolve, and NULL is the honest answer. |
| **D12** | **Geosupport return codes drive the disambiguation contract, not just error handling.** Success → BBL lookup; similar-street-names → the capped candidate list `CLAUDE.md`'s ambiguity contract requires; house-number-out-of-range and street-not-recognized → distinct, actionable results. This gives authoritative disambiguation instead of fuzzy scoring. Output carries **both** the verbatim stored `address` (citation fidelity) and a Geosupport-canonical display form (readability). |

---

## 4. Phases

### Phase 0 — Foundations ✅ **complete 2026-07-31**

Delivered on branch `feat/phase-0-foundations`. 552 tests passing (509 hermetic,
43 integration). Detail in
[`specs/2026-07-30-phase-0-foundations/`](./2026-07-30-phase-0-foundations/) —
requirements, plan, validation results, and the Geosupport spike findings.

Shipped: `db.py` (read-only access), `cypher_guard.py` (write refusal),
`caveats.py` + `reliability.py` (canonical caveats, static Type I–IV tagging),
`vocab.py` (event vocabulary canonicalization), `geocode.py` (Geosupport
client), a stub graph running under `langgraph dev`, and 40 live-resolved
example-query fixtures.

**What Phase 0 changed about the plan**, beyond building the modules:

- The `(source_name, event_type)` matrix has **11** pairs, not 7 — ACRIS was
  missed entirely by the first survey (§2.2).
- HPD **Class C** is immediately hazardous, not Class A; **Class I** is an
  administrative notice and is off the hazard scale (§2.2, open question 7).
- **`APPARENT_CONTROL` is strictly 1:1**, so the "multiple controllers" case the
  plan called for does not exist in this data (§2.4).
- Geosupport round-trips at **96.0%**, and `GRC '00'` does not guarantee a BBL —
  which finally explains why example query Tier 1 #1's address resolves to
  nothing anywhere (open question 3).
- Four events carry impossible future dates (open question 10).

No agent behavior. Everything here is a prerequisite for something later.

- Dependencies on top of the installed `neo4j>=6.2.0` / `python-dotenv`:
  `langgraph`, `langchain`, `deepagents`, `langsmith`, `pytest`. Pin per
  `langchain-dependencies`.
- `watchline/discovery/agent/` package skeleton; `langgraph.json` declaring
  `discovery_agent` → `graph.py:graph`, `env: .env`.
- `.mcp.json` Neo4j connector, read-only credentials, database `discovery`.
- **`db.py`** — the only path to the graph. Wraps
  `watchline.shared.connections`, forcing `routing_=RoutingControl.READ`,
  pinning `database_`, applying a default row cap and query timeout.
- **`cypher_guard.py`** — pre-execution validator rejecting `CREATE`, `MERGE`,
  `SET`, `DELETE`, `REMOVE`, `DROP`, `ALTER`, `LOAD CSV`,
  `CALL {…} IN TRANSACTIONS`, and any procedure outside an allowlist.
  Adversarially unit-tested, because Tier 4 will feed it model-generated
  Cypher.
- **`caveats.py`** — the canonical short/long pairs for `Portfolio`,
  `APPARENT_CONTROL`, `CONNECTED_BY_ADDRESS`, `CONNECTED_BY_NAME`, plus the
  `dof_ownername` interpretation note. Verbatim from
  `discovery-schema-reference`. One module, imported everywhere, never
  duplicated per tool.
- **`reliability.py`** — Type I/II/III/IV tags assigned statically at write
  time from the labels a tool touches, plus the decorator that attaches the
  matching caveats to output.
- **`vocab.py`** (D6) — canonical enums for `source_name`, `event_type`,
  status, and violation class, with per-source mappings and an explicit
  `unknown` path.
- **`geocode.py`** + **Geosupport sidecar** (D9) — extend the existing
  `linux/amd64` / Geosupport 25b image with a thin resolve endpoint alongside
  `run_standardize`. Client-side: bounded timeout, GRC→result mapping per D12,
  block/lot zero-padding to the 10-char BBL, and a health check that fails
  loudly at startup rather than silently degrading to "address not found."
  Pin the release as a shared constant, not a literal in two places.
- **`specs/required_indexes.cypher`** — done; hand to the pipeline owner. Also
  carries the `Landlord.bizaddr_bbl` request (D11) and withdraws the three
  address-index requests Geosupport made unnecessary.
- **Re-baseline the example queries** into `tests/fixtures/`: for each of the
  40, a real resolvable parameter value plus a captured known-good result.

**Done when:** `cypher_guard` rejects every adversarial write string in its
suite; `db.py` provably cannot write; `vocab.py` round-trips every real status
and class value observed in §2.2; the fixture file holds 40 real parameter sets.

### Phase 1 — Vertical slice: "who owns this building?" ✅ **complete 2026-08-01**

Delivered on branch `feat/phase-1-ownership-slice`. 826 tests passing (757
hermetic, 58 integration, 11 llm). Detail in
[`specs/2026-07-31-phase-1-ownership-slice/`](./2026-07-31-phase-1-ownership-slice/),
including the measured verdict distribution.

Shipped: `names.py` (comparison without a similarity claim),
`tools/ownership.py` (the flagship dual answer), `middleware.py` (capability
gating and persona), `tools/investigation.py` (Tier-4 placeholder),
`tools/registry.py`, `session.py`, and a tool-calling agent on `claude-opus-5`
running under `langgraph dev`.

**What Phase 1 changed about the plan:**

- **Two bugs were invisible to unit tests and only appeared on the server.**
  `langgraph dev` loads the entrypoint by file path (breaking relative imports),
  and the middleware's sync-only hooks meant **the trust gate never ran** under
  the server's async invocation. Hand verification is a merge criterion for good
  reason — a security control can pass every unit test and still be absent in
  the deployment.
- **The verdict distribution was measured, not estimated** (§2.5 below). The
  `INDETERMINATE`-dominance risk did not materialize.
- **`APPARENT_CONTROL` 1:1 was reconfirmed**, so the multi-controller test is
  labelled synthetic rather than implying coverage.
- One comparison refinement was taken (legal-form tokens) and one deliberately
  deferred (middle initials) — see open question 11.

The flagship tool end to end, keyed on `bbl` so no index work blocks it.
`CLAUDE.md` names this the single most common Tier-1 query — get it right first.

- **`lookup_building_ownership(bbl)`** — returns `dof_ownername` (Type I,
  "recorded owner") **and** the `Landlord` via `APPARENT_CONTROL` (Type II,
  "apparent controller"), both verbatim, both labeled, caveats attached, plus
  the D2 three-state comparison. Handles the ~80% no-controller path and the
  multiple-controller case as normal results.
- Minimal LangGraph: one tool-calling node, checkpointer, `thread_id` as session.
- **Trust middleware skeleton** — tool visibility filtered from
  `configurable.trust_level`, failing closed to `"public"` on missing,
  malformed, or unrecognized values. Enforced in the tool-filtering layer,
  never as a prompt instruction. Built now, before there is a Tier-4 tool to
  hide, so the control predates the capability.
- Persona plumbed as tone/register policy only — never gating.

**Done when:** the tool runs in `langgraph dev` / Studio against the live
graph; output carries both answers, correct caveat text, and a comparison
verdict; `"public"` and `"vetted"` threads both behave per policy.

### Phase 2 — Entity resolution, disambiguation, session state ✅ **complete 2026-08-01**

Delivered on branch `feat/phase-2-entity-resolution`. Detail in
[`specs/2026-08-01-phase-2-entity-resolution-session-state/`](./2026-08-01-phase-2-entity-resolution-session-state/).

Shipped: the Geosupport sidecar (`sidecar/`, a thin `linux/amd64` pass-through
to the contract `geocode.py` already targeted), `tools/address.py`
(`resolve_address`), `tools/landlord.py` (`resolve_landlord_name`), the
`DiscoveryState` session-state schema on `session.py`, and `state.py`
(`SessionStateMiddleware`: capture, idle timeout, and deterministic reference
resolution), wired first in the middleware chain.

**What Phase 2 changed about the plan:**

- **A real server-only bug, again.** Injecting the resolved-reference note as a
  `SystemMessage` produced "multiple non-consecutive system messages" from the
  Anthropic API (the persona prompt is already the system message). It is now a
  `HumanMessage`. Invisible to every unit test — found only by the `llm` tier,
  which is exactly why hand/`llm` verification is a merge criterion.
- **`Landlord.bbls` is populated on all 118,493 nodes**, so the disambiguation
  building-count comes from that list (keeping the tool to a single `Landlord`
  touch) rather than traversing `APPARENT_CONTROL`.
- **`db.index.fulltext.queryNodes` was already on the `cypher_guard` allowlist**
  — Phase 0 anticipated the name-resolution tools.
- **Indexed reference needs an explicit ordinal marker.** A bare number must not
  be read as an index: "115 Broad Street" is not "item 115". Ordinal word,
  ordinal-suffixed digit, or `number`/`#` prefix only.
- **`resolve_landlord_name` disambiguates on the guardrail-safe verdict**, not
  the fulltext score: exactly one exact-token match resolves, anything else is a
  candidate list. The retrieval score ranks only and is never returned.

Original scope, all delivered:

Address resolution needs no new index and is therefore unblocked from the
start. Name resolution is defined behind an interface so it proceeds whether or
not `FULLTEXT Landlord.name` has landed.

- **`resolve_address`** — Geosupport → BBL → `bbl` key lookup (D9). GRC
  outcomes map to structured results per D12: success, capped candidate list
  from Geosupport's similar-street-names response, house-number-out-of-range,
  street-not-recognized. Handles **geocoded-but-absent** as a distinct result —
  Geosupport may return a valid BBL for a lot that has no `Building` node.
  Never returns a fuzzy-score guess.
- **`resolve_landlord_name`** — fulltext over `Landlord.name`, handling the
  §2.4 dirt in normalization. This is where genuine fuzzy matching lives, and
  therefore where the disambiguation contract does the most work.
- **Session state:** `focus_entities`, `working_set`, `comparison_set`,
  `last_result` (stable indices), `thread_mode`, `disambiguation_history`.
  30-minute configurable idle timeout on the short-term slots only.
- **Resolved-reference metadata on every response** that resolved a pronoun,
  indexed reference, or ambiguous name (e.g. `resolved: "he" → Landlord
  ACT-LL-47644`). This is also the entire correction mechanism — "no, I
  meant…" **overwrites** the focus slot rather than appending.
- Turn order enforced: resolve references → classify intent → route tier →
  apply persona policy.

**Done when:** a multi-turn Studio thread resolves "he" / "that landlord" /
"the second one" correctly, and an ambiguous name returns a capped candidate
list instead of a guess.

### Phase 3 — Tier 1 and Tier 2 breadth ✅ **complete 2026-08-02**

Delivered on branch `feat/phase-3-breadth`. Detail in
[`specs/2026-08-02-phase-3-breadth/`](./2026-08-02-phase-3-breadth/).

Shipped nine tools across `tools/building.py`, `tools/landlord_portfolio.py`,
`tools/geo_time.py`, and a shared `tools/_events.py` rollup — the first
production consumers of `vocab.py`. Each validated live against its fixture
anchor.

**What Phase 3 changed about the plan / folded open questions:**

- **`Landlord.bbls` is populated on all 118,493 nodes**, so building counts read
  the list directly (no `APPARENT_CONTROL` traversal).
- **OQ12 (future dates) — resolved as *surface, never clamp*.** A "most recent"
  lookup flags a future-dated top event rather than reporting it as fact or
  moving it to today; null `event_date`s are excluded from the ordering.
- **OQ8 (ECB dual-scheme) — disclosed, not resolved.** An ECB aggregate carries a
  coverage note that the hazard scheme covers only ~35% of judgments.
- **Portfolio precomputed properties confirmed present** (`building_count`,
  `residential_units`, `member_count`); `portfolio_summary` reads them.
- **`aggregate_events_by_geo_time` requires a bounded date range** and the
  borough-join form is fast against the live graph (Bronx-2025 evictions = 4577
  returned in well under the timeout).
- **A test-design lesson, not a bug:** a refinement whose answer is already in
  the prior tool's structured payload (e.g. "how many are open" after an
  aggregate that returned the status breakdown) correctly reads it rather than
  re-querying. The re-query discipline is about not reciting stale/fabricated
  numbers, not forcing redundant calls — the `llm` test now refines across a new
  *source* to exercise a genuine re-query.

Original scope, all delivered:

One tool per canonical pattern, not one per tier. Each statically tagged, each
validated against the live graph with realistic values per
`neo4j-discovery-query`, each bounded, each routed through `vocab.py`.

*Tier 1:* `lookup_building`, `lookup_building_events` (type/source/status/date
filtered — covers last-sold, vacate-order, latest-complaint),
`lookup_landlord`, `landlord_portfolio_membership`.

*Tier 2:* `aggregate_building_events`, `aggregate_landlord_portfolio_events`,
`portfolio_summary` (**read the precomputed `Portfolio.building_count` /
`.residential_units`; do not recompute from members**),
`aggregate_events_by_geo_time` (rides the new
`Event(source_name, event_type, event_date)` index),
`portfolio_buildings_by_borough`.

Also: **deterministic re-query discipline** — a refinement like "just the
Class A ones" issues a fresh, precisely filtered Cypher call. The model never
recalls or recomputes a number from an earlier turn.

**Done when:** all 20 Tier 1–2 example queries answer correctly from their
re-baselined fixtures, with source-constrained violation filters throughout.

### Phase 4 — Tier 3 multi-hop ✅ **complete 2026-08-02**

Delivered on branch `feat/phase-4-tier3-multihop`. Detail in
[`specs/2026-08-02-phase-4-tier3-multihop/`](./2026-08-02-phase-4-tier3-multihop/).

Shipped nine tools across `tools/chain.py`, `tools/network.py`,
`tools/portfolio_detail.py`, and `tools/compare.py`. Each validated live.

**What Phase 4 changed about the plan / folded open questions:**

- **`REFERENCES` is bidirectional** between ACRIS documents (`ref_type`
  CRFN/DOCID); `trace_ownership_chain` matches it undirected and derives a
  mortgage's outstanding status from a referencing `MortgageSatisfaction`, since
  ACRIS events carry no status field.
- **`CONNECTED_BY_*` are dense.** An 111-member portfolio has ~12,650 connection
  edges, so `control_network` returns member/building/edge *counts* plus a capped
  member list, never the edge set.
- **OQ4 (nullable `REGISTERED_FOR.role`) — resolved:** shown as "role not
  recorded". The registration query starts from `:Actor` (a test asserts it).
- **The T3 #10 gap is the primary contract.** `trace_actor_to_landlord` never
  returns a confident match: `resolved_landlord` is always null; it states the
  missing edge and returns possibly-related landlords with `compare_names`
  evidence.
- **`compare_entities` is an orchestrator** (Type I wrapper): it calls the Phase 3
  aggregates once per entity, keeps each per-entity `reliability`, and has no
  cross-entity total — never summed (a test asserts the absence of a total).

Original scope, all delivered:

Bounded traversal, 2–4 hops, hard hop and row caps. Large results return a
**compact summary plus stable handles/IDs**, never raw rows — for token cost
and so indexed references stay resolvable in later turns.

`sister_buildings`, `trace_ownership_chain` (deeds and mortgages in order,
using `REFERENCES` for satisfaction/assignment chains),
`shared_address_landlords` (matches on `bizaddr_bbl` per D11, and until that
field lands, traverses `CONNECTED_BY_ADDRESS` while disclosing the
under-connection limitation from §2.4), `control_network`,
`portfolio_buildings_with_violations`, `portfolio_litigation`,
`ownership_vs_registration_diff`, and `compare_entities` — which runs an
existing aggregation once per member of `comparison_set` and aligns results
side by side, **never summed**.

**`trace_actor_to_landlord`** is the known-gap tool (Tier 3 #10). There is no
"raw `Actor` resolved to this `Landlord`" edge — only `CONNECTED_BY_NAME` /
`CONNECTED_BY_ADDRESS` inference. It must return *"no resolved landlord found,
but N possibly-related landlords via shared name/address"* — never silently
fail, never over-claim a match. Remember `REGISTERED_FOR` originates on
`:Actor`, not `:Landlord`; don't assume the source carries the landlord label.

**Done when:** all 10 Tier 3 examples answer, including #10 returning its
honest partial result.

### Phase 5 — Tier 4 deep agent (full, per D3) ✅ **complete 2026-08-02**

Delivered on branch `feat/phase-5-deep-agent`. Detail in
[`specs/2026-08-02-phase-5-deep-agent/`](./2026-08-02-phase-5-deep-agent/).

Shipped `investigator.py` (the Deep Agents subagent — Tier 1–3 library +
`run_cypher` Type III + `web_search` Type IV, fresh isolated context, one cited
report) and the `deep_investigation` body swap; `investigation_state` on
`DiscoveryState`; structural prompt-injection hardening; and bounded evals.

**What Phase 5 changed / found:**

- **The deep agent found a real bug.** During a live portfolio-condition run it
  surfaced a `vocab` `RawFilter` param-name collision (two filters both emitted
  `$vals_exact`, the second overwriting the first) that made
  `portfolio_buildings_with_violations` report 0 open hazardous violations where
  the true count was 570. Fixed with distinct param names — a Tier-3-caught
  Tier-2 wrong-numbers defect, exactly the payoff of the investigator.
- **`run_cypher` must be resilient, not just safe.** A model query that timed out
  raised a `Neo4jError` straight out and sank the whole investigation; it now
  catches execution errors and returns them as feedback (with a 20s timeout) so
  the agent rewrites and continues — the same discipline as a guard refusal.
- **Injection resistance is structural, and that is the point.** The tool set is
  fixed at construction and trust is read from config, never content, so no
  injected `raw_record` can add a tool or raise trust — asserted directly rather
  than relying on the model behaving.
- **Web search is deferred-provider no longer** — `langchain-tavily`, budgeted,
  provenance-separated, and disabled cleanly without `TAVILY_API_KEY`.

Original scope, all delivered:

- Deep Agents subagent with **fresh isolated context** — task delegation, not
  shared message history — returning one synthesized report with rationale,
  priority, and suggested focus, rather than leaking intermediate queries into
  the main thread.
- **Handed the same Tier 1–3 library.** Written once, used from both places.
- Self-generated Cypher goes through `cypher_guard` and `db.py`, Type III
  tagged, no exceptions.
- Web/registry search: **Tier 4 only**, never in the shared library, under an
  explicit call budget. Provenance visibly separated — graph-verified vs.
  web-sourced, each with its own citation. A web-sourced identity link is
  labeled a distinct, lower-confidence tier than the graph's `CONNECTED_BY_*`
  signals, never merged into "apparent control." Type IV tagged.
- Internal sub-routines named for the canonical patterns:
  **`PortfolioCondition`** (Tier 4 #1), **`DeteriorationTrajectory`** (#2).
- `investigation_state` — partial findings, hypotheses tested and rejected,
  evidence gathered. **Exempt from the 30-minute idle timeout**; persists until
  explicitly closed, since investigations may resume days later.
- Async-compatible per D8: a Tier 1–3 query must run while an earlier Tier-4
  investigation is in flight. The deep agent reads a **read-only snapshot of
  session state taken at launch**; ordinary turns keep hitting live state.
  Notification and polling UX belong to the calling app.
- Long-form caveats on every Type II element the narrative relies on.
- **Prompt-injection hardening.** The deep agent reads NOV descriptions and raw
  ACRIS/HPD `raw_record` JSON directly — a real injection surface, not a
  theoretical one. Graph content is untrusted data, never instruction.
  Re-verify here that trust gating still lives in the tool-filtering layer and
  that no injected text can widen tool visibility.

**Done when:** Tier 4 is invisible on a `"public"` thread and functional on a
`"vetted"` one; a full case-file run (Tier 4 #4) produces a cited narrative
with correct long-form caveats; an injection attempt embedded in `raw_record`
provably cannot escalate capability.

### Phase 6 — Evals, hardening, packaging ✅ **complete 2026-08-04**

- The worked-example threads from `CLAUDE.md` as end-to-end llm smoke tests
  (`tests/llm/test_worked_examples.py`): the tier-escalation thread (Type-II
  caveat → sister buildings via a demonstrative → source-constrained event count,
  the resolved reference carrying every turn; its Tier-4 escalation under
  `llm_deep`) and the indexed-reference pivot ("the second one" →
  `last_result.items[1]`). Structural assertions only.
- **LangSmith** eval harness over the 40 example queries (`evals/`) with
  deterministic **code** evaluators — expected tool, source-constraint, caveat
  presence, run provenance, resolved-reference — not answer text. Verified
  hermetically (`tests/test_evaluators.py`); the live run is gated on
  `LANGSMITH_API_KEY`. A first live Haiku pass over Tier 1–3 scored the four
  structural evaluators 1.000 and tool-routing 0.933 (the deltas were defensible
  sibling-tool choices).
- Adversarial suite indexed by threat in `tests/ADVERSARIAL.md` (injection,
  trust escalation, malformed `trust_level`, read-only, unbounded traversal,
  source collision) mapping each to the tests that prove it; `test_adversarial.py`
  filled the one gap (`run_cypher` surfacing truncation).
- Library-surface docs + a real public API: `watchline.discovery.agent` exports
  the calling surface with `__all__`, `main.py` is a runnable end-to-end example,
  and the README has a "Using the library" section.

**What Phase 6 changed / found:**

- **Harbor → LangSmith, LLM-judge → code evaluators (P6-1/P6-2).** Harbor was not
  installed and the verifiers are structural presence checks, so deterministic
  code evaluators (free, hermetically unit-testable) replaced a judge; the live
  LangSmith run is gated on a key, like Tavily/Geosupport.
- **The example queries are templates, not standalone prompts.** The first live
  eval exposed that the fixture texts (`"...this portfolio."`, `<address>`) left
  the model nothing to route on; `evals/dataset.py` concretizes them with entity
  identifiers (never answer fields) — a real correctness find the harness surfaced.
- **Adversarial coverage was already substantial (P6-4).** Injection, trust
  fail-closed, read-only, cap/timeout, and source-collision were all covered; the
  work was to index them and add the single missing truncation case.
- **The `graph` singleton is not re-exported at package level** — the name
  collides with the `graph` submodule. `build_agent` is the public entry; the
  server serves `…agent.graph.graph` by module path.

---

## 5. Guardrail checklist — verify at every phase

- [ ] Never emit or imply a legal ownership/control determination.
- [ ] Fail closed on trust; never infer or upgrade it mid-thread.
- [ ] Read-only always, including Tier 4's generated Cypher (D4).
- [ ] Every Type II touch ships its caveat text, not just a tag.
- [ ] Every violation query constrains `source_name` (§2.2).
- [ ] Addresses resolve via Geosupport 25b; `Building.address` is display-only.
- [ ] Agent-side Geosupport release matches the pipeline's, verified at startup.
- [ ] Status and class values go through `vocab.py`, never raw equality.
- [ ] Hops, rows, and external search calls all bounded.
- [ ] Ambiguity returns a capped candidate list; never a silent guess.
- [ ] Large results return summary + stable handles, not raw rows.
- [ ] Refinements re-query deterministically; no recalled numbers.
- [ ] Resolved-reference metadata on every response that resolved anything.

## 6. Open questions

1. ~~**Timeline for `specs/required_indexes.cypher`**~~ **Largely resolved —
   verified applied 2026-07-31.** `FULLTEXT Landlord.name`,
   `Event(source_name, event_type, event_date)`, `FULLTEXT Actor.name`, and
   `TEXT Landlord.bizaddr` are all present and ONLINE at 100%. The two
   *withdrawn* address indexes were applied too; harmless, and now usable for
   street-level browsing that BBL lookup cannot serve.
   **Still outstanding:** `Landlord.bizaddr_bbl` (D11), which needs the pipeline
   field first — confirmed the property key does not yet exist and 0 of 118,493
   `Landlord` nodes carry it. Until then Tier 3 #1 traverses
   `CONNECTED_BY_ADDRESS` and discloses that the network may be incomplete.
   Phase 2's name resolution is now unblocked.
2. ~~**Is a read-only Neo4j role available?**~~ **Answered 2026-07-31: yes.**
   Account `watchline`. D4 therefore has all three layers, and validation 2.1b
   confirms the server itself rejects `CREATE`, `MERGE`, `SET`, and index DDL
   with a security error while still permitting reads.
3. ~~**Is Geosupport 25b definitely the release used for the data currently in
   the graph?**~~ **Answered 2026-07-31** by the Phase 0 spike — see
   `specs/2026-07-30-phase-0-foundations/spike-findings.md`. Measured
   round-trip hit rate on 200 real `Building` rows: **96.0% exact BBL match**,
   2.0% resolving to a different lot, 1.5% street-parse failures (our fault,
   not Geosupport's — see the Queens numeric-street trap), 0.5% resolving with
   no tax lot. Good enough to proceed, and the residual is dominated by
   address-to-lot ambiguity rather than version skew. Two findings changed the
   client design: `GRC '00'` does **not** guarantee a BBL, and a resolved BBL
   is a *candidate* requiring confirmation against the graph, not an answer.
4. **`REGISTERED_FOR.role` is nullable in v1** — how should tools present a
   registration with no role? Omit, or show "role not recorded"?
5. **Does `HPD-Litigations` / `Marshal` data have a coverage window** shorter
   than the other sources? Aggregations spanning sources could otherwise
   under-report silently.
6. **Should `Building.bin` be populated or dropped** from `graph_type.cypher`?
   Declared but empty on all 859,794 rows (§2.3). Nothing in the agent needs
   it, so this is purely a note for the pipeline owner.
7. ~~**What does HPD violation class `I` mean?**~~ **Answered 2026-07-31.**
   Class I = *Information*: an administrative or informational order posted
   against the property rather than a defect found on inspection — an open
   Order to Repair/Vacate, a vacant-property notice, or an invalid/failed
   property registration. Because no hazard was found, these carry none of the
   correction-period or certification requirements A/B/C do, so **Class I is
   off the hazard scale entirely, not merely the least severe rank**.
   Encoded in `vocab.py`: `severity=None`, `is_hazard=False`, and a
   `HPD_HAZARD_CLASSES` set of A/B/C that `hpd_hazard_filter()` uses by
   default. Any severity count, ranking, or life-safety aggregate must exclude
   it — matching the convention in HPD's Alternative Enforcement Program and
   public worst-landlord rankings — because its 804,440 rows would otherwise
   inflate a number readers take as a count of physical hazards. Class I
   remains useful *on its own*, as a signal for invalid registrations and
   unresolved orders, which is its own red flag pattern worth a dedicated tool
   in Phase 3.
8. **Should ECB's `CLASS - 1/2/3` map onto the hazard scale?** The two schemes
   coexist in one column, and the hazard labels cover only 602,640 of
   1,699,561 ECB judgments (~35%). Currently modelled as two distinct schemes
   so a hazard-filtered aggregate can disclose its partial coverage; a
   verified mapping would let it cover all of ECB.
9. **Marshal status `'EAST'` (99 rows) and DOB null status (1,013 rows)** look
   like source-extract defects rather than real values. Worth raising with the
   pipeline owner; `vocab.py` resolves them to `UNKNOWN` / `NOT_RECORDED`
   rather than guessing.
11. ~~**Should single-letter tokens be treated as non-distinguishing in name
    comparison?**~~ **Answered 2026-08-01: yes, in the one-sided form.** A
    middle initial present on one side and absent on the other is disregarded;
    an initial present on *both* sides is not, because it can contradict
    (`'JOHN A SMITH'` vs `'JOHN B SMITH'` may be father and son). That
    restriction holds by construction rather than because the data currently
    lacks such a case. Two things emerged in implementation: the legal-form
    *exclude* mechanism would have changed nothing (a token excluded from the
    overlap test never makes two sets equal), so this required the stronger
    *strip*; and a single **digit** is a building number rather than an initial,
    so the predicate is alphabetic-only. Effect: `agrees` 25,300 → 31,754,
    `indeterminate` 31,726 → 25,272, with `differs` and `not_comparable`
    unchanged — the rule only converts hedges into agreement, never into
    disagreement. Detail in
    [`verdict-distribution.md`](./2026-07-31-phase-1-ownership-slice/verdict-distribution.md)
    §5.
12. **Four events carry impossible future dates** (found 2026-07-31): an HPD
    `VacateOrder` dated **2040-08-20**, an ACRIS `DeedTransfer` dated
    **2028-09-17**, and two `CourtFiling`s to 2030. Negligible in aggregate —
    4 of 42,296,617 — but **not** negligible per building, where a single row
    is the whole answer: "when was this last sold?" on BBL 4092810067 returns
    2028. Group 7's fixture generator initially picked that very row.
    Two follow-ups: raise with the pipeline owner, and have Phase 3's
    "most recent X" tools decide whether to clamp to today or surface the
    anomaly. Clamping silently would hide a real data defect, so surfacing is
    probably right.
