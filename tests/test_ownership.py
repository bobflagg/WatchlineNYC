"""Hermetic tests for the flagship ownership tool — validation 2.1 to 2.9.

No Neo4j: ``db.read`` is replaced with canned rows whose shapes were captured
from the live graph on 2026-07-31. Live behaviour is checked in
``tests/integration/test_ownership_live.py``.

The tests worth reading first are :class:`TestNoControllerIsASuccessfulAnswer`
and :class:`TestBothAnswersAreVerbatim`. They encode the two ways this tool
could be subtly wrong while appearing to work: treating the ~80% majority case
as a failure, and tidying up a name that needs to stay citable.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.caveats import CAVEATS, DerivedElement
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.names import OwnershipVerdict
from watchline.discovery.agent.reliability import RELIABILITY_KEY
from watchline.discovery.agent.tools import ownership
from watchline.discovery.agent.tools.ownership import (
    APPARENT_CONTROLLER_LABEL,
    RECORDED_OWNER_LABEL,
    lookup_building_ownership,
)

# Captured from the live graph 2026-07-31.
ROW_WITH_CONTROLLER = {
    "bbl": "1000050010",
    "address": "115 BROAD STREET",
    "borough": "Manhattan",
    "recorded_owner": "25 WATER OWNER, LLC",
    "apparent_controllers": [
        {
            "actor_id": "ACT-LL-90202",
            "name": "PETER HUNGERFORD",
            "bizaddr": "515 MADISON AVENUE 29 FL, MANHATTAN NY",
            "method": "GDS WCC+Louvain",
            "run_id": "20260729T002106Z",
        }
    ],
}

ROW_WITHOUT_CONTROLLER = {
    "bbl": "1000010010",
    "address": "140 CARDER ROAD",
    "borough": "Manhattan",
    "recorded_owner": "GOVERNORS ISLAND CORPORATION",
    "apparent_controllers": [],
}

# 1,863 buildings have a null dof_ownername; some of them have a controller.
ROW_NULL_RECORDED_OWNER = {
    "bbl": "1014269035",
    "address": "Unknown",
    "borough": "Manhattan",
    "recorded_owner": None,
    "apparent_controllers": [
        {
            "actor_id": "ACT-LL-1000",
            "name": "ANDREW LEVISON",
            "bizaddr": None,
            "method": "GDS WCC+Louvain",
            "run_id": "20260729T002106Z",
        }
    ],
}

# Names that agree, to exercise the agrees path without needing the one live
# example (which group 6 will find and add as a fixture).
ROW_AGREEING_NAMES = {
    "bbl": "1000000001",
    "address": "1 EXAMPLE STREET",
    "borough": "Manhattan",
    "recorded_owner": "LIBERT, LARS PETER",
    "apparent_controllers": [
        {
            "actor_id": "ACT-LL-4",
            "name": "(LARS) PETER LIBERT",
            "bizaddr": "21-21 45 ROAD, QUEENS NY",
            "method": "GDS WCC+Louvain",
            "run_id": "20260729T002106Z",
        }
    ],
}


@pytest.fixture
def fake_read(monkeypatch):
    """Replace db.read with canned rows. Returns a setter."""

    def _set(row: dict | None):
        def _read(cypher, parameters=None, **kwargs):
            records = [] if row is None else [row]
            return ReadResult(records=records, truncated=False, row_cap=1)

        monkeypatch.setattr(ownership, "read", _read)

    return _set


class TestThreeResultClasses:
    """Validation 2.1 — each outcome is distinct and complete."""

    def test_controller_present(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result["found"] is True
        assert result["recorded_owner"]["name"] == "25 WATER OWNER, LLC"
        assert len(result["apparent_controllers"]) == 1
        assert result["verdict"] == OwnershipVerdict.DIFFERS.value

    def test_building_not_found(self, fake_read):
        fake_read(None)
        result = lookup_building_ownership("9999999999")
        assert result["found"] is False
        assert result["reason"]
        assert result["recorded_owner"] is None
        assert result["apparent_controllers"] == []

    def test_not_found_is_not_an_empty_payload(self, fake_read):
        """A caller must distinguish "no such building" from "nothing known
        about this building's ownership"."""
        fake_read(None)
        result = lookup_building_ownership("9999999999")
        assert result["bbl"] == "9999999999"
        assert "found" in result and "reason" in result


