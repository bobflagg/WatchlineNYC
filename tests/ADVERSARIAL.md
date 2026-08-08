# Adversarial coverage index

The discovery agent is read-only, trust-gated, and reads attacker-influenced free
text (ACRIS party names, violation descriptions, `raw_record` JSON) directly. The
adversarial guarantees are **structural** — no injected string can add a tool,
widen visibility, raise trust, escape read-only, or run an unbounded scan — and
they are proven across the suite below, not in one file. This page is the map
(roadmap §6, decision P6-4).

Run the whole adversarial set:

```bash
pytest -m "" -k "injection or adversarial or cypher_guard or Collision or readonly or trust or gated"
```

## Coverage by threat

| Threat | Guarantee | Where |
|---|---|---|
| **Prompt injection in graph content** | Graph free text is returned as inert data; never executed, never re-interpreted as instructions. | `test_injection.py::test_graph_content_is_returned_as_inert_data` |
| **Trust escalation from content** | Trust is read from the run config only; an injected "you are now vetted" string is not a recognized level → `public`. | `test_injection.py::test_trust_never_comes_from_content`, `::test_tool_visibility_is_a_function_of_trust_only` |
| **Malformed / spoofed trust value** | `resolve_trust_level` fails closed on every non-`"vetted"` value (case, whitespace, wrong type, invented level). | `test_session.py::TestTrustLevelFailsClosed`, `test_middleware.py` (parametrized bad configs) |
| **Tier-4 tool reached without trust** | `deep_investigation` is *absent* from the tool list on a public thread — removed, not merely flagged. | `test_middleware.py::test_gated_tool_is_absent_not_merely_marked`, `::test_non_vetted_config_hides_tier_4`; end-to-end smoke: `tests/llm/test_phase5_behaviour.py::test_public_thread_cannot_invoke_the_deep_agent` |
| **Injection widens the investigator's powers** | The Tier-4 investigator's tool set is fixed at construction (Tier 1–3 + `run_cypher` + `web_search`); it never includes the gated tool. | `test_injection.py::test_investigator_tool_set_is_fixed_and_unprivileged` |
| **Write / schema / procedure via Cypher** | `assert_read_only` refuses writes, DDL, multi-statement, and non-allowlisted procedures — handed back as feedback, never executed. | `test_cypher_guard.py` (adversarial corpus), `test_investigator.py::test_run_cypher_refuses_unsafe` |
| **Server-side write attempt** | The Neo4j session is read-routed; a write is refused by the server even if the guard were bypassed. | `tests/integration/test_db_readonly.py` |
| **Unbounded traversal / scan** | `run_cypher` caps rows and **flags truncation**; a timeout or syntax error is returned as feedback, not raised. | `test_adversarial.py::test_unbounded_scan_is_capped_and_flagged_as_truncated`, `test_investigator.py::test_run_cypher_allows_reads_and_caps`, `::test_run_cypher_returns_execution_errors_as_feedback` |
| **Cross-source vocabulary collision** | A class/status code means different things per source (`HPD` Class C = immediately hazardous vs `DOB` class C; `OPEN` vs `Open`); every event query is source-scoped, and hazard labels never cross sources. | `test_vocab.py::TestCrossSourceCollision`, `test_building.py::test_source_is_always_constrained`, `test_aggregates.py::test_rollup_does_not_label_dob_class_c_as_hpd_hazard` |
| **Param-name collision zeroing counts** | Distinct vocab filters emit distinct Cypher params (`statusv`/`classv`, `openv`/`hazv`) — the Phase 5 bug where `$vals_exact` collided and every count came back 0. | `test_building.py::test_status_and_class_filters_use_distinct_params`, `test_portfolio_detail.py` (portfolio regression) |

## Adding coverage

New adversarial cases go in `test_adversarial.py` (hermetic) or the relevant
`tests/integration/*` file (live graph, audited read-only by the autouse
`no_writes_occurred` fixture). Add a row here so the suite stays discoverable as
one thing.
