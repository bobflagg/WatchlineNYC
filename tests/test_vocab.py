"""Hermetic tests for the event vocabulary — validation checks 5.1 through 5.4.

No Neo4j, no network. Live-data agreement is checked by
``tests/integration/test_vocab_drift.py`` (validation 5.5).

The tests worth reading first are :class:`TestCaseVariantsUnify` and
:class:`TestCrossSourceCollision`. They encode the two bugs this module exists
to make impossible, both of which produce a *plausible wrong number* rather than
an error.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.vocab import (
    HPD_HAZARD_CLASSES,
    HPD_IMMEDIATELY_HAZARDOUS,
    HPD_INFORMATIONAL_CLASSES,
    HPD_VIOLATION_CLASSES,
    hpd_hazard_filter,
    OPEN_STATUSES,
    VALID_PAIRS,
    ClassScheme,
    EventType,
    RawFilter,
    Source,
    Status,
    VocabularyError,
    canonical_class,
    canonical_status,
    class_filter,
    class_schemes_for,
    expected_raw_classes,
    expected_raw_statuses,
    is_open,
    require_pair,
    status_filter,
)


class TestPairValidation:
    """Validation 5.4 — invalid pairs rejected, all real pairs accepted."""

    def test_eleven_pairs(self):
        """ACRIS contributes four; missing it was a real earlier error."""
        assert len(VALID_PAIRS) == 11

    @pytest.mark.parametrize(("source", "event_type"), sorted(VALID_PAIRS))
    def test_all_real_pairs_accepted(self, source, event_type):
        assert require_pair(source, event_type) == (source, event_type)

    @pytest.mark.parametrize(
        ("source", "event_type"),
        [
            ("DOB", "Complaint"),
            ("Marshal", "Violation"),
            ("HPD", "Judgment"),
            ("ECB", "Violation"),
            ("ACRIS", "Complaint"),
            ("HPD-Litigations", "Eviction"),
            ("DOB", "VacateOrder"),
        ],
    )
    def test_impossible_pairs_rejected(self, source, event_type):
        with pytest.raises(VocabularyError, match="does not emit"):
            require_pair(source, event_type)

    def test_both_hpd_and_dob_emit_violation(self):
        """The overlap that makes source_name mandatory."""
        assert (Source.HPD, EventType.VIOLATION) in VALID_PAIRS
        assert (Source.DOB, EventType.VIOLATION) in VALID_PAIRS

    @pytest.mark.parametrize("source", ["hpd", "HPD ", "Hpd", "unknown", ""])
    def test_unknown_source_rejected(self, source):
        with pytest.raises(VocabularyError, match="Unknown source_name"):
            require_pair(source, "Violation")

    def test_missing_source_rejected(self):
        """Validation 5.5 / task 5.5 — a source is required, not optional."""
        with pytest.raises(VocabularyError, match="both required"):
            require_pair(None, "Violation")
        with pytest.raises(VocabularyError, match="both required"):
            require_pair("HPD", None)


class TestCaseVariantsUnify:
    """Validation 5.2 — the half-the-rows bug.

    HPD Complaint stores 'OPEN'/'CLOSE'; HPD Violation stores 'Open'/'Close'.
    A caller must get the right answer without knowing that.
    """

    @pytest.mark.parametrize("raw", ["OPEN", "Open", "open", "  open  ", "oPeN"])
    def test_complaint_open_variants(self, raw):
        assert canonical_status("HPD", "Complaint", raw) is Status.OPEN

    @pytest.mark.parametrize("raw", ["OPEN", "Open", "open", "oPeN"])
    def test_violation_open_variants(self, raw):
        assert canonical_status("HPD", "Violation", raw) is Status.OPEN

    @pytest.mark.parametrize("raw", ["CLOSE", "Close", "close"])
    def test_close_variants(self, raw):
        assert canonical_status("HPD", "Complaint", raw) is Status.CLOSED
        assert canonical_status("HPD", "Violation", raw) is Status.CLOSED

    def test_filter_covers_the_real_stored_casing(self):
        """The generated filter must match what is actually in the graph.

        Complaints store uppercase and violations titlecase, so a single
        hardcoded literal would silently miss one of them. Comparison is via
        toUpper, so both resolve to the same predicate.
        """
        complaint = status_filter("HPD", "Complaint", Status.OPEN)
        violation = status_filter("HPD", "Violation", Status.OPEN)
        assert complaint.exact == ("OPEN",)
        assert violation.exact == ("OPEN",)

    def test_predicate_is_case_insensitive_by_construction(self):
        fragment, params = status_filter("HPD", "Complaint", Status.OPEN).to_cypher("e.status")
        assert "toUpper(e.status)" in fragment
        assert params["vals_exact"] == ["OPEN"]


class TestCrossSourceCollision:
    """Validation 5.3 — HPD class 'C' and DOB class 'C' must never conflate."""

    def test_same_code_different_scheme(self):
        hpd_scheme, hpd_value = canonical_class("HPD", "Violation", "C")
        dob_scheme, dob_value = canonical_class("DOB", "Violation", "C")
        assert hpd_value == dob_value == "C"
        assert hpd_scheme is ClassScheme.HPD_HAZARD
        assert dob_scheme is ClassScheme.DOB_CODE
        assert hpd_scheme is not dob_scheme, (
            "The same code from two sources must carry different schemes, or a "
            "caller cannot tell 2.5M HPD rows from 180k unrelated DOB rows"
        )

    @pytest.mark.parametrize("code", ["A", "B", "C"])
    def test_shared_codes_all_distinguished(self, code):
        assert canonical_class("HPD", "Violation", code)[0] is ClassScheme.HPD_HAZARD
        assert canonical_class("DOB", "Violation", code)[0] is ClassScheme.DOB_CODE

    def test_class_filter_requires_a_source(self):
        """A class filter with no source is impossible to construct."""
        with pytest.raises(VocabularyError):
            class_filter(None, "Violation", "C")
        with pytest.raises(TypeError):
            class_filter("Violation", codes="C")  # type: ignore[call-arg]

    def test_hpd_only_code_not_recognized_for_dob(self):
        """'I' is HPD-only; DOB has no such code."""
        assert canonical_class("HPD", "Violation", "I")[0] is ClassScheme.HPD_HAZARD
        assert canonical_class("DOB", "Violation", "I")[0] is None


class TestHpdHazardSemantics:
    """The correction: Class C is immediately hazardous, not Class A."""

    def test_immediately_hazardous_is_c(self):
        assert HPD_IMMEDIATELY_HAZARDOUS == "C"
        assert HPD_VIOLATION_CLASSES["C"].label == "immediately hazardous"

    def test_class_a_is_non_hazardous(self):
        """Guards against reintroducing the doc error from the example-queries
        skill, which called Class A immediately hazardous."""
        assert HPD_VIOLATION_CLASSES["A"].label == "non-hazardous"
        assert "immediately" not in HPD_VIOLATION_CLASSES["A"].label

    def test_severity_ordering(self):
        assert (
            HPD_VIOLATION_CLASSES["A"].severity
            < HPD_VIOLATION_CLASSES["B"].severity
            < HPD_VIOLATION_CLASSES["C"].severity
        )

    def test_class_i_is_unranked(self):
        """'I' = Information: an administrative notice, not a hazard finding.

        Unranked rather than ranked zero, so it cannot be compared against the
        A/B/C hazard scale at all.
        """
        assert HPD_VIOLATION_CLASSES["I"].severity is None
        assert HPD_VIOLATION_CLASSES["I"].is_hazard is False
        assert "administrative" in HPD_VIOLATION_CLASSES["I"].label

    def test_abc_are_hazard_classes(self):
        for code in ("A", "B", "C"):
            assert HPD_VIOLATION_CLASSES[code].is_hazard is True


class TestHazardScaleExcludesClassI:
    """Class I must not inflate hazard counts.

    804,440 rows carry it. Included in a "how many hazardous violations"
    aggregate, they would read as physical conditions in buildings — the same
    category of error as the Class A mislabelling, just quieter.
    """

    def test_hazard_scale_is_abc_only(self):
        assert HPD_HAZARD_CLASSES == frozenset({"A", "B", "C"})
        assert "I" not in HPD_HAZARD_CLASSES
        assert HPD_INFORMATIONAL_CLASSES == frozenset({"I"})

    def test_default_filter_excludes_class_i(self):
        assert hpd_hazard_filter().exact == ("A", "B", "C")

    def test_life_safety_slice(self):
        assert hpd_hazard_filter({HPD_IMMEDIATELY_HAZARDOUS}).exact == ("C",)

    @pytest.mark.parametrize("codes", ["I", {"I"}, {"A", "I"}, {"c", "i"}])
    def test_class_i_rejected_with_an_explanation(self, codes):
        """Asking for I via the hazard filter is almost always a mistake."""
        with pytest.raises(VocabularyError, match="hazard scale"):
            hpd_hazard_filter(codes)

    def test_class_i_still_reachable_deliberately(self):
        """A class *breakdown* legitimately shows all four classes."""
        raw_filter = class_filter("HPD", "Violation", {"A", "B", "C", "I"})
        assert raw_filter.exact == ("A", "B", "C", "I")

    def test_hazard_filter_is_case_insensitive(self):
        assert hpd_hazard_filter({"a", "b"}).exact == ("A", "B")


class TestUnknownAndNotRecorded:
    """Validation 5.1 — nothing is silently dropped, and the two flavours of
    absence stay distinguishable."""

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_null_is_not_recorded(self, raw):
        assert canonical_status("DOB", "Violation", raw) is Status.NOT_RECORDED

    @pytest.mark.parametrize(
        ("source", "event_type", "raw"),
        [
            ("Marshal", "Eviction", "EAST"),  # misaligned column in the source
            ("DOB", "Violation", "Pending"),  # not a DOB status
            ("HPD", "Violation", "Active"),  # HPD violations use Open/Close
            ("HPD", "Complaint", "Resolved"),
        ],
    )
    def test_unrecognized_is_unknown(self, source, event_type, raw):
        assert canonical_status(source, event_type, raw) is Status.UNKNOWN

    def test_not_recorded_differs_from_unknown(self):
        """"Never recorded" and "unrecognizable" are different facts."""
        assert Status.NOT_RECORDED is not Status.UNKNOWN
        assert canonical_status("Marshal", "Eviction", None) is Status.NOT_RECORDED
        assert canonical_status("Marshal", "Eviction", "EAST") is Status.UNKNOWN

    def test_ecb_literal_unknown_string(self):
        """ECB genuinely stores the string 'Unknown' in 3 rows."""
        assert canonical_status("ECB", "Judgment", "Unknown") is Status.UNKNOWN

    def test_acris_has_no_status(self):
        assert canonical_status("ACRIS", "DeedTransfer", None) is Status.NOT_RECORDED


class TestStatusOutcomesPreserved:
    """Distinct outcomes stay distinct, per the chosen granularity."""

    @pytest.mark.parametrize(
        ("source", "event_type", "raw", "expected"),
        [
            ("DOB", "Violation", "Active", Status.OPEN),
            ("DOB", "Violation", "Resolved", Status.RESOLVED),
            ("DOB", "Violation", "Dismissed", Status.DISMISSED),
            ("ECB", "Judgment", "ACTIVE", Status.OPEN),
            ("ECB", "Judgment", "RESOLVE", Status.RESOLVED),
            ("HPD", "VacateOrder", "Active", Status.OPEN),
            ("HPD", "VacateOrder", "Rescinded", Status.RESCINDED),
            ("Marshal", "Eviction", "POSSESSION", Status.POSSESSION),
            ("Marshal", "Eviction", "P", Status.POSSESSION),
            ("Marshal", "Eviction", "EVICTION", Status.EVICTED),
        ],
    )
    def test_mapping(self, source, event_type, raw, expected):
        assert canonical_status(source, event_type, raw) is expected

    def test_resolved_and_dismissed_are_not_merged(self):
        """A dismissed violation is not a resolved one."""
        assert Status.RESOLVED is not Status.DISMISSED

    def test_ecb_raw_is_resolve_not_resolved(self):
        """The graph stores 'RESOLVE'; 'RESOLVED' is not a real value."""
        assert canonical_status("ECB", "Judgment", "RESOLVE") is Status.RESOLVED
        assert canonical_status("ECB", "Judgment", "RESOLVED") is Status.UNKNOWN


class TestIsOpen:
    @pytest.mark.parametrize(
        ("source", "event_type", "raw"),
        [
            ("HPD", "Complaint", "OPEN"),
            ("HPD", "Violation", "Open"),
            ("HPD", "VacateOrder", "Active"),
            ("DOB", "Violation", "Active"),
            ("ECB", "Judgment", "ACTIVE"),
            ("HPD-Litigations", "CourtFiling", "PENDING"),
        ],
    )
    def test_open_cases(self, source, event_type, raw):
        assert is_open(source, event_type, raw) is True

    @pytest.mark.parametrize(
        ("source", "event_type", "raw"),
        [
            ("HPD", "Complaint", "CLOSE"),
            ("HPD", "Violation", "Close"),
            ("DOB", "Violation", "Dismissed"),
            ("DOB", "Violation", "Resolved"),
            ("ECB", "Judgment", "RESOLVE"),
            ("HPD", "VacateOrder", "Rescinded"),
            ("HPD-Litigations", "CourtFiling", "CLOSED - 01/02/2020"),
            ("ACRIS", "Mortgage", None),
        ],
    )
    def test_closed_cases(self, source, event_type, raw):
        assert is_open(source, event_type, raw) is False

    def test_open_statuses_is_the_documented_set(self):
        assert OPEN_STATUSES == frozenset({Status.OPEN, Status.PENDING})


class TestLitigationDateSuffix:
    """HPD-Litigations status embeds a date with inconsistent separators."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("GRANTED - 02/08/2022", Status.GRANTED),
            ("Exempt- 08/29/2022", Status.EXEMPT),
            ("DENIED , 10/31/2016", Status.DENIED),
            ("WithDrawn/Abandoned- 12/27/2017", Status.WITHDRAWN),
            ("Rejected- 01/01/2020", Status.REJECTED),
            ("Rescinded- 01/01/2020", Status.RESCINDED),
            # values with no date suffix at all
            ("CLOSED", Status.CLOSED),
            ("PENDING", Status.PENDING),
            ("APPLICATION", Status.PENDING),
            ("Settlement", Status.SETTLED),
        ],
    )
    def test_prefix_is_extracted(self, raw, expected):
        assert canonical_status("HPD-Litigations", "CourtFiling", raw) is expected

    def test_filter_uses_prefix_matching(self):
        """1,580 distinct values cannot be enumerated, so match by prefix."""
        raw_filter = status_filter("HPD-Litigations", "CourtFiling", Status.GRANTED)
        assert raw_filter.prefixes == ("GRANTED",)
        assert raw_filter.exact == ()
        fragment, params = raw_filter.to_cypher("e.status")
        assert "STARTS WITH" in fragment
        assert params["vals_prefix_0"] == "GRANTED"

    def test_open_filter_covers_pending_and_application(self):
        raw_filter = status_filter("HPD-Litigations", "CourtFiling", OPEN_STATUSES)
        assert set(raw_filter.prefixes) == {"PENDING", "APPLICATION"}


