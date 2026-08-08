"""Structural checks on the example-query fixtures — validation 7.1, 7.3, 7.4.

Hermetic. That every parameter still *resolves* against the live graph is
checked by ``tests/integration/test_fixtures_resolve.py`` (validation 7.2).

Regenerate with::

    uv run python scripts/generate_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests/fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class TestAllFortyPresent:
    """Validation 7.1 — one parameter set per example query."""

    def test_forty_queries(self, fixtures):
        assert len(fixtures["queries"]) == 40

    def test_ten_per_tier(self, fixtures):
        counts: dict[int, int] = {}
        for query in fixtures["queries"]:
            counts[query["tier"]] = counts.get(query["tier"], 0) + 1
        assert counts == {1: 10, 2: 10, 3: 10, 4: 10}

    def test_numbering_is_complete(self, fixtures):
        for tier in (1, 2, 3, 4):
            numbers = sorted(q["n"] for q in fixtures["queries"] if q["tier"] == tier)
            assert numbers == list(range(1, 11)), f"tier {tier}: {numbers}"

    def test_every_query_has_params(self, fixtures):
        for query in fixtures["queries"]:
            assert query["params"], f"tier {query['tier']} #{query['n']} has no params"

    def test_no_unresolved_anchors(self, fixtures):
        """The generator marks a fixture it could not resolve. None may remain.

        This is the check that would have caught `456 West 24th Street` — a
        parameter nobody had confirmed resolves to anything.
        """
        unresolved = [
            f"tier {q['tier']} #{q['n']}"
            for q in fixtures["queries"]
            if "_unresolved_anchor" in q["params"]
        ]
        assert not unresolved, f"Fixtures with unresolved anchors: {unresolved}"

    def test_every_query_names_its_tool(self, fixtures):
        for query in fixtures["queries"]:
            assert query.get("tool"), f"tier {query['tier']} #{query['n']}"


class TestBlockedOnRecorded:
    """Validation 7.5 — fixtures record parameters, not answers, while the
    tool does not exist. A query loses ``blocked_on`` once its tool is built."""

    #: Tools built and mergeable so far (mirrors the generator's BUILT_TOOLS).
    BUILT = {
        "lookup_building_ownership", "resolve_address", "resolve_landlord_name",
        "lookup_building", "lookup_building_events", "lookup_landlord",
        "landlord_portfolio_membership", "aggregate_building_events",
        "aggregate_landlord_portfolio_events", "aggregate_events_by_geo_time",
        "portfolio_summary", "portfolio_buildings_by_borough",
        "sister_buildings", "trace_ownership_chain", "control_network",
        "shared_address_landlords", "portfolio_buildings_with_violations",
        "portfolio_litigation", "ownership_vs_registration_diff",
        "trace_actor_to_landlord", "deep_investigation",
    }

    def test_blocked_on_names_the_tool_when_present(self, fixtures):
        for query in fixtures["queries"]:
            if "blocked_on" in query:
                assert query["blocked_on"] == query["tool"], f"tier {query['tier']} #{query['n']}"

    def test_built_tools_are_unblocked(self, fixtures):
        for query in fixtures["queries"]:
            if query["tool"] in self.BUILT:
                assert "blocked_on" not in query, f"tier {query['tier']} #{query['n']}"

    def test_no_expected_answers_asserted(self, fixtures):
        """A fixture must not claim a result a tool has never produced."""
        for query in fixtures["queries"]:
            assert "expected" not in query
            assert "expected_result" not in query


class TestEdgeCases:
    """Validation 7.3 — the awkward cases are present deliberately."""

    REQUIRED = {
        "building_without_apparent_control",
        "landlord_ungeocodable_bizaddr",
        "portfolio_singleton",
        "event_null_date",
        "registered_for_null_role",
        "raw_actor_not_landlord",
    }

    def test_required_edge_cases_present(self, fixtures):
        assert self.REQUIRED <= set(fixtures["edge_cases"])

    @pytest.mark.parametrize("name", sorted(REQUIRED))
    def test_each_edge_case_has_a_real_entity(self, fixtures, name):
        entry = fixtures["edge_cases"][name]
        assert entry["entity"] is not None, f"{name} has no resolved entity"
        assert entry["why"], f"{name} has no explanation"

    def test_no_apparent_control_is_labelled_as_common(self, fixtures):
        """~80% of buildings. Calling it an edge case invites treating it as
        rare, which is how the flagship tool gets built wrong."""
        why = fixtures["edge_cases"]["building_without_apparent_control"]["why"]
        assert "COMMON" in why

    def test_future_dated_event_captured(self, fixtures):
        """Only 4 exist in 42.3M events, but one bad row is the whole answer to
        "when was this last sold?"."""
        entity = fixtures["edge_cases"]["event_future_dated"]["entity"]
        assert entity is not None
        assert entity["event_date"] > fixtures["provenance"]["captured_at"]

    def test_deed_transfer_fixture_is_not_future_dated(self, fixtures):
        """The normal-path fixture must not be one of the corrupt rows.

        It originally was: the most recent DeedTransfer in the graph is dated
        2028, so an unbounded "latest" query answered with a date that has not
        happened.
        """
        deed = fixtures["anchors"]["building_with_deed_transfer"]
        assert deed["last_sold"] <= fixtures["provenance"]["captured_at"]


class TestKnownAbsent:
    def test_multiple_controllers_documented_as_absent(self, fixtures):
        """Recorded so nobody hunts for a fixture that cannot be built."""
        absent = fixtures["known_absent"]
        assert "building_with_multiple_controllers" in absent
        assert "1:1" in absent["building_with_multiple_controllers"]

    def test_cardinality_finding_recorded(self, fixtures):
        card = fixtures["anchors"]["controller_cardinality"]
        assert card["max_controllers_per_building"] == 1
        assert card["buildings_with_a_controller"] == 171347


class TestProvenance:
    """Validation 7.4 — fixtures are refreshable, so record what they came from."""

    def test_capture_date(self, fixtures):
        assert fixtures["provenance"]["captured_at"]

    def test_selection_method_documented(self, fixtures):
        selection = fixtures["provenance"]["selection"]
        assert "Deterministic" in selection

    def test_portfolio_run_recorded(self, fixtures):
        """Portfolios are regenerated per run and portfolio_id is not stable
        across them (decision D7), so the run must be on record."""
        runs = fixtures["provenance"]["portfolio_runs"]
        assert runs and runs[0]["run_id"]

    def test_portfolio_ids_belong_to_the_recorded_run(self, fixtures):
        """A portfolio_id embeds its run. Catches a fixture left behind by an
        earlier pipeline run, which would otherwise resolve to nothing."""
        run_id = fixtures["provenance"]["portfolio_runs"][0]["run_id"]
        for name, anchor in fixtures["anchors"].items():
            if anchor and isinstance(anchor.get("portfolio_id"), str):
                assert run_id in anchor["portfolio_id"], name

    def test_node_counts_recorded(self, fixtures):
        counts = fixtures["provenance"]["node_counts"]
        assert set(counts) == {"Building", "Actor", "Landlord", "Event", "Portfolio"}
        assert all(value > 0 for value in counts.values())


class TestFixtureQueriesRespectKnownTraps:
    """The fixtures must not encode mistakes this project already found."""

    def test_violation_filters_name_a_source(self, fixtures):
        """HPD and DOB both emit 'Violation' and share codes A/B/C."""
        for query in fixtures["queries"]:
            params = query["params"]
            if "violation_class" in params:
                assert "source_name" in params, (
                    f"tier {query['tier']} #{query['n']} filters violation_class "
                    "without a source_name"
                )

    def test_life_safety_queries_use_class_c(self, fixtures):
        """Class C is immediately hazardous; A is non-hazardous."""
        for query in fixtures["queries"]:
            text = query["text"].lower()
            if "class c" in text or "life-safety" in text or "hazard" in text:
                params = query["params"]
                if "violation_class" in params:
                    codes = params["violation_class"]
                    codes = [codes] if isinstance(codes, str) else codes
                    assert "A" not in codes, (
                        f"tier {query['tier']} #{query['n']} uses Class A for a "
                        "hazard query"
                    )
                    assert "I" not in codes, (
                        f"tier {query['tier']} #{query['n']} includes Class I, "
                        "which is administrative rather than a hazard"
                    )

    def test_portfolio_size_query_filters_by_size(self, fixtures):
        """Most of the 97,863 portfolios are singletons."""
        query = next(q for q in fixtures["queries"] if q["tier"] == 4 and q["n"] == 10)
        assert "min_member_count" in query["params"]
