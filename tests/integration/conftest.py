"""Shared fixtures for tests that touch the live discovery graph, read-only.

Run with ``pytest -m integration``. Requires a populated ``.env``.

The session-scoped ``no_writes_occurred`` fixture implements validation check
2.4: it snapshots every node label and relationship type count before the
integration run and asserts they are unchanged afterwards. It is autouse, so
no individual test can opt out of being audited.
"""

from __future__ import annotations

import pytest
from neo4j import RoutingControl

from watchline.discovery.agent import db

pytestmark = pytest.mark.integration

NODE_LABELS = ("Building", "Actor", "Landlord", "Event", "Portfolio")
RELATIONSHIP_TYPES = (
    "HAS_EVENT",
    "REGISTERED_FOR",
    "PARTY_TO",
    "REFERENCES",
    "CONNECTED_BY_NAME",
    "CONNECTED_BY_ADDRESS",
    "MEMBER_OF",
    "IN_PORTFOLIO",
    "APPARENT_CONTROL",
)


def _snapshot() -> dict[str, int]:
    """Count every label and relationship type.

    Uses the count store (a bare label or type scan with `count`), so this is
    cheap even against ~42M Event nodes — do not add predicates here.
    """
    counts: dict[str, int] = {}
    for label in NODE_LABELS:
        result = db.read(f"MATCH (n:{label}) RETURN count(n) AS c")
        counts[f":{label}"] = result.single["c"]
    for rel in RELATIONSHIP_TYPES:
        result = db.read(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
        counts[f"[:{rel}]"] = result.single["c"]
    return counts


@pytest.fixture(scope="session", autouse=True)
def no_writes_occurred() -> None:
    """Validation 2.4 — assert the integration run mutated nothing.

    A pipeline run during the test session would also trip this. That is
    intentional: a spurious failure here is far cheaper than a real write
    going unnoticed, and the diff shows which element type moved.
    """
    before = _snapshot()
    yield
    after = _snapshot()
    drift = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not drift, (
        "Counts changed during the integration run — something wrote to the "
        f"discovery graph, or a pipeline ran concurrently: {drift}"
    )
    db.close()


@pytest.fixture(scope="session")
def raw_driver():
    """The driver with no guard in front of it.

    **Only** for proving the server refuses writes on its own (validation
    2.1b). Production code goes through :func:`db.read`; nothing else should
    use this.
    """
    return db._get_driver()


@pytest.fixture(scope="session")
def sample_bbl() -> str:
    """A real BBL that exists right now, resolved rather than hardcoded.

    Deliberately not a literal: the example-query addresses in the design docs
    turned out not to resolve at all, which is exactly the failure mode this
    avoids.
    """
    result = db.read("MATCH (b:Building) RETURN b.bbl AS bbl ORDER BY b.bbl LIMIT 1")
    return result.single["bbl"]


@pytest.fixture(scope="session")
def read_routing() -> RoutingControl:
    return RoutingControl.READ
