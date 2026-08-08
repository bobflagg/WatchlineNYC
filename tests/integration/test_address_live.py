"""``resolve_address`` against the live Geosupport sidecar + discovery graph.

Run with ``pytest -m integration``. Needs a populated ``.env`` **and** a running
Geosupport sidecar (see ``sidecar/README.md``); the module skips if the sidecar
is unreachable, since it is separately-launched infra a dev may not have up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.geocode import GeosupportClient, GeosupportUnavailable
from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools.address import resolve_address

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module", autouse=True)
def require_sidecar():
    """Skip this module unless the Geosupport sidecar is up and on 25b."""
    try:
        GeosupportClient().health()
    except GeosupportUnavailable as exc:
        pytest.skip(f"Geosupport sidecar unavailable: {exc}")


@pytest.fixture(scope="module")
def address_fixture() -> dict:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for query in fixtures["queries"]:
        if query["tool"] == "resolve_address":
            return query["params"]
    raise AssertionError("no resolve_address fixture query found")


def test_resolves_a_real_address_to_its_graph_building(address_fixture):
    out = resolve_address(address_fixture["address"], address_fixture["borough"])
    assert out["status"] == "resolved"
    assert out["bbl"] == address_fixture["bbl"]
    # The graph's own stored address is returned, not the typed input (D12).
    assert out["address"]
    assert out["reliability"]["type"] == ReliabilityType.TYPE_I.value


def test_no_tax_lot_is_distinct_from_not_found():
    # 456 West 24th Street parses but has no tax lot in 25b (spike §2).
    out = resolve_address("456 West 24 Street", "Manhattan")
    assert out["status"] == "no_tax_lot"


def test_ambiguous_street_returns_candidates():
    out = resolve_address("123 Broadwa", "Manhattan")
    assert out["status"] == "street_ambiguous"
    assert out["candidates"]  # a real capped list from NYC's street dictionary
    assert out["candidate_total"] >= len(out["candidates"])
