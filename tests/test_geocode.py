"""Tests for Geosupport address resolution — validation 6.2, 6.3, 6.5.

Hermetic: no Docker, no sidecar, no network. HTTP is exercised through
``httpx.MockTransport``.

Fixture responses are **real Geosupport 25b output**, captured during the spike
(see ``specs/2026-07-30-phase-0-foundations/spike-findings.md``). That matters:
an invented fixture would have encoded my assumption that ``GRC '00'`` implies a
BBL, which the real data disproves.
"""

from __future__ import annotations

import httpx
import pytest

from watchline.discovery.agent.geocode import (
    MAX_CANDIDATES,
    REQUIRED_RELEASE,
    Borough,
    GeocodeOutcome,
    GeocodeResult,
    GeosupportClient,
    GeosupportReleaseMismatch,
    GeosupportUnavailable,
    compose_bbl,
    interpret,
)

# --------------------------------------------------------------------------
# Real captured responses (trimmed to the fields the client reads)
# --------------------------------------------------------------------------

RESOLVED_120_BROADWAY = {
    "Geosupport Return Code (GRC)": "00",
    "Reason Code": "",
    "Message": "",
    "First Street Name Normalized": "BROADWAY",
    "House Number - Display Format": "120",
    "BOROUGH BLOCK LOT (BBL)": {
        "BOROUGH BLOCK LOT (BBL)": "1000477501",
        "Borough Code": "1",
        "Tax Block": "00047",
        "Tax Lot": "7501",
    },
    "Condominium Billing BBL": "1000477501",
    "List of Street Names": [],
}

# GRC 00 with an EMPTY BBL — the finding that shaped the outcome model.
NO_TAX_LOT_456_W24 = {
    "Geosupport Return Code (GRC)": "00",
    "Reason Code": "",
    "Message": "",
    "First Street Name Normalized": "WEST   24 STREET",
    "House Number - Display Format": "456",
    "BOROUGH BLOCK LOT (BBL)": {
        "BOROUGH BLOCK LOT (BBL)": "",
        "Borough Code": "",
        "Tax Block": "",
        "Tax Lot": "",
    },
    "List of Street Names": [],
}

AMBIGUOUS_BROADWA = {
    "Geosupport Return Code (GRC)": "EE",
    "Reason Code": "A",
    "Message": "'BROADWA' NOT RECOGNIZED. THERE ARE 010 SIMILAR NAMES.",
    "List of Street Names": [
        "BROADWAY",
        "BROADWAY ALLEY",
        "BROADWAY ATRIUM",
        "BROADWAY BRIDGE",
        "BROADWAY MALLS",
        "BROADWAY TERRACE",
        "BROAD STREET",
        "BRONFMAN CENTER",
        "BRONX SCHOOL OF LAW AND FINANCE",
        "BRONX SHORE COMFORT STATION",
    ],
}

NOT_RECOGNIZED = {
    "Geosupport Return Code (GRC)": "EE",
    "Reason Code": "A",
    "Message": "'ZZZNOSUCHSTREETZZZ' NOT RECOGNIZED. THERE ARE NO SIMILAR NAMES",
    "List of Street Names": [],
}

NO_HOUSE_NUMBER = {
    "Geosupport Return Code (GRC)": "13",
    "Reason Code": "B",
    "Message": "INPUT CONTAINS NO ADDRESS NUMBER",
    "List of Street Names": [],
}

TOO_MANY_DIGITS = {
    "Geosupport Return Code (GRC)": "13",
    "Reason Code": "6",
    "Message": "ADDRESS NBR HAS TOO MANY DIGITS (MORE THAN 5).",
    "List of Street Names": [],
}


class TestComposeBbl:
    """Validation 6.2 — zero-padding is a classic off-by-one source."""

    @pytest.mark.parametrize(
        ("boro", "block", "lot", "expected"),
        [
            ("1", "00047", "7501", "1000477501"),  # already padded
            ("1", "47", "7501", "1000477501"),  # block needs padding
            ("2", "2565", "8", "2025650008"),  # both need padding
            ("3", "452", "1", "3004520001"),
            ("4", "391", "5", "4003910005"),
            ("5", "1", "1", "5000010001"),  # minimum
            ("1", "99999", "9999", "1999999999"),  # maximum
        ],
    )
    def test_composition(self, boro, block, lot, expected):
        result = compose_bbl(
            {"Borough Code": boro, "Tax Block": block, "Tax Lot": lot}
        )
        assert result == expected
        assert len(result) == 10

    @pytest.mark.parametrize("boro", list(Borough))
    def test_every_borough_digit_produces_ten_chars(self, boro):
        result = compose_bbl(
            {"Borough Code": boro.value, "Tax Block": "1", "Tax Lot": "1"}
        )
        assert len(result) == 10
        assert result.startswith(boro.value)

    def test_whitespace_is_stripped(self):
        assert (
            compose_bbl({"Borough Code": " 1 ", "Tax Block": " 47 ", "Tax Lot": " 7501 "})
            == "1000477501"
        )

    @pytest.mark.parametrize(
        "components",
        [
            {"BOROUGH BLOCK LOT (BBL)": "", "Borough Code": "", "Tax Block": "", "Tax Lot": ""},
            {"Borough Code": "1", "Tax Block": "", "Tax Lot": "7501"},
            {"Borough Code": "", "Tax Block": "47", "Tax Lot": "7501"},
            {"Borough Code": "1", "Tax Block": "47", "Tax Lot": ""},
            {},
            None,
            "",
            "   ",
        ],
    )
    def test_incomplete_yields_none(self, components):
        assert compose_bbl(components) is None

    def test_null_sentinel_is_not_a_bbl(self):
        """Geosupport writes '0000000000' when there is no condo billing lot.

        Treating it as real would produce lookups for a building that cannot
        exist. My initial spike hypothesis was that this field would rescue the
        mismatches; it is the sentinel in every case.
        """
        assert compose_bbl("0000000000") is None
        assert compose_bbl({"BOROUGH BLOCK LOT (BBL)": "0000000000"}) is None

    def test_flat_string_accepted(self):
        assert compose_bbl("1000477501") == "1000477501"

    def test_nested_flat_fallback(self):
        assert compose_bbl({"BOROUGH BLOCK LOT (BBL)": "1000477501"}) == "1000477501"


