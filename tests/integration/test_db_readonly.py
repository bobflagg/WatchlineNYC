"""Integration tests for read-only access against the live discovery graph.

Run with ``pytest -m integration``.

The centrepiece is :class:`TestServerRefusesWritesIndependently`, which
implements validation check 2.1b. It deliberately **bypasses**
:mod:`cypher_guard` and sends writes straight through the driver, because the
question it answers is not "does our code decline to write" — the hermetic
tests already prove that — but "would the server stop us if our code were
wrong". That is the only layer of D4 that survives a bug in this repo.
"""

from __future__ import annotations

import pytest
from neo4j import RoutingControl
from neo4j.exceptions import ClientError, Neo4jError

from watchline.discovery.agent import db
from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE

pytestmark = pytest.mark.integration


class TestServerRefusesWritesIndependently:
    """Validation 2.1b — D4 layer 1, tested without relying on layers 2 or 3."""

    @pytest.mark.parametrize(
        "write_cypher",
        [
            "CREATE (n:__WatchlineGuardProbe {probe: true}) RETURN n",
            "MERGE (n:__WatchlineGuardProbe {probe: true}) RETURN n",
            "MATCH (b:Building) WITH b LIMIT 1 SET b.__probe = 1 RETURN b.bbl",
            "CREATE INDEX __watchline_probe IF NOT EXISTS FOR (b:Building) ON (b.__probe)",
        ],
        ids=["create", "merge", "set", "index-ddl"],
    )
    def test_server_rejects_write(self, raw_driver, write_cypher):
        """The write must fail at the server, not in our code.

        If any of these succeed, the account in .env is not read-only and
        Phase 0 is not mergeable — regardless of how good cypher_guard is.
        """
        with pytest.raises(Neo4jError) as exc:
            raw_driver.execute_query(
                write_cypher,
                database_=NEO4J_DISCOVERY_DATABASE,
                routing_=RoutingControl.WRITE,
            )
        # Should be a permission/authorization refusal rather than, say, a
        # syntax error that only looks like success at protecting us.
        code = exc.value.code or ""
        assert "Forbidden" in code or "Security" in code or "Unauthorized" in code, (
            f"Write was rejected, but with {code!r} rather than a security error. "
            "Confirm the account is genuinely read-only rather than the query "
            "merely being invalid."
        )

    def test_reads_still_work_on_the_same_account(self, raw_driver):
        """A role scoped too tightly to read is also a failure.

        Guards against 'fixing' the write problem by removing read access.
        """
        records = raw_driver.execute_query(
            "MATCH (b:Building) RETURN count(b) AS c",
            database_=NEO4J_DISCOVERY_DATABASE,
            routing_=RoutingControl.READ,
        ).records
        assert records[0]["c"] > 0


class TestReadPath:
    def test_simple_read(self, sample_bbl):
        result = db.read(
            "MATCH (b:Building {bbl: $bbl}) RETURN b.bbl AS bbl, b.borough AS borough",
            {"bbl": sample_bbl},
        )
        assert result.single["bbl"] == sample_bbl

    def test_parameters_are_bound_not_interpolated(self, sample_bbl):
        """A parameter containing Cypher must be treated as data."""
        result = db.read(
            "MATCH (b:Building {bbl: $bbl}) RETURN count(b) AS c",
            {"bbl": "' OR true RETURN 1 //"},
        )
        assert result.single["c"] == 0

    def test_empty_result_is_not_an_error(self):
        result = db.read(
            "MATCH (b:Building {bbl: $bbl}) RETURN b.bbl AS bbl",
            {"bbl": "0000000000"},
        )
        assert result.records == []
        assert result.single is None


class TestBoundsAreEnforcedServerSide:
    def test_row_cap_truncates_and_flags(self):
        result = db.read("MATCH (b:Building) RETURN b.bbl AS bbl", row_cap=5)
        assert len(result) == 5
        assert result.truncated is True

    def test_exact_fit_is_not_flagged_as_truncated(self):
        """Off-by-one check: exactly row_cap rows is complete, not truncated."""
        result = db.read("MATCH (b:Building) RETURN b.bbl AS bbl LIMIT 5", row_cap=5)
        assert len(result) == 5
        assert result.truncated is False

    def test_under_cap_is_not_truncated(self):
        result = db.read("MATCH (b:Building) RETURN b.bbl AS bbl LIMIT 3", row_cap=10)
        assert len(result) == 3
        assert result.truncated is False

    def test_timeout_aborts_server_side(self):
        """A deliberately expensive scan must be killed, not merely abandoned.

        `raw_record` is free text on ~42M Event nodes with no index, so this
        cannot complete inside the timeout.
        """
        with pytest.raises(ClientError) as exc:
            db.read(
                "MATCH (e:Event) WHERE e.raw_record CONTAINS $needle RETURN count(e) AS c",
                {"needle": "zzz-no-such-token-zzz"},
                timeout=0.5,
            )
        assert "Timeout" in (exc.value.code or "") or "timeout" in str(exc.value).lower()


class TestNotificationsSurface:
    def test_unrecognized_label_is_reported(self):
        """An unknown label returns zero rows *and* a notification.

        Without surfacing this, a typo'd label is indistinguishable from a
        genuinely empty result — which is how a broken tool looks correct.
        """
        result = db.read("MATCH (n:__NoSuchLabelHere) RETURN count(n) AS c")
        assert result.single["c"] == 0
        statuses = [(n.gql_status, n.status_description) for n in result.notifications]
        assert any("01N50" in status for status, _ in statuses), (
            f"Expected an unknown-label notification (01N50), got {statuses}"
        )


class TestSchemaMatchesExpectations:
    """Guard against the graph moving under us between phases."""

    def test_labels_are_as_documented(self):
        result = db.read("CALL db.labels() YIELD label RETURN label ORDER BY label")
        labels = {r["label"] for r in result.records}
        assert {"Building", "Actor", "Landlord", "Event", "Portfolio"} <= labels
        assert "LandlordActor" not in labels, (
            "The :LandlordActor -> :Landlord rename appears to have regressed"
        )

    def test_relationship_types_are_as_documented(self):
        result = db.read(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN relationshipType ORDER BY relationshipType"
        )
        types = {r["relationshipType"] for r in result.records}
        assert types == {
            "HAS_EVENT",
            "REGISTERED_FOR",
            "PARTY_TO",
            "REFERENCES",
            "CONNECTED_BY_NAME",
            "CONNECTED_BY_ADDRESS",
            "MEMBER_OF",
            "IN_PORTFOLIO",
            "APPARENT_CONTROL",
        }
