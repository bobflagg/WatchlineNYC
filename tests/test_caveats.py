"""Tests for caveat text and reliability tagging — validation 4.1 to 4.5.

Hermetic: no Neo4j, no network.

:class:`TestTextMatchesSkillExactly` is the load-bearing one. The caveats are
what keep this system's output from reading as a legal ownership claim, and
duplicated wording drifts — drifted wording gets weaker. So the text is diffed
against ``discovery-schema-reference/SKILL.md`` on every run, and the module is
checked to be the only copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from watchline.discovery.agent.caveats import (
    CAVEATS,
    Caveat,
    CaveatKind,
    DerivedElement,
    caveat_for,
    caveats_for,
    long_forms,
    short_forms,
)
from watchline.discovery.agent.reliability import (
    RELIABILITY_KEY,
    TYPE_I_ELEMENTS,
    TYPE_II_ELEMENTS,
    ExternalSource,
    Reliability,
    ReliabilityDeclarationError,
    ReliabilityType,
    reliability_of,
    tagged,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / ".claude/skills/discovery-schema-reference/SKILL.md"

# The two classes below diff caveat wording against the discovery-schema-reference
# skill, which isn't vendored into this lean repo. Skip them when it's absent (as the
# integration/llm tiers skip without their prerequisites); they run wherever the skill
# file is present (the full development checkout).
_needs_skill = pytest.mark.skipif(
    not SKILL_PATH.exists(),
    reason="discovery-schema-reference skill not present in this checkout",
)


def _normalize(text: str) -> str:
    """Collapse the skill file's line wrapping to single spaces."""
    return " ".join(text.split())


def _parse_skill_caveats() -> dict[str, dict[str, str]]:
    """Extract every Short/Long pair from the skill's caveat section.

    Parsed rather than duplicated, so the test cannot drift from the skill in
    the same way the module might.
    """
    content = SKILL_PATH.read_text(encoding="utf-8")
    section = content.split("## Caveat text")[1].split("\n## ")[0]

    pattern = re.compile(
        r"\*\*`(?P<element>[^`]+)`\*\*" r'|- (?P<kind>Short|Long): "(?P<value>[^"]*)"',
        re.DOTALL,
    )
    found: dict[str, dict[str, str]] = {}
    current: str | None = None
    for match in pattern.finditer(section):
        if match.group("element"):
            current = match.group("element")
        elif current is not None:
            found.setdefault(current, {})[match.group("kind").lower()] = _normalize(
                match.group("value")
            )
    return found


@_needs_skill
class TestSkillParsing:
    """Guard the parser itself — a broken parser would make 4.1 vacuous."""

    def test_skill_file_exists(self):
        assert SKILL_PATH.is_file(), f"Missing {SKILL_PATH}"

    def test_parser_finds_all_five_elements(self):
        parsed = _parse_skill_caveats()
        assert set(parsed) == {element.value for element in DerivedElement}, (
            f"Parsed {sorted(parsed)}; the skill and DerivedElement disagree"
        )

    def test_parser_finds_both_forms(self):
        for element, forms in _parse_skill_caveats().items():
            assert set(forms) == {"short", "long"}, f"{element}: got {sorted(forms)}"

    def test_parser_would_notice_a_change(self):
        """Sanity: the parsed text is non-trivial, not empty strings."""
        for element, forms in _parse_skill_caveats().items():
            assert len(forms["short"]) > 20, element
            assert len(forms["long"]) > 100, element


@_needs_skill
class TestTextMatchesSkillExactly:
    """Validation 4.1 — drift between module and skill fails the build."""

    @pytest.mark.parametrize("element", list(DerivedElement))
    def test_short_form_matches(self, element):
        expected = _parse_skill_caveats()[element.value]["short"]
        assert CAVEATS[element].short == expected, (
            f"{element.value} short form differs from the skill.\n"
            f"  skill:  {expected!r}\n  module: {CAVEATS[element].short!r}"
        )

    @pytest.mark.parametrize("element", list(DerivedElement))
    def test_long_form_matches(self, element):
        expected = _parse_skill_caveats()[element.value]["long"]
        assert CAVEATS[element].long == expected, (
            f"{element.value} long form differs from the skill.\n"
            f"  skill:  {expected!r}\n  module: {CAVEATS[element].long!r}"
        )

    def test_connected_by_address_acknowledges_under_connection(self):
        """The amendment must survive. It exists because the clustering matches
        on a raw string, so formatting variance drops real connections."""
        long_form = CAVEATS[DerivedElement.CONNECTED_BY_ADDRESS].long
        assert "under- and over-connect" in long_form
        assert "fail to link records that should be connected" in long_form

    def test_connected_by_name_also_acknowledges_both(self):
        assert "under- and over-connect" in CAVEATS[DerivedElement.CONNECTED_BY_NAME].long


