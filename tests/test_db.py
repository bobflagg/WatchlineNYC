"""Hermetic tests for the read-only access wrapper.

No Neo4j, no network. These cover the contract of :mod:`db` — that a caller
cannot ask it to write, cannot redirect it, and cannot be handed a truncated
result without being told. Anything requiring a real server lives in
``tests/integration/``.
"""

from __future__ import annotations

import inspect

import pytest

from watchline.discovery.agent import db
from watchline.discovery.agent.cypher_guard import CypherRefused


class TestNoWritePathExists:
    """The API must not offer a way to write, even by misuse."""

    def test_read_refuses_writes_before_touching_the_driver(self):
        """A write is refused by the guard, so no connection is even opened.

        This is why the test is hermetic: if `read` tried to connect first,
        this would fail without credentials.
        """
        with pytest.raises(CypherRefused):
            db.read("CREATE (n:Building {bbl: '1000010010'})")

    @pytest.mark.parametrize(
        "cypher",
        [
            "CREATE (n)",
            "MERGE (n:Building {bbl: '1'})",
            "MATCH (n:Building) SET n.address = 'x'",
            "MATCH (n) DETACH DELETE n",
            "MATCH (n:Building) REMOVE n.address",
            "CREATE INDEX foo FOR (b:Building) ON (b.address)",
            "DROP INDEX foo",
            "CALL apoc.create.node(['X'], {}) YIELD node RETURN node",
        ],
    )
    def test_write_shapes_all_refused(self, cypher):
        with pytest.raises(CypherRefused):
            db.read(cypher)

    def test_read_signature_exposes_no_access_mode_or_database(self):
        """No parameter may let a caller change access mode or target database.

        Enforced as a test rather than a convention so a future refactor that
        adds `database=` as a convenience fails loudly here.
        """
        params = set(inspect.signature(db.read).parameters)
        assert params == {"cypher", "parameters", "row_cap", "timeout"}

    def test_database_is_pinned(self):
        assert db.ReadResult(records=[], truncated=False, row_cap=1).database == "discovery"


class TestBounds:
    def test_row_cap_must_be_positive(self):
        with pytest.raises(ValueError, match="at least 1"):
            db.read("MATCH (n) RETURN n", row_cap=0)

    def test_defaults_are_bounded(self):
        """Neither bound may default to unlimited."""
        assert 0 < db.DEFAULT_ROW_CAP < 1_000_000
        assert 0 < db.DEFAULT_TIMEOUT_SECONDS <= 300


class TestReadResult:
    def test_len_counts_records(self):
        result = db.ReadResult(records=[{"a": 1}, {"a": 2}], truncated=False, row_cap=10)
        assert len(result) == 2

    def test_single_returns_none_when_empty(self):
        assert db.ReadResult(records=[], truncated=False, row_cap=10).single is None

    def test_single_returns_the_row(self):
        result = db.ReadResult(records=[{"bbl": "1000010010"}], truncated=False, row_cap=10)
        assert result.single == {"bbl": "1000010010"}

    def test_single_raises_on_multiple(self):
        """A key lookup returning two rows means an assumption is wrong.

        Silently taking the first row would hide that, so this raises.
        """
        result = db.ReadResult(records=[{"a": 1}, {"a": 2}], truncated=False, row_cap=10)
        with pytest.raises(ValueError, match="at most one row"):
            _ = result.single

    def test_truncation_is_visible(self):
        """Callers must be able to tell a capped result from a complete one."""
        result = db.ReadResult(records=[{"a": 1}], truncated=True, row_cap=1)
        assert result.truncated is True

    def test_is_immutable(self):
        result = db.ReadResult(records=[], truncated=False, row_cap=10)
        with pytest.raises(Exception):
            result.truncated = True  # type: ignore[misc]


class TestEnvParsing:
    @pytest.mark.parametrize("raw", ["", "   ", "not-a-number", None])
    def test_bad_int_falls_back_to_default(self, monkeypatch, raw):
        if raw is None:
            monkeypatch.delenv("WATCHLINE_TEST_INT", raising=False)
        else:
            monkeypatch.setenv("WATCHLINE_TEST_INT", raw)
        assert db._int_env("WATCHLINE_TEST_INT", 42) == 42

    def test_good_int_is_used(self, monkeypatch):
        monkeypatch.setenv("WATCHLINE_TEST_INT", "7")
        assert db._int_env("WATCHLINE_TEST_INT", 42) == 7

    @pytest.mark.parametrize("raw", ["", "abc"])
    def test_bad_float_falls_back(self, monkeypatch, raw):
        monkeypatch.setenv("WATCHLINE_TEST_FLOAT", raw)
        assert db._float_env("WATCHLINE_TEST_FLOAT", 1.5) == 1.5


class TestDriverLifecycle:
    def test_close_is_idempotent(self):
        """Safe to call on shutdown without knowing whether a driver was made."""
        db.close()
        db.close()
