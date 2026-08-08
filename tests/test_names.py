"""Tests for party-name comparison — validation checks 1.1 through 1.7.

Hermetic: no Neo4j, no network, no model.

Every pair in :class:`TestTheFourRealPairs` is taken verbatim from the live
graph. That matters more than it sounds: the reason this module exists is that
plausible-looking invented fixtures would all have passed a naive equality
check, and the real data does not.
"""

from __future__ import annotations

import inspect

import pytest

from watchline.discovery.agent import names as names_module
from watchline.discovery.agent.names import (
    LEGAL_FORM_TOKENS,
    NameComparison,
    OwnershipVerdict,
    compare_names,
    normalize,
)


class TestTheFourRealPairs:
    """Validation 1.1 — the pairs observed in the graph, with required verdicts."""

    REAL_PAIRS = [
        # Same person, surname-first vs given-name-first, plus a parenthetical.
        ("LIBERT, LARS PETER", "(LARS) PETER LIBERT", OwnershipVerdict.AGREES),
        # Same person, one-character difference (MARSILLO / ARSILLO) plus a
        # leading period. Calling this a disagreement would be wrong; calling it
        # agreement would be a claim. Hence indeterminate.
        ("ANGELO MARSILLO", ".ARSILLO ANGELO", OwnershipVerdict.INDETERMINATE),
        # Genuine divergence: a realty LLC on record, a person inferred.
        ("3071 HULL REALTY LLC", ",MARIA CROSS", OwnershipVerdict.DIFFERS),
        # The fixture building 1000050010 (115 BROAD STREET).
        ("25 WATER OWNER, LLC", "PETER HUNGERFORD", OwnershipVerdict.DIFFERS),
    ]

    @pytest.mark.parametrize(("recorded", "inferred", "expected"), REAL_PAIRS)
    def test_verdict(self, recorded, inferred, expected):
        assert compare_names(recorded, inferred).verdict is expected

    def test_naive_equality_would_get_all_four_wrong(self):
        """Guards the premise. If plain equality ever agreed with this module on
        every pair, this module would be unnecessary — and something is wrong.
        """
        for recorded, inferred, expected in self.REAL_PAIRS:
            naive = (
                OwnershipVerdict.AGREES
                if recorded.strip().casefold() == inferred.strip().casefold()
                else OwnershipVerdict.DIFFERS
            )
            if expected is not OwnershipVerdict.DIFFERS:
                assert naive is not expected, (recorded, inferred)


