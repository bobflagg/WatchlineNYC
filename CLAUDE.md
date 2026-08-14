# CLAUDE.md — WatchlineNYC

Guidance for Claude Code sessions working in this repository. Read this before
adding features or refactoring — it captures the architecture and the
non-negotiable invariants that aren't obvious from any single file.

> **Continuing the entity-linking / portfolio-construction pipeline (Splink)?**
> That's a separate sub-project with its own scoped handoff notes — read
> [`watchline/discovery/ingest/portfolio/CLAUDE.md`](watchline/discovery/ingest/portfolio/CLAUDE.md)
> first. It lives on the `entity-linking-prototype` branch and is independent of
> the app/agent documented below.

## What this is

WatchlineNYC is accountability infrastructure for NYC housing: it lets
journalists, tenant advocates, watchdog agencies, and the public investigate
housing conditions and ownership accountability conversationally, grounded in
NYC's public record.

The system is a **Streamlit app over a conversational LangGraph agent** that
queries the **`watchline-discovery`** Neo4j knowledge graph (read-only), with a
**Geosupport** sidecar for address resolution and optional web search for the
deepest investigations. The agent is an **orchestrator, not a reasoner**: it
turns a plain-English question into parameterized graph queries, applies explicit
reliability rules, and explains the result — it never asserts anything a tool
didn't return.

Two layers, cleanly separated:

- **The agent/tool library** (`watchline/discovery/agent/`) — a LangGraph agent
  plus the Cypher tool library it calls. Usable on its own (see
  `watchline/discovery/agent/__init__.py` and `main.py`): create a session (a
  `thread_id` + trust/persona config), pass a turn, get back structured, cited
  results.
- **The UI** (`watchline/discovery/ui/`) — a Streamlit app that streams the
  agent's progress and answer, renders the evidence behind it, tracks per-query
  cost, and exports a branded HTML report.

## Repository map

```
watchline/
  discovery/
    agent/
      graph.py          # build_agent(): top-level Tier 1–3 agent + middleware; exports `graph` for langgraph dev
      investigator.py   # build_investigator(): the Tier-4 Deep Agent (run_cypher + web search)
      middleware.py     # TrustGate (tool visibility), ToolCallGuard, session-state capture, persona prompt
      session.py        # TrustLevel, personas, DiscoveryContext (context_schema), resolve_trust_level/persona
      state.py          # DiscoveryState: session state beyond message history (focus_entities, working_set, …)
      tools/            # the shared Cypher tool library + registry (all_tools)
      reliability.py    # Type I/II tagging applied to tool payloads
      caveats.py        # canonical caveat text for Type II elements (single source of truth)
      cypher_guard.py   # read-only enforcement: refuses writes/admin in model-authored Cypher
      db.py             # read-only Cypher execution helper
      geocode.py        # address → BBL via the Geosupport sidecar
      names.py          # landlord-name resolution
      vocab.py          # cross-source vocabulary (e.g. HPD vs DOB class collisions)
    ui/
      app.py            # the Streamlit app (entrypoint) + the API-key gate
      stream.py         # pure stream parsing → Token/ToolStart/ToolResult/Answer/Cost + Evidence
      sidebar.py        # trust/persona controls + sample queries
      cost.py           # cache-aware per-query cost accounting
      report.py         # deterministic branded HTML report (pure; to_html)
      samples.py        # curated sample questions
  shared/
    connections.py      # Neo4j driver + .env loading (read-only access)
tests/                  # hermetic (default) + integration + llm + llm_deep tiers
deploy/                 # Docker Compose stack (Neo4j + Geosupport + app + Caddy) — see deploy/README.md
sidecar/                # Geosupport sidecar image
langgraph.json          # discovery_agent → watchline.discovery.agent.graph:graph
```

## Running it (developer)