class TestEcbTwoSchemes:
    """ECB Judgment mixes a numeric scheme and a hazard scheme in one column."""

    def test_both_schemes_declared(self):
        schemes = class_schemes_for("ECB", "Judgment")
        assert set(schemes) == {ClassScheme.ECB_CLASS_NUMBER, ClassScheme.ECB_HAZARD}

    @pytest.mark.parametrize("raw", ["CLASS - 1", "CLASS - 2", "CLASS - 3"])
    def test_numeric_scheme(self, raw):
        assert canonical_class("ECB", "Judgment", raw)[0] is ClassScheme.ECB_CLASS_NUMBER

    @pytest.mark.parametrize("raw", ["Hazardous", "Non-Hazardous", "non-hazardous"])
    def test_hazard_scheme(self, raw):
        assert canonical_class("ECB", "Judgment", raw)[0] is ClassScheme.ECB_HAZARD

    def test_unknown_value_has_no_scheme(self):
        scheme, value = canonical_class("ECB", "Judgment", "Unknown")
        assert scheme is None
        assert value == "Unknown"

    def test_single_scheme_sources_declare_one(self):
        assert class_schemes_for("HPD", "Violation") == (ClassScheme.HPD_HAZARD,)
        assert class_schemes_for("Marshal", "Eviction") == (
            ClassScheme.MARSHAL_PROPERTY_TYPE,
        )