class TestModuleIsTheOnlyCopy:
    """Validation 4.2 — no caveat text duplicated in production code."""

    def test_no_caveat_text_outside_caveats_module(self):
        sources = [
            path
            for path in (REPO_ROOT / "watchline").rglob("*.py")
            if path.name != "caveats.py"
        ]
        assert sources, "Found no other modules to check — test would be vacuous"

        offenders: list[str] = []
        for caveat in CAVEATS.values():
            # A distinctive fragment; matching the whole string would miss a
            # partial copy-paste, which is the likelier mistake.
            for form, text in (("short", caveat.short), ("long", caveat.long)):
                fragment = text[:40]
                for path in sources:
                    if fragment in path.read_text(encoding="utf-8"):
                        offenders.append(
                            f"{caveat.element.value} {form} form appears in "
                            f"{path.relative_to(REPO_ROOT)}"
                        )
        assert not offenders, (
            "Caveat text must live only in caveats.py so it cannot drift:\n  "
            + "\n  ".join(offenders)
        )


class TestCaveatStructure:
    def test_five_reliability_warnings_and_one_interpretation_note(self):
        """dof_ownername differs in kind: the record is reliable, it just
        usually names a shell entity."""
        reliability = [c for c in CAVEATS.values() if c.kind is CaveatKind.RELIABILITY]
        interpretation = [
            c for c in CAVEATS.values() if c.kind is CaveatKind.INTERPRETATION
        ]
        assert len(reliability) == 5
        assert [c.element for c in interpretation] == [DerivedElement.DOF_OWNERNAME]

    def test_landlord_and_apparent_control_say_different_things(self):
        """One is about inferred identity, the other inferred control.

        Collapsing them would leave a bare Landlord read warning about control
        it never asserted, and say nothing about whether the records describe
        one party at all.
        """
        landlord = CAVEATS[DerivedElement.LANDLORD].long
        control = CAVEATS[DerivedElement.APPARENT_CONTROL].long
        assert landlord != control
        assert "same party" in landlord
        assert "controls this building" in control

    def test_caveats_are_immutable(self):
        with pytest.raises(Exception):
            CAVEATS[DerivedElement.PORTFOLIO].short = "weaker wording"  # type: ignore[misc]

    def test_lookup_by_string(self):
        assert caveat_for("Portfolio") is CAVEATS[DerivedElement.PORTFOLIO]

    def test_unknown_element_raises(self):
        """Fail loudly rather than emit nothing."""
        with pytest.raises(ValueError):
            caveat_for("NotAnElement")

    def test_order_is_stable_regardless_of_input_order(self):
        forward = caveats_for([DerivedElement.PORTFOLIO, DerivedElement.APPARENT_CONTROL])
        reverse = caveats_for([DerivedElement.APPARENT_CONTROL, DerivedElement.PORTFOLIO])
        assert forward == reverse

    def test_short_and_long_helpers(self):
        elements = [DerivedElement.PORTFOLIO]
        assert short_forms(elements) == (CAVEATS[DerivedElement.PORTFOLIO].short,)
        assert long_forms(elements) == (CAVEATS[DerivedElement.PORTFOLIO].long,)

    def test_no_caveat_hedges_into_a_legal_claim(self):
        """None of this text may assert ownership. Guards a future reword."""
        for caveat in CAVEATS.values():
            lowered = caveat.long.lower()
            assert "owns" not in lowered, caveat.element
            assert "is the owner" not in lowered, caveat.element


