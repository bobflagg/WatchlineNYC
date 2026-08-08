"""``resolve_landlord_name`` against the live discovery graph (fulltext).

Run with ``pytest -m integration``. Needs a populated ``.env``. No sidecar —
this tool is graph-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools.landlord import resolve_landlord_name

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _resolve_query(fixtures: dict) -> dict:
    for query in fixtures["queries"]:
        if query["tool"] == "resolve_landlord_name":
            return query["params"]
    raise AssertionError("no resolve_landlord_name fixture query found")


def test_resolves_or_disambiguates_a_real_name(fixtures):
    """A fixture landlord's name resolves to that landlord, or surfaces it among
    candidates when the name is shared."""
    params = _resolve_query(fixtures)
    out = resolve_landlord_name(params["name"])
    assert out["status"] in {"resolved", "needs_disambiguation"}
    if out["status"] == "resolved":
        assert out["landlord"]["actor_id"] == params["actor_id"]
    else:
        assert params["actor_id"] in {c["actor_id"] for c in out["candidates"]}


def test_shared_name_disambiguates_with_distinguishing_detail(fixtures):
    """The SANDRO CATALIC anchor: several distinct landlords, one name."""
    name = fixtures["anchors"]["landlord_connected_by_name"]["name"]
    out = resolve_landlord_name(name)
    assert out["status"] == "needs_disambiguation"
    assert len(out["candidates"]) >= 2
    for candidate in out["candidates"]:
        assert candidate["actor_id"]
        assert "business_address" in candidate
        assert "building_count" in candidate


def test_type_ii_landlord_caveat_travels(fixtures):
    name = fixtures["anchors"]["landlord_connected_by_name"]["name"]
    out = resolve_landlord_name(name)
    assert out["reliability"]["type"] == ReliabilityType.TYPE_II.value
    landlord_caveats = [c for c in out["reliability"]["caveats"] if c["element"] == "Landlord"]
    assert landlord_caveats and landlord_caveats[0]["text"]


def test_unknown_name_is_not_found():
    out = resolve_landlord_name("Zzqxwv Nobodyhere Unlikelyname")
    assert out["status"] in {"not_found", "needs_disambiguation"}
    # If anything came back it must not be a confident single resolution.
    assert out["status"] != "resolved"