class TestViolationClassIsRepurposed:
    """The field means something different per source; the scheme says what."""

    @pytest.mark.parametrize(
        ("source", "event_type", "raw", "expected"),
        [
            ("HPD", "Complaint", "EMERGENCY", ClassScheme.HPD_COMPLAINT_URGENCY),
            ("HPD", "VacateOrder", "Fire Damage", ClassScheme.HPD_VACATE_CAUSE),
            ("HPD-Litigations", "CourtFiling", "Tenant Action", ClassScheme.LITIGATION_CASE_TYPE),
            ("Marshal", "Eviction", "RESIDENTIAL", ClassScheme.MARSHAL_PROPERTY_TYPE),
            ("ACRIS", "DeedTransfer", "DEED", ClassScheme.ACRIS_DOCUMENT_TYPE),
        ],
    )
    def test_scheme_reported(self, source, event_type, raw, expected):
        assert canonical_class(source, event_type, raw)[0] is expected

    def test_null_class(self):
        assert canonical_class("HPD", "Violation", None) == (None, None)


class TestRawFilter:
    def test_empty_filter_is_falsey_and_matches_nothing(self):
        empty = RawFilter()
        assert not empty
        fragment, params = empty.to_cypher("e.status")
        assert fragment == "false"
        assert params == {}

    def test_null_only_filter(self):
        raw_filter = status_filter("DOB", "Violation", Status.NOT_RECORDED)
        assert raw_filter.match_null is True
        fragment, _ = raw_filter.to_cypher("e.status")
        assert "IS NULL" in fragment

    def test_multiple_statuses_combine(self):
        raw_filter = status_filter(
            "DOB", "Violation", {Status.RESOLVED, Status.DISMISSED}
        )
        assert set(raw_filter.exact) == {"RESOLVED", "DISMISSED"}

    def test_class_filter_uppercases(self):
        raw_filter = class_filter("HPD", "Violation", {"c", "a"})
        assert raw_filter.exact == ("A", "C")

    def test_class_filter_rejects_empty(self):
        with pytest.raises(VocabularyError, match="At least one"):
            class_filter("HPD", "Violation", set())

    def test_generated_cypher_passes_the_guard(self):
        """A predicate this module builds must survive cypher_guard."""
        from watchline.discovery.agent.cypher_guard import is_read_only

        fragment, _ = status_filter("HPD", "Violation", Status.OPEN).to_cypher("e.status")
        cypher = (
            "MATCH (b:Building {bbl: $bbl})-[:HAS_EVENT]->(e:Event) "
            f"WHERE e.source_name = $source AND e.event_type = $type AND {fragment} "
            "RETURN count(e) AS c"
        )
        assert is_read_only(cypher), cypher


class TestDriftDetectorInputs:
    """The expected-value exports must stay consistent with the mappings."""

    def test_every_raw_status_maps_to_something(self):
        for (source, event_type), raws in expected_raw_statuses().items():
            for raw in raws:
                canonical = canonical_status(source, event_type, raw)
                assert isinstance(canonical, Status)

    def test_every_raw_class_is_recognized_or_deliberately_not(self):
        for (source, event_type), raws in expected_raw_classes().items():
            for raw in raws:
                scheme, value = canonical_class(source, event_type, raw)
                assert value == raw
                # ECB 'Unknown' is the one documented unrecognized value.
                if not (source is Source.ECB and raw == "Unknown"):
                    assert scheme is not None, f"{source}/{event_type}: {raw!r}"

    def test_pairs_with_status_have_a_mapping_entry(self):
        for source, event_type in VALID_PAIRS:
            # Should not raise; every valid pair is representable.
            assert canonical_status(source, event_type, None) is Status.NOT_RECORDED