class TestInterpretGrc:
    """Validation 6.3 — each GRC class maps to its own structured outcome."""

    def test_success_with_bbl(self):
        result = interpret(RESOLVED_120_BROADWAY, borough=Borough.MANHATTAN)
        assert result.outcome is GeocodeOutcome.RESOLVED
        assert result.bbl == "1000477501"
        assert result.resolved is True
        assert result.normalized_street == "BROADWAY"

    def test_success_without_bbl_is_its_own_outcome(self):
        """The load-bearing case: GRC '00' does not guarantee a BBL.

        Checking only the return code would hand None to a key lookup and
        report "building not found" — a different, misleading answer.
        """
        result = interpret(NO_TAX_LOT_456_W24, borough=Borough.MANHATTAN)
        assert result.outcome is GeocodeOutcome.NO_TAX_LOT
        assert result.bbl is None
        assert result.resolved is False
        assert result.grc == "00"
        # The street did resolve, which is what makes this distinguishable.
        assert result.normalized_street == "WEST   24 STREET"

    def test_ambiguous_street_returns_candidates(self):
        result = interpret(AMBIGUOUS_BROADWA, borough=Borough.MANHATTAN)
        assert result.outcome is GeocodeOutcome.STREET_AMBIGUOUS
        assert result.needs_disambiguation is True
        assert result.candidates[0] == "BROADWAY"

    def test_candidates_are_capped_but_total_reported(self):
        """CLAUDE.md caps disambiguation at ~5; Geosupport offers up to 10.

        The true total travels with the capped list so a truncated set is never
        mistaken for the whole one.
        """
        result = interpret(AMBIGUOUS_BROADWA)
        assert len(result.candidates) == MAX_CANDIDATES
        assert result.candidate_total == 10
        assert result.candidates_truncated is True

    def test_not_recognized_without_candidates(self):
        result = interpret(NOT_RECOGNIZED)
        assert result.outcome is GeocodeOutcome.STREET_NOT_RECOGNIZED
        assert result.candidates == ()
        assert result.needs_disambiguation is False

    @pytest.mark.parametrize("response", [NO_HOUSE_NUMBER, TOO_MANY_DIGITS])
    def test_input_problems_are_invalid_input(self, response):
        assert interpret(response).outcome is GeocodeOutcome.INVALID_INPUT

    def test_reason_code_distinguishes_input_problems(self):
        """Same GRC, different reason — the message is what a user needs."""
        assert interpret(NO_HOUSE_NUMBER).reason_code == "B"
        assert interpret(TOO_MANY_DIGITS).reason_code == "6"
        assert "NO ADDRESS NUMBER" in interpret(NO_HOUSE_NUMBER).message

    @pytest.mark.parametrize("grc", ["", "01", "XX", "99", None])
    def test_unknown_grc_fails_closed(self, grc):
        response = {"Geosupport Return Code (GRC)": grc} if grc is not None else {}
        assert interpret(response).outcome is GeocodeOutcome.FAILED

    def test_all_outcomes_are_distinguishable(self):
        """None of the failure modes may collapse into another."""
        outcomes = {
            interpret(RESOLVED_120_BROADWAY).outcome,
            interpret(NO_TAX_LOT_456_W24).outcome,
            interpret(AMBIGUOUS_BROADWA).outcome,
            interpret(NOT_RECOGNIZED).outcome,
            interpret(NO_HOUSE_NUMBER).outcome,
            interpret({}).outcome,
        }
        assert len(outcomes) == 6


class TestBorough:
    def test_digits_match_bbl_prefix(self):
        assert [b.value for b in Borough] == ["1", "2", "3", "4", "5"]

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Manhattan", Borough.MANHATTAN),
            ("BRONX", Borough.BRONX),
            ("brooklyn", Borough.BROOKLYN),
            (" Queens ", Borough.QUEENS),
            ("Staten Island", Borough.STATEN_ISLAND),
        ],
    )
    def test_from_name(self, name, expected):
        assert Borough.from_name(name) is expected

    def test_unknown_borough_raises(self):
        with pytest.raises(ValueError, match="Unknown borough"):
            Borough.from_name("Jersey City")