Python 3.13, managed with [uv](https://docs.astral.sh/uv/). Full run/deploy
instructions are in `README.md` and `deploy/README.md`; the dev essentials:

```bash
uv sync                                   # install deps
cp .env.example .env                      # set NEO4J_URI/USER/PASSWORD (+ ANTHROPIC_API_KEY, optional TAVILY)

make ui-start                             # Streamlit UI in the background → http://localhost:8501
make ui-logs                              # tail it     |  make ui-stop
uv run streamlit run watchline/discovery/ui/app.py   # …or run in the foreground

uv run langgraph dev                      # LangGraph Studio for the agent alone (multi-turn/threads)
```

The app runs against a Neo4j you already have (e.g. Neo4j Desktop) plus an
optional local Geosupport. Address-lookup features need Geosupport at
`GEOSUPPORT_URL`; the landlord and deep-investigation features don't.

**Model.** `build_model()` reads `WATCHLINE_MODEL` at call time, defaulting to
`MODEL_ID = "claude-sonnet-5"`; set `WATCHLINE_MODEL=claude-opus-5` for
production. Test tiers pin cheaper models via `WATCHLINE_TEST_MODEL` (Haiku) and
`WATCHLINE_TEST_DEEP_MODEL` (Sonnet).

## Architecture

A tool-calling LangGraph agent handles Tiers 1–3 directly; **Tier 4 is a single
tool backed by a Deep Agent**, spawned with fresh, isolated context so its
iterative query/rank/correlate loop doesn't pollute the main thread — it returns
one synthesized, cited report.

### Query tiers → execution path

| Tier | Name | Engine | Shape |
|---|---|---|---|
| 1 | Simple Lookup | Direct parameterized Cypher | One entity, ≤1 hop, deterministic |
| 2 | Simple Aggregation | Direct parameterized Cypher | Count/group/summarize over a bounded scope |
| 3 | Multi-hop / Relational | Bounded-hop traversal tool | 2–4 hop subgraph; may need disambiguation |
| 4 | Deep Investigative | Deep Agent tool (`investigator.py`) | Open-ended, iterative, narrative + citations |

The **Tier 1–3 tool library is shared**: the top-level agent uses it for the fast
path, and the Tier-4 deep agent is handed the same tools for its internal
investigation (plus `run_cypher` for model-authored queries and web search).
Write a tool once, use it from both places.

**Tier and persona are separate axes** — tier picks the engine; persona picks the
policy (tone/register/disclaimers) wrapped around the engine's output. Never
conflate them into one routing dimension.

Per-turn order of operations: (1) resolve pronouns / indexed references /
implicit continuation against session state; (2) classify the resolved intent
(new question, refinement, or instruction to a running Tier-4 thread); (3) route
by tier; (4) apply the persona policy.

### Middleware stack

`build_agent()` composes middleware in this order (first = outermost):
`[session_state, trust_gate, persona_prompt, prompt_caching, tool_call_guard]`.

- **`session_state`** captures/updates `DiscoveryState` from each turn.
- **`trust_gate`** (`TrustGate` + `visible_tools`) controls **which tools the
  model can even see** based on `trust_level` — this is where Tier-4 gating lives.
- **`persona_prompt`** injects the tone/register policy.
- **`prompt_caching`** (`AnthropicPromptCachingMiddleware`) caches the
  system+tools prefix; behaviour-neutral, cost-only.
- **`tool_call_guard`** (`ToolCallGuard`) is a final safety net on tool calls.

### Trust & persona contract

The library does **not** authenticate or vet users — the calling app passes
context at session creation as `configurable` fields (not tool args):

- **`trust_level`** — `"public"` | `"vetted"`. Only `"vetted"` unlocks the Tier-4
  tool. **Fail closed**: missing/malformed/unknown → `"public"`. Never infer or
  upgrade trust from anything said mid-thread.
- **`persona`** — `"general_public"` | `"tenant_advocate"` | `"journalist"` |
  `"watchdog_agency"`. Shapes tone only; **never** confers capability. A
  self-declared `"journalist"` is not `"vetted"`.

Both are set once per session; to elevate trust, start a new thread. Enforce
gating in the **middleware/tool-visibility layer**, never as a prompt instruction
— the graph carries a lot of free text the deep agent reads directly (NOV
descriptions, raw ACRIS/HPD `raw_record` JSON), a real prompt-injection surface.

### Session state (`state.py` — `DiscoveryState`)

Beyond message history: `focus_entities` (most-recent entity per type, for
pronouns), `working_set` (implicit scoped collection for aggregations),
`comparison_set` (explicit "compare X to Y" list — aligned side by side, never
summed), `last_result` (stable indices for "the second one"), `thread_mode`,
`investigation_state` (Tier-4 partial findings; persists until closed),
`disambiguation_history`.

**Every response that resolved a pronoun/indexed reference/ambiguous name reports
what it resolved to** as metadata (e.g. `resolved: "he" → Landlord ACT-LL-47644`)
— this drives the UI's "interpreting 'he' as…" and is how correction works
(overwrite the focus slot, don't append).

### Tool library & reliability tagging

Adopt the Type I/II/III/IV taxonomy, orthogonal to tier, and **tag each tool
statically** at write time by which labels/rel types it touches:

- **Type I** — directly-sourced fields only.
- **Type II** — touches a derived element (`Landlord`, `Portfolio`,
  `APPARENT_CONTROL`, `CONNECTED_BY_*`).
- **Type III** — Tier-4's own self-generated Cypher (`run_cypher`).
- **Type IV** — Type III plus web/registry search.

`reliability.py` applies tags; **every tool touching a Type II element returns
caveat text** (short inline form + long narrative form). Caveat wording lives in
`caveats.py` — one canonical pair per element, reused everywhere; don't hardcode
strings per tool.

**"Who owns this building?" always returns both answers, labeled** —
`Building.dof_ownername` (Type I, "recorded owner," may be a shell LLC) and the
`Landlord` reached via `APPARENT_CONTROL` (Type II, "apparent controller"). When
they disagree, surface the disagreement. This is the most common Tier-1 query.

**Ambiguity — never silently guess.** Narrow with session context first
(deterministic), else return a structured "needs disambiguation" result (capped
list, each with distinguishing detail) for the agent to ask about; record the
choice in `disambiguation_history`.

### The UI layer (`ui/`)

- **`app.py`** — the Streamlit entrypoint. Streams progress + a token-streamed
  answer, renders the Evidence panel, the per-query cost caption, and an export
  panel. Opens with an **API-key gate**: if `ANTHROPIC_API_KEY` is unset it shows
  a setup screen (key held in-process for the session only); a missing
  `TAVILY_API_KEY` is a non-blocking "web search disabled" notice.
- **`stream.py`** — *pure* stream parsing (no Streamlit): agent events →
  `Token`/`ToolStart`/`ToolResult`/`Answer`/`Cost` and an `Evidence` structure.
  This is where most agent→UI logic lives and where it's unit-tested.
- **`cost.py`** — cache-aware token cost accounting. **`report.py`** — pure,
  deterministic branded HTML report (`to_html`). **`sidebar.py`** — trust/persona
  controls + samples.

Keep UI logic testable: parsing/formatting go in pure modules (`stream.py`,
`cost.py`, `report.py`) with hermetic tests; `app.py` only renders their output
and is covered by Streamlit `AppTest`.

## The graph (`watchline-discovery`)

The live Neo4j graph is authoritative; `reliability.py`/`caveats.py` encode which
elements are derived. Five node types, all implying `:WatchlineNode`:

- **`Building`** — DOF/PLUTO record. Key `bbl`. Type I (`address`, `borough`,
  `bin`, lat/long, `residential_units`, `year_built`, `building_class`, `rs_*`,
  `dof_*` incl. `dof_ownername`).
- **`Actor`** — any party in a public record. Key `actor_id`. Mostly raw,
  unresolved ACRIS parties. Type I.
- **`Landlord`** — a label some `Actor`s also carry (not a separate identity):
  resolved/curated landlord entities with a business address and a `bbls` list.
  Type II.
- **`Portfolio`** — a computed cluster of `Landlord`s (GDS WCC+Louvain),
  self-documenting via `method`/`run_id`. Type II.
- **`Event`** — timestamped public-record event. Key `event_id`. Sources: HPD
  Complaints/Violations/VacateOrders, ACRIS Deed/Mortgage/{Satisfaction,Assignment},
  DOB Violations, ECB Judgments, HPD-Litigations, Marshal Evictions. `raw_record`
  embeds source JSON. Type I.

| Relationship | Direction | Notes |
|---|---|---|
| `HAS_EVENT` | `Building → Event` | Type I |
| `REGISTERED_FOR` | `Actor → Building` | HPD registration mirror. Type I |
| `PARTY_TO` | `Actor → Event` | Type I |
| `REFERENCES` | `Event → Event` | Document citation. Type I |
| `CONNECTED_BY_NAME` | `Landlord ↔ Landlord` | Fuzzy identity signal, weighted. Type II |
| `CONNECTED_BY_ADDRESS` | `Landlord ↔ Landlord` | Shared-address signal, weighted. Type II |
| `MEMBER_OF` | `Landlord → Portfolio` | Type II |
| `IN_PORTFOLIO` | `Building → Portfolio` | Type II |
| `APPARENT_CONTROL` | `Landlord → Building` | Heuristic (~18.5% of edges have no matching `REGISTERED_FOR`). Type II |

A raw ACRIS `Actor` is **not** guaranteed to have an edge into the
`Landlord`/`APPARENT_CONTROL` graph — there's no explicit "this party resolved to
this landlord" edge, only the shared-name/shared-address inferences. Design tools
and disambiguation with this gap in mind.

## Guardrails (non-negotiable)

- **Read-only graph access, always** — including Tier-4's self-generated Cypher.
  `cypher_guard.py` refuses writes/admin; reuse `watchline.shared.connections`.
- **Fail closed on trust** — enforced in middleware/tool-visibility, never prompt.
- **Never emit or imply a legal ownership/control determination.** `Landlord`,
  `APPARENT_CONTROL`, and `Portfolio` are inferred — always carry their caveats.
- **Bound hops/rows/search calls** on Tier 3 and Tier 4 — no unbounded traversals
  or external-search loops.
- **Deterministic re-query** — a refinement ("just the Class A ones") triggers a
  fresh, precisely filtered Cypher call; never have the model recompute or recall
  a number from turns back.
- **Compact large outputs** — return a summary + stable IDs/handle, not raw rows,
  for token efficiency and so indexed references stay resolvable.

## Testing

Three cost-tiered tiers; the default run is hermetic (no graph, no model, no
money). Markers are declared in `pyproject.toml`.

```bash
uv run pytest                 # hermetic (default: -m 'not integration and not llm and not llm_deep')
uv run pytest -m integration  # live Neo4j discovery graph, read-only; needs .env
uv run pytest -m llm          # calls Claude (Haiku via WATCHLINE_TEST_MODEL); asserts tool invocation, not prose
uv run pytest -m llm_deep     # a full Tier-4 investigation (Sonnet); slowest/priciest — opt in explicitly
```

Keep new logic testable at the hermetic tier: pure functions over captured tool
payloads / stream events, so the fast suite stays the primary signal. Integration
and llm tiers assert *structural* properties (a tool was called, caveats/provenance
are present, a reference resolved) — never answer prose.

## Adding features — conventions

- **New graph capability?** Add a parameterized Cypher tool under
  `agent/tools/`, register it in `tools/registry.py`, tag its reliability type,
  and return caveats for any Type II element it touches. Add hermetic tests over
  its payload shape.
- **Model-authored queries** only ever run inside Tier-4 via `run_cypher`, behind
  `cypher_guard`. Don't add a second path that lets the model write Cypher into
  the fast tiers.
- **New UI behavior?** Put parsing/formatting in a pure module (`stream.py`/
  `cost.py`/`report.py`) with unit tests; keep `app.py` a thin renderer covered
  by `AppTest`.
- **Trust/persona** are the only capability/policy axes — extend them in
  `session.py`/`middleware.py`, keep gating in the visibility layer.