class TestNormalization:
    """Validation 1.2 — the punctuation the real data actually carries."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("LIBERT, LARS PETER", ("lars", "libert", "peter")),
            ("(LARS) PETER LIBERT", ("lars", "libert", "peter")),
            (",MARIA CROSS", ("cross", "maria")),
            (".ARSILLO ANGELO", ("angelo", "arsillo")),
            (".XI MEI LI", ("li", "mei", "xi")),
            ("25 WATER OWNER, LLC", ("25", "llc", "owner", "water")),
            ("3071 HULL REALTY LLC", ("3071", "hull", "llc", "realty")),
            ("GOVERNORS ISLAND CORPORATION", ("corporation", "governors", "island")),
        ],
    )
    def test_real_values(self, raw, expected):
        assert normalize(raw) == expected

    def test_token_order_is_irrelevant(self):
        """Surname-first vs given-name-first is formatting, not identity."""
        assert normalize("LIBERT, LARS PETER") == normalize("LARS PETER LIBERT")

    def test_case_is_irrelevant(self):
        assert normalize("Maria Cross") == normalize("MARIA CROSS") == normalize("maria cross")

    def test_whitespace_collapses(self):
        assert normalize("WEST   24   STREET") == ("24", "street", "west")

    def test_periods_join_rather_than_split(self):
        """'L.L.C.' is one token, not three. Splitting on periods would turn an
        abbreviation into single letters and match unrelated names."""
        assert normalize("L.L.C.") == ("llc",)
        assert normalize("O'BRIEN") == ("obrien",)

    def test_numbers_are_kept(self):
        """Many NYC entities are named after a building number; dropping it
        would lose real signal."""
        assert "3071" in normalize("3071 HULL REALTY LLC")

    @pytest.mark.parametrize("raw", [None, "", "   ", ",", "...", "()", "-- --", 123, []])
    def test_empty_and_junk_yield_no_tokens(self, raw):
        assert normalize(raw) == ()

    def test_duplicate_tokens_collapse(self):
        """'724 724 ELTON AVENUE' shapes appear in bizaddr; a repeated token is
        not extra evidence."""
        assert normalize("724 724 ELTON AVENUE") == ("724", "avenue", "elton")


class TestLegalFormsDoNotCreateFalseAgreement:
    """Validation 1.3 — suffixes are not stripped."""

    def test_llc_versus_inc_is_not_agreement(self):
        result = compare_names("X REALTY LLC", "X REALTY INC")
        assert result.verdict is not OwnershipVerdict.AGREES
        assert result.verdict is OwnershipVerdict.INDETERMINATE

    def test_suffix_present_versus_absent_is_not_agreement(self):
        assert compare_names("HULL REALTY LLC", "HULL REALTY").verdict is (
            OwnershipVerdict.INDETERMINATE
        )

    def test_identical_including_suffix_agrees(self):
        assert compare_names("3071 HULL REALTY LLC", "3071 hull realty llc").verdict is (
            OwnershipVerdict.AGREES
        )


class TestLegalFormsDoNotCreateFalseIndeterminacy:
    """The other half of the same rule, and the reason it exists.

    Sharing 'llc' is not evidence of shared identity. Without excluding legal
    forms from the overlap test, nearly every company-vs-company pair would land
    in INDETERMINATE on that token alone — draining the verdict of meaning in
    exactly the cases users care about.
    """

    def test_two_unrelated_llcs_differ(self):
        result = compare_names("25 WATER OWNER, LLC", "3071 HULL REALTY LLC")
        assert result.shared_tokens == ("llc",)
        assert result.shared_distinguishing == ()
        assert result.verdict is OwnershipVerdict.DIFFERS

    @pytest.mark.parametrize("form", sorted(LEGAL_FORM_TOKENS))
    def test_every_legal_form_is_non_distinguishing(self, form):
        result = compare_names(f"ALPHA {form}", f"BRAVO {form}")
        assert result.verdict is OwnershipVerdict.DIFFERS, form

    def test_legal_forms_still_appear_in_shared_tokens(self):
        """Excluded from the verdict, not hidden from the evidence."""
        result = compare_names("ALPHA LLC", "BRAVO LLC")
        assert "llc" in result.shared_tokens
        assert "llc" not in result.shared_distinguishing


class TestOneSidedMiddleInitials:
    """Roadmap open question 11, resolved as the one-sided variant.

    An initial present on one side and absent on the other carries no
    contradicting information, so it is disregarded. An initial present on
    *both* sides can contradict, so it is not. The asymmetry is the rule.
    """

    @pytest.mark.parametrize(
        ("recorded", "inferred"),
        [
            ("COX, AARON R", "AARON COX"),
            ("LEVIN, AARON M", "AARON LEVIN"),
            ("ABBASI, AAMIR R", "AAMIR ABBASI"),
            ("FRISCIA, PAUL J", "PAUL FRISCIA"),
        ],
    )
    def test_one_sided_initial_is_disregarded(self, recorded, inferred):
        assert compare_names(recorded, inferred).verdict is OwnershipVerdict.AGREES

    def test_the_disregarded_initial_is_reported(self):
        """An unexplained AGREES on visibly different strings would look like a
        bug. The evidence has to say what was set aside."""
        result = compare_names("COX, AARON R", "AARON COX")
        assert result.disregarded_initials == ("r",)
        assert result.left_only == ()
        assert result.right_only == ()

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("SMITH, JOHN A", "SMITH, JOHN B"),
            ("JOHN A SMITH", "JOHN B SMITH"),
            ("A JOHN SMITH", "SMITH JOHN B"),
        ],
    )
    def test_contradicting_initials_are_never_collapsed(self, left, right):
        """The father-and-son case. Zero instances in the current data — this
        holds by construction, not because none happen to exist.
        """
        result = compare_names(left, right)
        assert result.verdict is OwnershipVerdict.INDETERMINATE
        assert result.disregarded_initials == ()

    def test_matching_initials_on_both_sides_still_agree(self):
        """Nothing is dropped, but the sets are already equal."""
        result = compare_names("SMITH, JOHN A", "JOHN A SMITH")
        assert result.verdict is OwnershipVerdict.AGREES
        assert result.disregarded_initials == ()

    def test_stripping_never_empties_a_side(self):
        """A name that is only initials cannot be compared meaningfully, but
        NOT_COMPARABLE means "a side was absent". Manufacturing that state
        through our own normalization would claim more than the data says.
        """
        result = compare_names("A B", "JOHN SMITH")
        assert result.disregarded_initials == ()
        assert result.verdict is OwnershipVerdict.DIFFERS
        assert result.left_tokens == ("a", "b")

    def test_initials_do_not_rescue_genuinely_different_names(self):
        result = compare_names("COX, AARON R", "MARIA CROSS")
        assert result.verdict is OwnershipVerdict.DIFFERS

    def test_full_tokens_remain_traceable(self):
        """The raw comparison stays inspectable even when a token is
        disregarded for the verdict."""
        result = compare_names("COX, AARON R", "AARON COX")
        assert result.left_tokens == ("aaron", "cox", "r")
        assert result.right_tokens == ("aaron", "cox")

    def test_symmetric(self):
        forward = compare_names("COX, AARON R", "AARON COX")
        reverse = compare_names("AARON COX", "COX, AARON R")
        assert forward.verdict is reverse.verdict
        assert forward.disregarded_initials == reverse.disregarded_initials

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("5 HULL REALTY LLC", "HULL REALTY LLC"),
            ("1 LIBERTY PLAZA LLC", "LIBERTY PLAZA LLC"),
            ("7 WORLD TRADE LLC", "WORLD TRADE LLC"),
        ],
    )
    def test_single_digits_are_not_initials(self, left, right):
        """A single digit is a building number, not a middle initial. NYC is
        full of single-digit addresses, and dropping the digit would merge
        '5 Hull Realty' with 'Hull Realty' — plausibly different entities.
        """
        result = compare_names(left, right)
        assert result.disregarded_initials == ()
        assert result.verdict is OwnershipVerdict.INDETERMINATE


class TestNotComparable:
    """Validation 1.4 — an absent side is not a comparison."""

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            (None, "MARIA CROSS"),
            ("MARIA CROSS", None),
            (None, None),
            ("", "MARIA CROSS"),
            ("MARIA CROSS", ""),
            ("   ", "MARIA CROSS"),
            (",", "MARIA CROSS"),
        ],
    )
    def test_absent_side(self, left, right):
        result = compare_names(left, right)
        assert result.verdict is OwnershipVerdict.NOT_COMPARABLE
        assert result.comparable is False

    def test_not_comparable_is_distinct_from_differs(self):
        """"Nothing to compare" and "compared, and they differ" are different
        facts. ~80% of buildings have no apparent controller, so conflating them
        would mislabel the majority of results."""
        assert OwnershipVerdict.NOT_COMPARABLE is not OwnershipVerdict.DIFFERS
        assert compare_names(None, "MARIA CROSS").verdict is not OwnershipVerdict.DIFFERS

    def test_raw_values_preserved_even_when_not_comparable(self):
        result = compare_names(None, "MARIA CROSS")
        assert result.left_raw is None
        assert result.right_raw == "MARIA CROSS"


class TestNoSimilarityScoreExists:
    """Validation 1.5 — a score is a quasi-identity claim (D2).

    Enforced as a test so a future "helpful" addition fails here rather than
    passing review.
    """

    FORBIDDEN = ("score", "ratio", "similar", "distance", "fuzzy", "confidence", "percent")

    def test_public_api_is_exactly_as_declared(self):
        assert set(names_module.__all__) == {
            "OwnershipVerdict",
            "NameComparison",
            "LEGAL_FORM_TOKENS",
            "normalize",
            "compare_names",
        }

    def test_no_public_name_suggests_scoring(self):
        offenders = [
            name
            for name in dir(names_module)
            if not name.startswith("_")
            and any(word in name.casefold() for word in self.FORBIDDEN)
        ]
        assert not offenders, offenders

    def test_no_comparison_field_is_numeric(self):
        result = compare_names("LIBERT, LARS PETER", "(LARS) PETER LIBERT")
        for field, value in vars(result).items():
            assert not isinstance(value, (int, float)) or isinstance(value, bool), field

    def test_no_third_party_fuzzy_matcher_imported(self):
        source = inspect.getsource(names_module)
        for library in ("rapidfuzz", "fuzzywuzzy", "difflib", "Levenshtein", "jellyfish"):
            assert library not in source, library


class TestEvidenceTravelsWithTheVerdict:
    """Validation 1.6 — the evidence is what keeps this an observation."""

    def test_shared_and_disjoint_tokens_reported(self):
        result = compare_names("ANGELO MARSILLO", ".ARSILLO ANGELO")
        assert result.shared_tokens == ("angelo",)
        assert result.left_only == ("marsillo",)
        assert result.right_only == ("arsillo",)

    def test_raw_inputs_reported_verbatim(self):
        """A caller must be able to cite the record exactly as stored."""
        result = compare_names("LIBERT, LARS PETER", "(LARS) PETER LIBERT")
        assert result.left_raw == "LIBERT, LARS PETER"
        assert result.right_raw == "(LARS) PETER LIBERT"

    def test_agreement_has_no_disjoint_tokens(self):
        result = compare_names("LIBERT, LARS PETER", "(LARS) PETER LIBERT")
        assert result.left_only == ()
        assert result.right_only == ()

    def test_difference_has_no_distinguishing_overlap(self):
        assert compare_names("25 WATER OWNER, LLC", "PETER HUNGERFORD").shared_distinguishing == ()

    def test_result_is_immutable(self):
        result = compare_names("A", "B")
        with pytest.raises(Exception):
            result.verdict = OwnershipVerdict.AGREES  # type: ignore[misc]

    def test_is_a_name_comparison(self):
        assert isinstance(compare_names("A", "B"), NameComparison)


class TestSymmetry:
    """Validation 1.7 — which record came first must not change the verdict."""

    PAIRS = [pair[:2] for pair in TestTheFourRealPairs.REAL_PAIRS] + [
        ("X REALTY LLC", "X REALTY INC"),
        ("ALPHA LLC", "BRAVO LLC"),
        (None, "MARIA CROSS"),
        ("", ""),
    ]

    @pytest.mark.parametrize(("left", "right"), PAIRS)
    def test_verdict_is_symmetric(self, left, right):
        assert compare_names(left, right).verdict is compare_names(right, left).verdict

    @pytest.mark.parametrize(("left", "right"), PAIRS)
    def test_shared_tokens_are_symmetric(self, left, right):
        assert compare_names(left, right).shared_tokens == (
            compare_names(right, left).shared_tokens
        )

    @pytest.mark.parametrize(("left", "right"), PAIRS)
    def test_side_specific_evidence_swaps(self, left, right):
        """Intended asymmetry: a caller wants to know *which* record carried the
        unmatched tokens."""
        forward = compare_names(left, right)
        reverse = compare_names(right, left)
        assert forward.left_only == reverse.right_only
        assert forward.right_only == reverse.left_only


class TestVerdictEnum:
    def test_four_values(self):
        assert len(OwnershipVerdict) == 4

    def test_values_are_stable_strings(self):
        """Serialized into tool payloads, so the wire values are a contract."""
        assert OwnershipVerdict.AGREES == "agrees"
        assert OwnershipVerdict.DIFFERS == "differs"
        assert OwnershipVerdict.INDETERMINATE == "indeterminate"
        assert OwnershipVerdict.NOT_COMPARABLE == "not_comparable"

    def test_docstring_records_that_not_comparable_is_the_majority(self):
        """~80% of buildings have no apparent controller. If that context is
        lost, the value gets treated as an edge case."""
        assert "majority" in OwnershipVerdict.__doc__
