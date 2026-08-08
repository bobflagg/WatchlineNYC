"""The only path from this module to the discovery graph. Read-only by design.

Implements layer 2 of decision D4 and consumes layer 1:

1. **A read-only Neo4j role** — the server refuses writes regardless of what
   this code does. The real guarantee (P0-4).
2. **This module** — every session is opened ``READ_ACCESS``, the database is
   pinned, and rows and time are bounded. Callers cannot override any of it.
3. **:mod:`.cypher_guard`** — refuses write clauses before they are sent.

Wraps :mod:`watchline.shared.connections` rather than replacing it (P0-2):
other modules depend on that driver setup, so it is left untouched.

Why bounds are mandatory rather than advisory: this graph holds ~42.3M
``Event`` and ~14.8M ``Actor`` nodes. An unbounded query is not a slow query,
it is a hung session. Measured during schema survey work: an unindexed address
scan took ~2.9s, and a ``DISTINCT source_name, event_type`` across all events
took ~20s.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from neo4j import (
    READ_ACCESS,
    Driver,
    GqlStatusObject,
    NotificationMinimumSeverity,
    Query,
    Record,
)

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE, neo4j_driver

from .cypher_guard import assert_read_only

logger = logging.getLogger(__name__)

__all__ = ["ReadResult", "close", "read", "DEFAULT_ROW_CAP", "DEFAULT_TIMEOUT_SECONDS"]


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using default %d", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using default %s", name, raw, default)
        return default


#: Maximum rows returned to a caller unless raised explicitly per call.
#: Large results should return a compact summary plus stable handles anyway
#: (see CLAUDE.md), so hitting this cap usually means the query is wrong.
DEFAULT_ROW_CAP: int = _int_env("WATCHLINE_ROW_CAP", 1_000)

#: Server-side transaction timeout, in seconds. Enforced by Neo4j via
#: ``neo4j.Query(timeout=...)``, so it kills the query server-side rather than
#: merely abandoning it client-side.
DEFAULT_TIMEOUT_SECONDS: float = _float_env("WATCHLINE_QUERY_TIMEOUT", 30.0)


@dataclass(frozen=True)
class ReadResult:
    """Outcome of a read, with the context a caller needs to trust it."""

    records: list[dict[str, Any]]
    #: True when the query produced more rows than ``row_cap``. Callers must
    #: not present a truncated result as complete — for an aggregation that is
    #: the difference between a right and a wrong answer.
    truncated: bool
    row_cap: int
    #: Server notifications (deprecation warnings, unrecognized labels, …), as
    #: GQL status objects — the non-deprecated form in neo4j 6.
    #: Surfaced rather than swallowed: an unknown-label warning is how a typo'd
    #: label gets noticed instead of silently returning zero rows.
    notifications: tuple[GqlStatusObject, ...] = field(default_factory=tuple)
    database: str = NEO4J_DISCOVERY_DATABASE

    def __len__(self) -> int:
        return len(self.records)

    @property
    def single(self) -> dict[str, Any] | None:
        """The one row, or ``None`` if there were none.

        Raises if there was more than one — a lookup by key returning two rows
        means an assumption is wrong, and silently taking the first would hide
        it.
        """
        if not self.records:
            return None
        if len(self.records) > 1:
            raise ValueError(
                f"Expected at most one row, got {len(self.records)}; "
                "use .records if multiple rows are legitimate"
            )
        return self.records[0]


_driver_lock = threading.Lock()
_driver: Driver | None = None


def _get_driver() -> Driver:
    """Return the process-wide driver, creating it on first use.

    One driver, reused for the process lifetime — the driver owns a connection
    pool, so constructing one per query would defeat pooling entirely. Private
    by convention: tools go through :func:`read`. Integration tests import it
    directly to prove the *server* refuses writes independently of
    :mod:`.cypher_guard` (validation 2.1b).
    """
    global _driver
    with _driver_lock:
        if _driver is None:
            _driver = neo4j_driver()
        return _driver


def close() -> None:
    """Close the shared driver. Call on application shutdown; idempotent."""
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None


def read(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    *,
    row_cap: int | None = None,
    timeout: float | None = None,
) -> ReadResult:
    """Execute a read against the discovery graph.

    There is deliberately no parameter for access mode or database. A caller
    cannot ask this function to write, and cannot point it at another database;
    that is the whole point of routing every tool through here.

    :param cypher: A read query. Refused by :mod:`.cypher_guard` if it could
        write, targets a non-allowlisted procedure, or contains multiple
        statements.
    :param parameters: Query parameters. **Always** pass values here rather
        than formatting them into *cypher* — string interpolation is both an
        injection risk and a query-plan-cache miss.
    :param row_cap: Override the default row cap for this call.
    :param timeout: Override the default server-side timeout for this call.
    :raises CypherRefused: if the query is not provably read-only.
    """
    assert_read_only(cypher)

    cap = DEFAULT_ROW_CAP if row_cap is None else row_cap
    if cap < 1:
        raise ValueError(f"row_cap must be at least 1, got {cap}")
    limit = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    # Query carries the transaction timeout so Neo4j enforces it server-side.
    query = Query(cypher, timeout=limit)  # type: ignore[arg-type]

    with _get_driver().session(
        database=NEO4J_DISCOVERY_DATABASE,
        default_access_mode=READ_ACCESS,
        # Surface everything the server wants to tell us; we decide what to log.
        notifications_min_severity=NotificationMinimumSeverity.INFORMATION,
    ) as session:
        result = session.run(query, parameters or {})
        # Fetch one more than the cap so truncation is detectable rather than
        # guessed at. Streaming, so a 42M-row query does not land in memory.
        fetched: list[Record] = result.fetch(cap + 1)
        truncated = len(fetched) > cap
        records = [dict(record) for record in fetched[:cap]]
        summary = result.consume()

    # Only status objects that are actual notifications; the result also carries
    # routine outcome statuses like "00000" (success) and "02000" (no data).
    notifications = tuple(
        status for status in (summary.gql_status_objects or ()) if status.is_notification
    )
    _log_notifications(notifications, cypher)

    if truncated:
        logger.warning(
            "Query returned more than row_cap=%d rows; result is truncated. Cypher: %s",
            cap,
            _abbreviate(cypher),
        )

    return ReadResult(
        records=records,
        truncated=truncated,
        row_cap=cap,
        notifications=notifications,
        database=NEO4J_DISCOVERY_DATABASE,
    )


def _log_notifications(notifications: tuple[GqlStatusObject, ...], cypher: str) -> None:
    """Log server notifications at a severity matching their own."""
    for note in notifications:
        severity = str(note.raw_severity or "").upper()
        message = (
            f"Neo4j notification [{note.gql_status}] {note.status_description} "
            f"| {_abbreviate(cypher)}"
        )
        if "WARN" in severity:
            logger.warning(message)
        else:
            logger.info(message)


def _abbreviate(cypher: str, limit: int = 200) -> str:
    collapsed = " ".join(cypher.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
