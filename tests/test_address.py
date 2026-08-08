"""Hermetic tests for ``resolve_address`` — no sidecar, no graph.

The Geosupport client and ``db.read`` are both faked, so every ``GeocodeOutcome``
branch, the Queens numeric-street retry, and the graph-confirmation /
geocoded-but-absent split are exercised without network or credentials. The live
sidecar + graph paths are the integration tier (Group 6).
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.geocode import Borough, GeocodeOutcome, GeocodeResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import address


# --- fakes ----------------------------------------------------------------


class FakeClient:
    """Maps ``(house_number, street_name)`` to a canned ``GeocodeResult``."""

    def __init__(self, responses: dict[tuple[str, str], GeocodeResult]):
        # Geosupport is case-insensitive; key on casefolded street so the tests
        # assert behaviour, not the exact case the tool happens to forward.
        self.responses = {(h, s.casefold()): v for (h, s), v in responses.items()}
        self.calls: list[tuple[str, str, str]] = []

    def resolve(self, house_number, street_name, borough) -> GeocodeResult:
        self.calls.append((house_number, street_name, str(borough)))
        return self.responses[(house_number, street_name.casefold())]


def _resolved(bbl="1000050010", street="BROAD STREET"):
    return GeocodeResult(outcome=GeocodeOutcome.RESOLVED, bbl=bbl, normalized_street=street)


@pytest.fixture
def patch(monkeypatch):
    """Install a fake client and a fake ``read``; return a helper to configure both."""

    def _install(responses, graph_rows=None):
        client = FakeClient(responses)
        monkeypatch.setattr(address, "_client", lambda: client)

        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            rows = graph_rows if graph_rows is not None else []
            return ReadResult(records=list(rows), truncated=False, row_cap=1)

        monkeypatch.setattr(address, "read", fake_read)
        return client, captured

    return _install


# --- outcome branches -----------------------------------------------------


def test_resolved_confirmed_returns_graph_address(patch):
    graph_row = {"bbl": "1000050010", "address": "115 BROAD STREET", "borough": "Manhattan"}
    patch({("115", "BROAD STREET"): _resolved()}, graph_rows=[graph_row])
    out = address.resolve_address("115 Broad Street", "Manhattan")
    assert out["status"] == "resolved"
    assert out["resolved"] is True
    assert out["bbl"] == "1000050010"
    # The graph's own stored address is what is cited, not the typed input.
    assert out["address"] == "115 BROAD STREET"


def test_resolved_but_absent_from_graph_is_its_own_status(patch):
    # Geosupport resolves a BBL, but no Building node exists for it (D12, spike §6).
    patch({("1", "NOWHERE STREET"): _resolved(bbl="1999990001")}, graph_rows=[])
    out = address.resolve_address("1 Nowhere Street", "Manhattan")
    assert out["status"] == "geocoded_but_absent"
    assert out["resolved"] is False
    assert out["bbl"] == "1999990001"


def test_no_tax_lot(patch):
    patch({("456", "WEST 24 STREET"): GeocodeResult(outcome=GeocodeOutcome.NO_TAX_LOT)})
    out = address.resolve_address("456 West 24 Street", "Manhattan")
    assert out["status"] == "no_tax_lot"
    assert out["resolved"] is False


def test_street_ambiguous_returns_capped_candidates(patch):
    result = GeocodeResult(
        outcome=GeocodeOutcome.STREET_AMBIGUOUS,
        candidates=("BROADWAY", "BROADWAY ALLEY", "BROADWAY ATRIUM"),
        candidate_total=10,
    )
    # The retry (whole string as street) also fails, so the first attempt's
    # candidate list is what surfaces.
    patch({
        ("123", "BROADWA"): result,
        ("", "123 BROADWA"): GeocodeResult(outcome=GeocodeOutcome.STREET_NOT_RECOGNIZED),
    })
    out = address.resolve_address("123 Broadwa", "Manhattan")
    assert out["status"] == "street_ambiguous"
    assert out["candidates"] == ["BROADWAY", "BROADWAY ALLEY", "BROADWAY ATRIUM"]
    assert out["candidate_total"] == 10
    assert out["candidates_truncated"] is True


def test_street_not_recognized(patch):
    patch({
        ("1", "ZZZ STREET"): GeocodeResult(outcome=GeocodeOutcome.STREET_NOT_RECOGNIZED),
        ("", "1 ZZZ STREET"): GeocodeResult(outcome=GeocodeOutcome.STREET_NOT_RECOGNIZED),
    })
    out = address.resolve_address("1 ZZZ Street", "Manhattan")
    assert out["status"] == "street_not_recognized"


def test_unavailable_is_not_not_found(patch):
    patch({("1", "BROAD STREET"): GeocodeResult(outcome=GeocodeOutcome.UNAVAILABLE)})
    out = address.resolve_address("1 Broad Street", "Manhattan")
    assert out["status"] == "geocoder_unavailable"
    assert out["resolved"] is False
    # The whole point: an outage must read differently from "no such address".
    assert "unavailable" in out["message"].lower()


def test_invalid_borough(patch):
    patch({})
    out = address.resolve_address("1 Broad Street", "Gotham")
    assert out["status"] == "invalid_borough"


def test_empty_address(patch):
    patch({})
    out = address.resolve_address("   ", "Manhattan")
    assert out["status"] == "invalid_input"


# --- Queens numeric-street retry (spike §5) -------------------------------


def test_numeric_street_retries_whole(patch):
    # Naive split of "39 Avenue" → house 39 / street "AVENUE", which Geosupport
    # rejects. The retry passes the whole string as the street and resolves.
    responses = {
        ("39", "AVENUE"): GeocodeResult(outcome=GeocodeOutcome.STREET_NOT_RECOGNIZED),
        ("", "39 AVENUE"): _resolved(bbl="4001230045", street="39 AVENUE"),
    }
    graph_row = {"bbl": "4001230045", "address": "39 AVENUE", "borough": "Queens"}
    client, _ = patch(responses, graph_rows=[graph_row])
    out = address.resolve_address("39 Avenue", "Queens")
    assert out["status"] == "resolved"
    assert out["bbl"] == "4001230045"
    # It really did retry: both the split form and the whole form were tried.
    tried = [(c[0], c[1].casefold()) for c in client.calls]
    assert ("39", "avenue") in tried
    assert ("", "39 avenue") in tried


def test_no_retry_when_first_attempt_resolves(patch):
    client, _ = patch(
        {("115", "BROAD STREET"): _resolved()},
        graph_rows=[{"bbl": "1000050010", "address": "115 BROAD STREET", "borough": "Manhattan"}],
    )
    address.resolve_address("115 Broad Street", "Manhattan")
    assert len(client.calls) == 1  # no wasteful second lookup


@pytest.mark.parametrize(
    "raw, house, street",
    [
        ("115 Broad Street", "115", "Broad Street"),
        ("232-05 87 Avenue", "232-05", "87 Avenue"),
        ("Broadway", "", "Broadway"),
        ("  30-17  82nd Street ", "30-17", "82nd Street"),
    ],
)
def test_split_address(raw, house, street):
    assert address._split_address(raw) == (house, street)


# --- reliability & safety -------------------------------------------------


def test_type_i_and_not_gated():
    declaration = address.resolve_address.reliability
    assert declaration.type is ReliabilityType.TYPE_I
    assert declaration.requires_tier_4 is False


def test_reliability_attached_to_payload(patch):
    patch({("456", "WEST 24 STREET"): GeocodeResult(outcome=GeocodeOutcome.NO_TAX_LOT)})
    out = address.resolve_address("456 West 24 Street", "Manhattan")
    assert out[RELIABILITY_KEY]["type"] == "I"


def test_confirm_cypher_passes_guard():
    # The one Cypher literal must be provably read-only.
    cypher_guard.assert_read_only(address._CONFIRM_CYPHER)


def test_bbl_is_bound_not_interpolated(patch):
    _, captured = patch(
        {("1", "BROAD STREET"): _resolved(bbl="1000050010")},
        graph_rows=[{"bbl": "1000050010", "address": "X", "borough": "Manhattan"}],
    )
    address.resolve_address("1 Broad Street", "Manhattan")
    assert captured["params"] == {"bbl": "1000050010"}