class TestStaticTagging:
    """Validation 4.4 — tags come from the declaration, not from results."""

    def test_type_i_for_directly_sourced_only(self):
        declaration = reliability_of(["Building", "Event", "HAS_EVENT"])
        assert declaration.type is ReliabilityType.TYPE_I
        assert declaration.caveats == ()

    @pytest.mark.parametrize("element", sorted(TYPE_II_ELEMENTS))
    def test_any_type_ii_element_makes_the_whole_query_type_ii(self, element):
        declaration = reliability_of(["Building", element])
        assert declaration.type is ReliabilityType.TYPE_II

    def test_self_generated_cypher_is_type_iii(self):
        declaration = reliability_of(["Building"], self_generated_cypher=True)
        assert declaration.type is ReliabilityType.TYPE_III

    def test_web_search_is_type_iv(self):
        declaration = reliability_of(
            ["Building"], external_sources=[ExternalSource.WEB_SEARCH]
        )
        assert declaration.type is ReliabilityType.TYPE_IV

    def test_registry_search_is_type_iv(self):
        declaration = reliability_of(
            ["Building"], external_sources=[ExternalSource.REGISTRY_SEARCH]
        )
        assert declaration.type is ReliabilityType.TYPE_IV

    def test_unknown_element_is_rejected(self):
        """A typo must not silently downgrade a tool to Type I."""
        with pytest.raises(ReliabilityDeclarationError, match="Unknown graph element"):
            reliability_of(["Bulding"])
        with pytest.raises(ReliabilityDeclarationError, match="Unknown graph element"):
            reliability_of(["APARENT_CONTROL"])

    def test_element_sets_do_not_overlap(self):
        assert not (TYPE_I_ELEMENTS & TYPE_II_ELEMENTS)

    def test_declaration_is_immutable(self):
        declaration = reliability_of(["Building"])
        with pytest.raises(Exception):
            declaration.type = ReliabilityType.TYPE_IV  # type: ignore[misc]


class TestGeosupportCarveOut:
    """Validation 4.5 — D10, expressed without widening it."""

    def test_geosupport_stays_type_i(self):
        declaration = reliability_of(
            ["Building"], external_sources=[ExternalSource.GEOSUPPORT]
        )
        assert declaration.type is ReliabilityType.TYPE_I
        assert declaration.requires_tier_4 is False

    def test_geosupport_does_not_suppress_type_ii(self):
        """The carve-out is about the external call, not the graph elements."""
        declaration = reliability_of(
            ["Building", "APPARENT_CONTROL"],
            external_sources=[ExternalSource.GEOSUPPORT],
        )
        assert declaration.type is ReliabilityType.TYPE_II

    @pytest.mark.parametrize(
        "source", [ExternalSource.WEB_SEARCH, ExternalSource.REGISTRY_SEARCH]
    )
    def test_other_external_sources_require_tier_4(self, source):
        declaration = reliability_of(["Building"], external_sources=[source])
        assert declaration.requires_tier_4 is True

    def test_registry_and_web_are_distinct_members(self):
        """A registry-sourced identity link is a different claim from a web
        result and must stay labellable as such."""
        assert ExternalSource.REGISTRY_SEARCH is not ExternalSource.WEB_SEARCH


class TestTypeIiImpliesCaveats:
    """Validation 4.3 — the rule is structural, not aspirational."""

    def test_type_ii_tool_with_caveats_is_accepted(self):
        @tagged(["Building", "APPARENT_CONTROL"])
        def tool() -> dict:
            return {"bbl": "1000010010"}

        payload = tool()
        assert payload[RELIABILITY_KEY]["type"] == "II"
        assert payload[RELIABILITY_KEY]["caveats"]

    def test_bare_landlord_read_now_has_a_caveat(self):
        """Tier 1 #4 — "business address on file for landlord X".

        This declaration used to fail at import because Landlord had no
        canonical caveat. It now carries the identity caveat, which is the
        relevant uncertainty for a tool that reads name and bizaddr without
        touching APPARENT_CONTROL.
        """

        @tagged(["Landlord"])
        def lookup_landlord(actor_id: str) -> dict:
            return {"actor_id": actor_id, "bizaddr": "123 MAIN STREET, BROOKLYN NY"}

        payload = lookup_landlord("ACT-LL-47644")
        assert payload[RELIABILITY_KEY]["type"] == "II"
        assert [c["element"] for c in payload[RELIABILITY_KEY]["caveats"]] == ["Landlord"]

    def test_every_type_ii_element_can_produce_a_caveat(self):
        """No Type II element may be uncoverable — otherwise some future tool
        is unwritable, which is how the Landlord gap surfaced."""
        for element in TYPE_II_ELEMENTS:

            @tagged([element])
            def tool() -> dict:
                return {}

            assert tool()[RELIABILITY_KEY]["caveats"], element

    def test_type_ii_tool_without_caveat_text_is_rejected(self):
        """The rule still bites. Simulated by narrowing the caveat map, since
        no real element is uncovered any more."""
        from watchline.discovery.agent import reliability as reliability_module

        original = reliability_module._ELEMENT_CAVEATS.copy()
        try:
            reliability_module._ELEMENT_CAVEATS.pop("Portfolio")
            with pytest.raises(ReliabilityDeclarationError, match="no reliability caveat"):

                @tagged(["Portfolio"])
                def tool() -> dict:
                    return {}
        finally:
            reliability_module._ELEMENT_CAVEATS.clear()
            reliability_module._ELEMENT_CAVEATS.update(original)

    def test_type_i_tool_needs_no_caveat(self):
        @tagged(["Building", "Event"])
        def tool() -> dict:
            return {"bbl": "1000010010"}

        assert tool()[RELIABILITY_KEY]["caveats"] == []

    def test_dof_ownername_note_alone_does_not_satisfy_type_ii(self):
        """An interpretation note is not a reliability warning.

        Simulated by narrowing the caveat map so a Type II element yields only
        the dof_ownername note.
        """
        from watchline.discovery.agent import reliability as reliability_module

        original = reliability_module._ELEMENT_CAVEATS.copy()
        try:
            reliability_module._ELEMENT_CAVEATS.pop("Landlord")
            with pytest.raises(ReliabilityDeclarationError):

                @tagged(["Landlord", "Building.dof_ownername"])
                def tool() -> dict:
                    return {}
        finally:
            reliability_module._ELEMENT_CAVEATS.clear()
            reliability_module._ELEMENT_CAVEATS.update(original)

    def test_type_iv_tool_needs_a_reliability_caveat_too(self):
        with pytest.raises(ReliabilityDeclarationError):

            @tagged(["Building"], external_sources=[ExternalSource.WEB_SEARCH])
            def tool() -> dict:
                return {}


