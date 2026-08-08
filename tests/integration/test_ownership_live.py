"""The ownership tool against the live graph — validation 2.1, 2.4, 2.8, 2.9.

Run with ``pytest -m integration``.

Uses the Phase 0 fixtures rather than hardcoded BBLs, so a pipeline change that
invalidates an entity surfaces as a fixture-resolution failure with a clear
remedy (regenerate) rather than as a confusing failure here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.caveats import CAVEATS, DerivedElement
from watchline.discovery.agent.cypher_guard import assert_read_only
from watchline.discovery.agent.names import OwnershipVerdict
from watchline.discovery.agent.reliability import RELIABILITY_KEY
from watchline.discovery.agent.tools import ownership
from watchline.discovery.agent.tools.ownership import lookup_building_ownership

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def controlled(fixtures) -> dict:
    return fixtures["anchors"]["building_with_apparent_control"]


@pytest.fixture(scope="module")
def uncontrolled(fixtures) -> dict:
    return fixtures["edge_cases"]["building_without_apparent_control"]["entity"]


class TestCypherIsAccepted:
    def test_guard_allows_the_template(self):
        """Validation 2.8. Also covered by the repo-wide AST sweep, asserted
        here too so a failure points straight at this tool."""
        assert_read_only(ownership._OWNERSHIP_CYPHER)


class TestControllerPresent:
    def test_returns_both_answers(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        assert result["found"] is True
        assert result["recorded_owner"]["name"] == controlled["recorded_owner"]
        names = [c["name"] for c in result["apparent_controllers"]]
        assert controlled["landlord_name"] in names

    def test_controller_actor_id_matches_the_fixture(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        ids = [c["actor_id"] for c in result["apparent_controllers"]]
        assert controlled["landlord_actor_id"] in ids

    def test_provenance_matches_the_recorded_portfolio_run(self, controlled, fixtures):
        """The APPARENT_CONTROL edge and the Portfolio nodes come from the same
        clustering run, so the run_id should agree."""
        run_id = fixtures["provenance"]["portfolio_runs"][0]["run_id"]
        result = lookup_building_ownership(controlled["bbl"])
        assert result["apparent_controllers"][0]["provenance"]["run_id"] == run_id

    def test_verdict_is_a_real_verdict(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        assert result["verdict"] in {v.value for v in OwnershipVerdict}

    def test_display_fields_present(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        assert result["address"] == controlled["address"]
        assert result["borough"] == controlled["borough"]


class TestNoControllerPath:
    """The majority of the housing stock. Must read as an answer, not a miss."""

    def test_is_a_successful_answer(self, uncontrolled):
        result = lookup_building_ownership(uncontrolled["bbl"])
        assert result["found"] is True
        assert result["recorded_owner"]["name"] == uncontrolled["recorded_owner"]
        assert result["apparent_controllers"] == []
        assert result["verdict"] == OwnershipVerdict.NOT_COMPARABLE.value

    def test_caveats_still_attached(self, uncontrolled):
        """Precisely when a reader might over-read the recorded owner as the
        whole answer."""
        result = lookup_building_ownership(uncontrolled["bbl"])
        assert len(result[RELIABILITY_KEY]["caveats"]) == 3


class TestBuildingNotFound:
    def test_explicit_not_found(self):
        result = lookup_building_ownership("5999999999")
        assert result["found"] is False
        assert "5999999999" in result["reason"]


class TestCaveatTextAgainstTheCanonicalModule:
    """Validation 2.4 — the text a caller receives is the canonical text."""

    def test_all_three_match(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        by_element = {c["element"]: c["text"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert by_element == {
            "Landlord": CAVEATS[DerivedElement.LANDLORD].short,
            "APPARENT_CONTROL": CAVEATS[DerivedElement.APPARENT_CONTROL].short,
            "Building.dof_ownername": CAVEATS[DerivedElement.DOF_OWNERNAME].short,
        }

    def test_no_caveat_asserts_ownership(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        for caveat in result[RELIABILITY_KEY]["caveats"]:
            assert "owns" not in caveat["text"].casefold()


class TestParametersAreBound:
    """Validation 2.9 — proven against the real driver, not just by inspection."""

    def test_injection_shaped_bbl_never_reaches_the_graph(self):
        result = lookup_building_ownership("1000050010; MATCH (n) DETACH DELETE n")
        assert result["found"] is False

    def test_wellformed_but_absent_bbl_returns_not_found(self):
        """Confirms the parameter is compared as data: a valid-shaped BBL that
        does not exist yields no rows rather than an error."""
        assert lookup_building_ownership("5999999998")["found"] is False


class TestKnownCardinality:
    """Validation 2.7 — record the 1:1 fact rather than implying coverage."""

    def test_fixture_building_has_exactly_one_controller(self, controlled):
        result = lookup_building_ownership(controlled["bbl"])
        assert result["controller_count"] == 1

    def test_cardinality_finding_still_holds(self, fixtures):
        """If this ever changes, the multi-controller path becomes testable for
        real and the synthetic test in the hermetic tier can be replaced."""
        recorded = fixtures["anchors"]["controller_cardinality"]
        assert recorded["max_controllers_per_building"] == 1