def _client(handler) -> GeosupportClient:
    transport = httpx.MockTransport(handler)
    return GeosupportClient(
        base_url="http://sidecar:8080",
        client=httpx.Client(transport=transport),
    )


class TestHealthCheck:
    """Validation 6.5 / task 6.4 — release pinning, enforced not warned."""

    def test_matching_release_passes(self):
        client = _client(
            lambda request: httpx.Response(200, json={"release": REQUIRED_RELEASE})
        )
        assert client.health()["release"] == REQUIRED_RELEASE

    def test_mismatched_release_raises(self):
        """A silent mismatch surfaces as inexplicably missing buildings, so it
        must fail at startup instead."""
        client = _client(lambda request: httpx.Response(200, json={"release": "25c"}))
        with pytest.raises(GeosupportReleaseMismatch, match="25c"):
            client.health()

    def test_missing_release_raises(self):
        client = _client(lambda request: httpx.Response(200, json={"ok": True}))
        with pytest.raises(GeosupportUnavailable, match="did not report"):
            client.health()

    def test_unreachable_raises(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        with pytest.raises(GeosupportUnavailable):
            _client(handler).health()

    def test_error_status_raises(self):
        client = _client(lambda request: httpx.Response(503, text="unavailable"))
        with pytest.raises(GeosupportUnavailable):
            client.health()

    def test_required_release_matches_pipeline_pin(self):
        """The pipeline Dockerfile pins RELEASE=25b."""
        assert REQUIRED_RELEASE == "25b"


class TestResolveOverHttp:
    def test_resolved(self):
        def handler(request):
            assert request.url.path == "/resolve"
            return httpx.Response(200, json=RESOLVED_120_BROADWAY)

        result = _client(handler).resolve("120", "BROADWAY", Borough.MANHATTAN)
        assert result.bbl == "1000477501"
        assert result.borough is Borough.MANHATTAN

    def test_request_body_shape(self):
        seen = {}

        def handler(request):
            import json

            seen.update(json.loads(request.content))
            return httpx.Response(200, json=RESOLVED_120_BROADWAY)

        _client(handler).resolve(" 120 ", " BROADWAY ", "1")
        assert seen == {
            "house_number": "120",
            "street_name": "BROADWAY",
            "borough": "1",
        }

    def test_outage_is_not_reported_as_not_found(self):
        """An outage must be distinguishable from a genuine miss, or every
        query silently answers "no such address"."""

        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        result = _client(handler).resolve("120", "BROADWAY", Borough.MANHATTAN)
        assert result.outcome is GeocodeOutcome.UNAVAILABLE
        assert result.outcome is not GeocodeOutcome.STREET_NOT_RECOGNIZED
        assert result.resolved is False

    def test_timeout_is_unavailable(self):
        def handler(request):
            raise httpx.ReadTimeout("too slow", request=request)

        assert (
            _client(handler).resolve("120", "BROADWAY", "1").outcome
            is GeocodeOutcome.UNAVAILABLE
        )

    def test_no_retries_on_failure(self):
        """A retry loop would mask a persistent outage and slow every miss.

        Geocoding is deterministic, so a retry cannot fix anything a retry
        would fix.
        """
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ConnectError("refused", request=request)

        _client(handler).resolve("120", "BROADWAY", "1")
        assert len(calls) == 1

    def test_invalid_json_is_unavailable(self):
        client = _client(lambda request: httpx.Response(200, text="not json"))
        assert (
            client.resolve("120", "BROADWAY", "1").outcome is GeocodeOutcome.UNAVAILABLE
        )

    def test_non_object_json_is_unavailable(self):
        client = _client(lambda request: httpx.Response(200, json=["nope"]))
        assert (
            client.resolve("120", "BROADWAY", "1").outcome is GeocodeOutcome.UNAVAILABLE
        )

    def test_context_manager_closes_owned_client(self):
        with GeosupportClient(base_url="http://sidecar:8080") as client:
            assert client.client is not None

    def test_base_url_trailing_slash_normalized(self):
        client = GeosupportClient(base_url="http://sidecar:8080/")
        assert client.base_url == "http://sidecar:8080"


class TestResultInvariants:
    def test_result_is_immutable(self):
        result = interpret(RESOLVED_120_BROADWAY)
        with pytest.raises(Exception):
            result.bbl = "9999999999"  # type: ignore[misc]

    def test_resolved_requires_a_bbl(self):
        """`resolved` must never be True without a BBL to use."""
        result = GeocodeResult(outcome=GeocodeOutcome.RESOLVED, bbl=None)
        assert result.resolved is False

    @pytest.mark.parametrize(
        "outcome",
        [o for o in GeocodeOutcome if o is not GeocodeOutcome.RESOLVED],
    )
    def test_non_resolved_outcomes_are_not_resolved(self, outcome):
        assert GeocodeResult(outcome=outcome, bbl="1000477501").resolved is False