class TestDecoratorBehaviour:
    def test_reliability_is_inspectable_statically(self):
        """The tool-filtering layer reads this without calling the tool."""

        @tagged(["Building", "Portfolio"])
        def tool() -> dict:
            return {}

        assert isinstance(tool.reliability, Reliability)
        assert tool.reliability.type is ReliabilityType.TYPE_II

    def test_wraps_preserves_identity(self):
        @tagged(["Building"])
        def my_tool() -> dict:
            """Docstring retained."""
            return {}

        assert my_tool.__name__ == "my_tool"
        assert my_tool.__doc__ == "Docstring retained."

    def test_payload_is_not_mutated_in_place(self):
        original = {"bbl": "1"}

        @tagged(["Building"])
        def tool() -> dict:
            return original

        tool()
        assert RELIABILITY_KEY not in original

    def test_non_dict_return_is_rejected(self):
        @tagged(["Building"])
        def tool():  # type: ignore[misc]
            return ["not", "a", "dict"]

        with pytest.raises(TypeError, match="must return a dict"):
            tool()

    def test_colliding_key_is_rejected(self):
        @tagged(["Building"])
        def tool() -> dict:
            return {RELIABILITY_KEY: "hijacked"}

        with pytest.raises(ReliabilityDeclarationError, match="would overwrite"):
            tool()

    def test_short_form_by_default(self):
        @tagged(["Building", "Portfolio"])
        def tool() -> dict:
            return {}

        text = tool()[RELIABILITY_KEY]["caveats"][0]["text"]
        assert text == CAVEATS[DerivedElement.PORTFOLIO].short

    def test_long_form_for_narrative_output(self):
        @tagged(["Building", "Portfolio"], long_form=True)
        def tool() -> dict:
            return {}

        text = tool()[RELIABILITY_KEY]["caveats"][0]["text"]
        assert text == CAVEATS[DerivedElement.PORTFOLIO].long

    def test_portfolio_edges_inherit_the_portfolio_caveat(self):
        """MEMBER_OF and IN_PORTFOLIO are edges into a Portfolio, so the
        Portfolio caveat covers them — they need no wording of their own."""
        for element in ("MEMBER_OF", "IN_PORTFOLIO"):
            declaration = reliability_of(["Building", element])
            assert declaration.type is ReliabilityType.TYPE_II
            assert [c.element for c in declaration.caveats] == [DerivedElement.PORTFOLIO]

    def test_flagship_tool_shape(self):
        """The Phase 1 tool: both ownership answers, both caveats."""

        @tagged(["Building", "Building.dof_ownername", "APPARENT_CONTROL"])
        def lookup_building_ownership(bbl: str) -> dict:
            return {"bbl": bbl, "recorded_owner": "X LLC", "apparent_controller": None}

        payload = lookup_building_ownership("1000010010")
        elements = {c["element"] for c in payload[RELIABILITY_KEY]["caveats"]}
        assert elements == {"APPARENT_CONTROL", "Building.dof_ownername"}
        assert payload[RELIABILITY_KEY]["type"] == "II"
        assert payload[RELIABILITY_KEY]["requires_tier_4"] is False
