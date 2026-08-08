"""Validation 7.2 — every fixture parameter still resolves against the graph.

Run with ``pytest -m integration``.

This is the check that would have caught ``456 West 24th Street, Manhattan``:
an example-query parameter nobody had confirmed resolves to anything. It
returns zero rows from the graph, and the Geosupport spike later showed NYC's
own geocoder has no tax lot for it either.

Fixtures are a snapshot of a graph that changes on someone else's schedule, so
a failure here usually means "regenerate", not "bug":

    uv run python scripts/generate_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent import db

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"
SCAN_TIMEOUT = 900.0


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _collect(fixtures: dict, key: str) -> dict[str, str]:
    """Map every occurrence of *key* to where it came from, for a clear failure."""
    found: dict[str, str] = {}
    for name, anchor in fixtures["anchors"].items():
        if anchor and isinstance(anchor.get(key), str):
            found.setdefault(anchor[key], f"anchor:{name}")
    for query in fixtures["queries"]:
        value = query["params"].get(key)
        if isinstance(value, str):
            found.setdefault(value, f"tier {query['tier']} #{query['n']}")
    return found


class TestKeysResolve:
    def test_every_bbl_exists(self, fixtures):
        bbls = _collect(fixtures, "bbl")
        assert bbls, "No BBLs in fixtures — test would be vacuous"
        result = db.read(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN b.bbl AS bbl",
            {"bbls": sorted(bbls)},
            row_cap=500,
            timeout=SCAN_TIMEOUT,
        )
        missing = set(bbls) - {row["bbl"] for row in result.records}
        assert not missing, {bbl: bbls[bbl] for bbl in sorted(missing)}

    def test_every_actor_id_exists(self, fixtures):
        actor_ids = {
            **_collect(fixtures, "actor_id"),
            **_collect(fixtures, "landlord_actor_id"),
            **_collect(fixtures, "registered_actor_id"),
            **_collect(fixtures, "connected_actor_id"),
        }
        assert actor_ids
        result = db.read(
            "UNWIND $ids AS id MATCH (a:Actor {actor_id: id}) RETURN a.actor_id AS id",
            {"ids": sorted(actor_ids)},
            row_cap=500,
            timeout=SCAN_TIMEOUT,
        )
        missing = set(actor_ids) - {row["id"] for row in result.records}
        assert not missing, {aid: actor_ids[aid] for aid in sorted(missing)}

    def test_every_portfolio_id_exists(self, fixtures):
        """Portfolios are regenerated per run, so a stale id resolves to
        nothing (decision D7). This is the tripwire for that."""
        ids = _collect(fixtures, "portfolio_id")
        assert ids
        result = db.read(
            "UNWIND $ids AS id MATCH (p:Portfolio {portfolio_id: id}) "
            "RETURN p.portfolio_id AS id",
            {"ids": sorted(ids)},
            row_cap=500,
            timeout=SCAN_TIMEOUT,
        )
        missing = set(ids) - {row["id"] for row in result.records}
        assert not missing, (
            f"Stale portfolio ids — has the pipeline regenerated? "
            f"{ {pid: ids[pid] for pid in sorted(missing)} }"
        )

    def test_every_event_id_exists(self, fixtures):
        event_ids = {
            **_collect(fixtures, "event_id"),
            **_collect(fixtures, "example_event_id"),
            **_collect(fixtures, "mortgage_event_id"),
            **_collect(fixtures, "referencing_event_id"),
        }
        assert event_ids
        result = db.read(
            "UNWIND $ids AS id MATCH (e:Event {event_id: id}) RETURN e.event_id AS id",
            {"ids": sorted(event_ids)},
            row_cap=500,
            timeout=SCAN_TIMEOUT,
        )
        missing = set(event_ids) - {row["id"] for row in result.records}
        assert not missing, {eid: event_ids[eid] for eid in sorted(missing)}


class TestEdgeCaseEntitiesStillQualify:
    """An edge-case fixture that no longer has its property is useless.

    Checking existence is not enough — the point of these rows is the property,
    and a pipeline fix could quietly remove it.
    """

    def test_building_without_apparent_control_still_has_none(self, fixtures):
        bbl = fixtures["edge_cases"]["building_without_apparent_control"]["entity"]["bbl"]
        result = db.read(
            "MATCH (b:Building {bbl: $bbl}) "
            "RETURN count { (:Landlord)-[:APPARENT_CONTROL]->(b) } AS controllers",
            {"bbl": bbl},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["controllers"] == 0

    def test_building_with_apparent_control_still_has_one(self, fixtures):
        anchor = fixtures["anchors"]["building_with_apparent_control"]
        result = db.read(
            "MATCH (l:Landlord)-[:APPARENT_CONTROL]->(b:Building {bbl: $bbl}) "
            "RETURN collect(l.actor_id) AS controllers",
            {"bbl": anchor["bbl"]},
            timeout=SCAN_TIMEOUT,
        )
        controllers = result.single["controllers"]
        assert anchor["landlord_actor_id"] in controllers

    def test_null_role_registration_still_null(self, fixtures):
        entity = fixtures["edge_cases"]["registered_for_null_role"]["entity"]
        result = db.read(
            "MATCH (a:Actor {actor_id: $actor_id})-[r:REGISTERED_FOR]->"
            "(b:Building {bbl: $bbl}) RETURN r.role AS role, r.registrationid AS rid",
            {"actor_id": entity["actor_id"], "bbl": entity["bbl"]},
            row_cap=50,
            timeout=SCAN_TIMEOUT,
        )
        assert any(row["role"] is None for row in result.records)

    def test_null_date_event_still_null(self, fixtures):
        entity = fixtures["edge_cases"]["event_null_date"]["entity"]
        result = db.read(
            "MATCH (e:Event {event_id: $id}) RETURN e.event_date AS event_date",
            {"id": entity["event_id"]},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["event_date"] is None

    def test_future_dated_event_still_future(self, fixtures):
        entity = fixtures["edge_cases"]["event_future_dated"]["entity"]
        result = db.read(
            "MATCH (e:Event {event_id: $id}) "
            "RETURN e.event_date > date() AS is_future, "
            "toString(e.event_date) AS event_date",
            {"id": entity["event_id"]},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["is_future"] is True

    def test_singleton_portfolio_still_singleton(self, fixtures):
        entity = fixtures["edge_cases"]["portfolio_singleton"]["entity"]
        result = db.read(
            "MATCH (p:Portfolio {portfolio_id: $id}) RETURN p.member_count AS members",
            {"id": entity["portfolio_id"]},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["members"] == 1

    def test_raw_actor_still_unresolved(self, fixtures):
        """Tier 3 #10's known gap: a raw ACRIS party with no Landlord label."""
        entity = fixtures["edge_cases"]["raw_actor_not_landlord"]["entity"]
        result = db.read(
            "MATCH (a:Actor {actor_id: $id}) RETURN a:Landlord AS is_landlord",
            {"id": entity["actor_id"]},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["is_landlord"] is False

    def test_ungeocodable_bizaddr_still_out_of_city(self, fixtures):
        entity = fixtures["edge_cases"]["landlord_ungeocodable_bizaddr"]["entity"]
        result = db.read(
            "MATCH (l:Landlord {actor_id: $id}) RETURN l.bizaddr AS bizaddr",
            {"id": entity["actor_id"]},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["bizaddr"] == entity["bizaddr"]


class TestRecordedFactsStillHold:
    def test_controller_cardinality_still_one_to_one(self, fixtures):
        """If this ever fails, tools that assumed one controller need review —
        and a multiple-controller fixture becomes buildable."""
        result = db.read(
            """MATCH (l:Landlord)-[:APPARENT_CONTROL]->(b:Building)
               WITH b, count(DISTINCT l) AS controllers
               RETURN max(controllers) AS max_controllers""",
            timeout=SCAN_TIMEOUT,
        )
        recorded = fixtures["anchors"]["controller_cardinality"][
            "max_controllers_per_building"
        ]
        assert result.single["max_controllers"] == recorded

    def test_node_counts_have_not_moved_wildly(self, fixtures):
        """A large drift means the fixtures are stale enough to regenerate."""
        recorded = fixtures["provenance"]["node_counts"]
        for label, expected in recorded.items():
            actual = db.read(
                f"MATCH (n:{label}) RETURN count(n) AS c", timeout=SCAN_TIMEOUT
            ).single["c"]
            drift = abs(actual - expected) / expected
            assert drift < 0.10, (
                f"{label} moved {drift:.1%} (recorded {expected:,}, now {actual:,}) "
                "— regenerate the fixtures"
            )