class TestNoControllerIsASuccessfulAnswer:
    """~80% of buildings have no apparent controller. If this reads as an error
    or an empty result, the tool is wrong for the majority of the housing stock.
    """

    def test_found_is_true(self, fake_read):
        fake_read(ROW_WITHOUT_CONTROLLER)
        assert lookup_building_ownership("1000010010")["found"] is True

    def test_recorded_owner_still_returned(self, fake_read):
        fake_read(ROW_WITHOUT_CONTROLLER)
        result = lookup_building_ownership("1000010010")
        assert result["recorded_owner"]["name"] == "GOVERNORS ISLAND CORPORATION"

    def test_controllers_is_empty_list_not_none(self, fake_read):
        fake_read(ROW_WITHOUT_CONTROLLER)
        result = lookup_building_ownership("1000010010")
        assert result["apparent_controllers"] == []
        assert result["controller_count"] == 0

    def test_verdict_is_not_comparable_not_differs(self, fake_read):
        """"Nothing to compare" is not "they disagree". Conflating them would
        report a disagreement for four fifths of all buildings."""
        fake_read(ROW_WITHOUT_CONTROLLER)
        verdict = lookup_building_ownership("1000010010")["verdict"]
        assert verdict == OwnershipVerdict.NOT_COMPARABLE.value
        assert verdict != OwnershipVerdict.DIFFERS.value

    def test_no_reason_field_implying_failure(self, fake_read):
        fake_read(ROW_WITHOUT_CONTROLLER)
        assert "reason" not in lookup_building_ownership("1000010010")


class TestBothAnswersAreVerbatim:
    """Validation 2.2 — the graph's exact record is what is citable."""

    def test_recorded_owner_byte_for_byte(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result["recorded_owner"]["name"] == ROW_WITH_CONTROLLER["recorded_owner"]

    def test_controller_name_byte_for_byte(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        expected = ROW_WITH_CONTROLLER["apparent_controllers"][0]["name"]
        assert result["apparent_controllers"][0]["name"] == expected

    def test_dirty_names_are_not_cleaned(self, fake_read):
        """Real controller names carry leading punctuation. Tidying them would
        break citation and hide a data-quality signal."""
        row = dict(ROW_WITH_CONTROLLER)
        row["recorded_owner"] = "JEAN-JOSEPH, FLORENCE"
        row["apparent_controllers"] = [
            {**ROW_WITH_CONTROLLER["apparent_controllers"][0], "name": ",MARIA CROSS"}
        ]
        fake_read(row)
        result = lookup_building_ownership("1000050010")
        assert result["recorded_owner"]["name"] == "JEAN-JOSEPH, FLORENCE"
        assert result["apparent_controllers"][0]["name"] == ",MARIA CROSS"

    def test_null_recorded_owner_is_none_not_empty_string(self, fake_read):
        fake_read(ROW_NULL_RECORDED_OWNER)
        result = lookup_building_ownership("1014269035")
        assert result["recorded_owner"] is None
        assert result["found"] is True
        assert result["verdict"] == OwnershipVerdict.NOT_COMPARABLE.value


class TestBothAnswersAreLabelled:
    """Validation 2.3 — a consumer must not be able to mistake the inference
    for ownership."""

    def test_labels_present(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result["recorded_owner"]["label"] == RECORDED_OWNER_LABEL
        assert result["apparent_controllers"][0]["label"] == APPARENT_CONTROLLER_LABEL

    def test_controller_is_never_described_as_an_owner(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        controller = lookup_building_ownership("1000050010")["apparent_controllers"][0]
        assert not any("owner" in key.casefold() for key in controller)
        assert "apparent" in controller["label"]

    def test_each_side_carries_its_reliability_type(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result["recorded_owner"]["reliability_type"] == "I"
        assert result["apparent_controllers"][0]["reliability_type"] == "II"

    def test_each_side_names_its_source(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert "Finance" in result["recorded_owner"]["source"]
        assert "Inferred" in result["apparent_controllers"][0]["source"]

    def test_no_top_level_owner_field(self, fake_read):
        """There is deliberately no single "owner" — that is the whole point."""
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert "owner" not in result
        assert "owner_name" not in result


class TestCaveatsAndReliability:
    """Validation 2.4 — Type II with all three caveats, text from caveats.py."""

    def test_type_ii(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result[RELIABILITY_KEY]["type"] == "II"

    def test_three_caveats(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        elements = {c["element"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert elements == {"Landlord", "APPARENT_CONTROL", "Building.dof_ownername"}

    def test_caveat_text_matches_the_canonical_module(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        by_element = {c["element"]: c["text"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert by_element["APPARENT_CONTROL"] == CAVEATS[DerivedElement.APPARENT_CONTROL].short
        assert by_element["Landlord"] == CAVEATS[DerivedElement.LANDLORD].short
        assert by_element["Building.dof_ownername"] == CAVEATS[DerivedElement.DOF_OWNERNAME].short

    def test_caveats_present_even_with_no_controller(self, fake_read):
        """The caveats describe what the tool consulted, not what it found. An
        empty controller list is exactly when a reader might over-read the
        recorded owner as the answer."""
        fake_read(ROW_WITHOUT_CONTROLLER)
        result = lookup_building_ownership("1000010010")
        assert len(result[RELIABILITY_KEY]["caveats"]) == 3

    def test_not_tier_4_gated(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        result = lookup_building_ownership("1000050010")
        assert result[RELIABILITY_KEY]["requires_tier_4"] is False

    def test_static_declaration_is_inspectable(self):
        """The tool-filtering layer reads this without calling the tool."""
        declaration = lookup_building_ownership.reliability
        assert declaration.type.value == "II"
        assert "APPARENT_CONTROL" in declaration.elements


class TestProvenance:
    """Validation 2.5 — the answer came from one heuristic run and says so."""

    def test_method_and_run_id_carried(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        provenance = lookup_building_ownership("1000050010")["apparent_controllers"][0][
            "provenance"
        ]
        assert provenance["method"] == "GDS WCC+Louvain"
        assert provenance["run_id"] == "20260729T002106Z"

    def test_business_address_carried(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        controller = lookup_building_ownership("1000050010")["apparent_controllers"][0]
        assert controller["business_address"] == "515 MADISON AVENUE 29 FL, MANHATTAN NY"

    def test_actor_id_carried_as_the_stable_handle(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        controller = lookup_building_ownership("1000050010")["apparent_controllers"][0]
        assert controller["actor_id"] == "ACT-LL-90202"


class TestControllersAreACollection:
    """Validation 2.6 and 2.7.

    APPARENT_CONTROL is 1:1 across all 171,347 controlled buildings (verified
    2026-07-31), so **no fixture and no live query can exercise more than one
    controller**. `graph_type.cypher` does not constrain it, so the code handles
    a collection; the two-controller test below is explicitly synthetic and is
    not evidence that the situation occurs.
    """

    def test_always_a_list(self, fake_read):
        for row in (ROW_WITH_CONTROLLER, ROW_WITHOUT_CONTROLLER):
            fake_read(row)
            assert isinstance(lookup_building_ownership(row["bbl"])["apparent_controllers"], list)

    def test_synthetic_two_controllers_each_get_their_own_comparison(self, fake_read):
        """SYNTHETIC — no such building exists in the graph today."""
        row = dict(ROW_WITH_CONTROLLER)
        row["apparent_controllers"] = [
            ROW_WITH_CONTROLLER["apparent_controllers"][0],
            {
                "actor_id": "ACT-LL-99999",
                "name": "25 WATER OWNER LLC",
                "bizaddr": None,
                "method": "GDS WCC+Louvain",
                "run_id": "20260729T002106Z",
            },
        ]
        fake_read(row)
        result = lookup_building_ownership("1000050010")
        assert result["controller_count"] == 2
        verdicts = [c["comparison"]["verdict"] for c in result["apparent_controllers"]]
        assert verdicts == [OwnershipVerdict.DIFFERS.value, OwnershipVerdict.AGREES.value]

    def test_synthetic_multiple_controllers_have_no_single_verdict(self, fake_read):
        """One verdict cannot describe two comparisons, so it is None rather
        than a fiction."""
        row = dict(ROW_WITH_CONTROLLER)
        row["apparent_controllers"] = ROW_WITH_CONTROLLER["apparent_controllers"] * 2
        fake_read(row)
        assert lookup_building_ownership("1000050010")["verdict"] is None


class TestComparisonAndEvidence:
    def test_agreeing_names(self, fake_read):
        fake_read(ROW_AGREEING_NAMES)
        result = lookup_building_ownership("1000000001")
        assert result["verdict"] == OwnershipVerdict.AGREES.value

    def test_evidence_travels_with_the_comparison(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        comparison = lookup_building_ownership("1000050010")["apparent_controllers"][0][
            "comparison"
        ]
        assert comparison["shared_tokens"] == []
        assert set(comparison["recorded_owner_only_tokens"]) == {"25", "llc", "owner", "water"}
        assert set(comparison["apparent_controller_only_tokens"]) == {"peter", "hungerford"}

    def test_no_numeric_confidence_anywhere(self, fake_read):
        """A score between two party names is a quasi-identity claim (D2)."""
        fake_read(ROW_WITH_CONTROLLER)
        comparison = lookup_building_ownership("1000050010")["apparent_controllers"][0][
            "comparison"
        ]
        for key, value in comparison.items():
            assert not isinstance(value, (int, float)), key


class TestInputHandling:
    """Validation 2.9 — the BBL is bound, not interpolated."""

    def test_cypher_uses_a_parameter(self):
        assert "$bbl" in ownership._OWNERSHIP_CYPHER

    def test_cypher_has_no_format_placeholders(self):
        """Guards against a future refactor interpolating the value."""
        assert "{bbl}" not in ownership._OWNERSHIP_CYPHER
        assert "%s" not in ownership._OWNERSHIP_CYPHER

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-bbl",
            "",
            "   ",
            "100005001",  # 9 digits
            "10000500100",  # 11 digits
            "6000050010",  # borough 6 does not exist
            "0000050010",  # borough 0 does not exist
            "1000050010; MATCH (n) DETACH DELETE n",
            "1' OR true //",
            None,
            123,
        ],
    )
    def test_malformed_bbl_is_refused_without_querying(self, bad, monkeypatch):
        def _explode(*args, **kwargs):
            raise AssertionError("db.read must not be called for a malformed BBL")

        monkeypatch.setattr(ownership, "read", _explode)
        result = lookup_building_ownership(bad)
        assert result["found"] is False
        assert "BBL" in result["reason"]

    def test_whitespace_is_tolerated(self, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        assert lookup_building_ownership("  1000050010  ")["found"] is True

    @pytest.mark.parametrize("borough_digit", ["1", "2", "3", "4", "5"])
    def test_all_five_borough_digits_accepted(self, borough_digit, fake_read):
        fake_read(ROW_WITH_CONTROLLER)
        assert lookup_building_ownership(f"{borough_digit}000050010")["found"] is True
