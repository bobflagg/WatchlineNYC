"""Pre-execution refusal of any Cypher that could write or alter the graph.

This is layer 3 of the read-only guarantee (decision D4). The other two are a
read-only Neo4j role and ``READ_ACCESS`` on every session; each stands on its
own, and none of them is trusted to be the only one.

Why a code-side guard at all, when the role is read-only? Because from Phase 5
this receives **model-generated** Cypher. A server-side rejection surfaces as an
opaque runtime error mid-investigation; a guard refusal is structured, cheap,
and can be handed back to the deep agent as usable feedback. The role is the
guarantee; this is the good error message — and the redundancy is deliberate.

**Two failure modes, not one.** Letting a write through is the obvious one.
Refusing a legitimate read is equally a bug: it makes tools mysteriously fail
on valid data. The single-pass scanner below exists because the original
two-pass version refused ``WHERE n.url = 'http://x'`` — it stripped ``//`` as a
comment before it knew it was inside a string literal.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["CypherRefused", "assert_read_only", "is_read_only", "ALLOWED_PROCEDURES"]


class CypherRefused(Exception):
    """Raised when a query is refused before execution.

    Carries structured detail rather than only a message, so Phase 5 can tell
    the deep agent *what* was refused and *why* rather than just "no".

    :param category: Machine-readable slug, stable for programmatic handling.
    :param reason: Human-readable explanation, suitable to show a model.
    :param construct: The offending fragment.
    """

    def __init__(self, category: str, reason: str, construct: str, cypher: str) -> None:
        self.category = category
        self.reason = reason
        self.construct = construct
        self.cypher = cypher
        super().__init__(f"[{category}] {reason} (offending construct: {construct!r})")


# Clauses that mutate data or schema. Matched as whole words against Cypher
# that has already had comments and quoted spans removed, so a property value
# like 'DELETED 2019' cannot trigger a refusal.
#
# Multi-word entries are matched with flexible internal whitespace, so
# "IN   TRANSACTIONS" and "IN\nTRANSACTIONS" are caught too.
_WRITE_CLAUSES: tuple[str, ...] = (
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "DROP",
    "ALTER",
    "RENAME",
    "GRANT",
    "REVOKE",
    "DENY",
    "LOAD CSV",
    "PERIODIC COMMIT",
    "IN TRANSACTIONS",
    "TERMINATE",
    "FOREACH",
    "START DATABASE",
    "STOP DATABASE",
    "ENABLE SERVER",
    "DEALLOCATE",
    "REALLOCATE",
)

#: Procedures explicitly permitted. Everything else is refused, including
#: procedures that do not exist — an allowlist that fails closed is the point.
#:
#: Finalized against the queries this codebase actually issues (see
#: ``tests/test_cypher_guard.py::TestRealQueriesAreAllowed``). Adding an entry
#: is a deliberate code change, reviewed on the grounds that the procedure
#: cannot write.
ALLOWED_PROCEDURES: frozenset[str] = frozenset(
    {
        # Read-only schema introspection. Used by db.py's schema assertions and
        # by the vocabulary drift detector (group 5).
        "db.labels",
        "db.relationshiptypes",
        "db.propertykeys",
        "db.schema.visualization",
        "db.schema.nodetypeproperties",
        "db.schema.reltypeproperties",
        # Read-only index query procedures. Required by the name-resolution
        # tools in Phase 2 (fulltext over Landlord.name).
        "db.index.fulltext.querynodes",
        "db.index.fulltext.queryrelationships",
        "db.index.vector.querynodes",
        "db.index.vector.queryrelationships",
    }
)

_CALL_TARGET = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_USE_CLAUSE = re.compile(r"\bUSE\s+[A-Za-z_`$]", re.IGNORECASE)
_PROJECTION = re.compile(r"\bRETURN\b|\bYIELD\b")

_BLOCK_COMMENT_OPEN = "/*"
_LINE_COMMENT_OPEN = "//"
_QUOTES = frozenset({"'", '"', "`"})


def _strip_comments_and_literals(cypher: str) -> str:
    """Remove comments and quoted spans in a **single** left-to-right pass.

    Single pass is the whole point: whichever construct opens first wins, which
    is how Cypher itself reads. Two separate passes get ``'http://x'`` wrong,
    because the ``//`` looks like a comment to a pass that does not yet know it
    is inside a literal.

    Each removed span becomes a single space, so tokens either side cannot be
    joined into a new word.

    :raises CypherRefused: on an unterminated comment or literal. Malformed
        input is refused rather than guessed at (task 3.5).
    """
    out: list[str] = []
    i = 0
    n = len(cypher)

    while i < n:
        char = cypher[i]
        pair = cypher[i : i + 2]

        if pair == _BLOCK_COMMENT_OPEN:
            end = cypher.find("*/", i + 2)
            if end == -1:
                raise CypherRefused(
                    "unterminated",
                    "Unterminated block comment; refusing rather than guessing at intent",
                    construct=_BLOCK_COMMENT_OPEN,
                    cypher=cypher,
                )
            out.append(" ")
            i = end + 2
            continue

        if pair == _LINE_COMMENT_OPEN:
            end = cypher.find("\n", i + 2)
            out.append(" ")
            i = n if end == -1 else end + 1
            continue

        if char in _QUOTES:
            closed = False
            j = i + 1
            while j < n:
                # Backslash escapes apply to ' and " but not to backtick-quoted
                # identifiers, which escape a literal backtick by doubling it.
                if char != "`" and cypher[j] == "\\":
                    j += 2
                    continue
                if cypher[j] == char:
                    if char == "`" and cypher[j + 1 : j + 2] == "`":
                        j += 2
                        continue
                    closed = True
                    break
                j += 1
            if not closed:
                raise CypherRefused(
                    "unterminated",
                    f"Unterminated {char!r}-quoted span; refusing rather than guessing at intent",
                    construct=char,
                    cypher=cypher,
                )
            out.append(" ")
            i = j + 1
            continue

        out.append(char)
        i += 1

    return "".join(out)


def assert_read_only(
    cypher: str, *, allowed_procedures: frozenset[str] | None = None
) -> None:
    """Refuse *cypher* unless it is provably read-only.

    Returns ``None`` on success — a normal return is permission to execute.

    Fails closed: anything not recognizably a read is refused, including empty,
    malformed, or unparseable input.

    :raises CypherRefused: with a machine-readable ``category``.
    """
    allowed = ALLOWED_PROCEDURES if allowed_procedures is None else allowed_procedures

    if not isinstance(cypher, str) or not cypher.strip():
        raise CypherRefused(
            "empty",
            "Query is empty or not a string",
            construct=repr(cypher)[:60],
            cypher=cypher if isinstance(cypher, str) else repr(cypher),
        )

    # Normalize compatibility forms before matching, so fullwidth or otherwise
    # decorated keywords (ＣＲＥＡＴＥ) cannot slip past a plain ASCII compare.
    # Only the copy used for *analysis* is normalized; the caller still executes
    # the original. Normalizing can only make this stricter, never laxer.
    normalized = unicodedata.normalize("NFKC", cypher)

    stripped = _strip_comments_and_literals(normalized)

    statements = [part for part in stripped.split(";") if part.strip()]
    if len(statements) > 1:
        raise CypherRefused(
            "multi_statement",
            "Multiple statements are not permitted; a write can hide behind a read",
            construct=";",
            cypher=cypher,
        )
    if not statements:
        raise CypherRefused(
            "empty",
            "Query contains no executable statement once comments are removed",
            construct=cypher.strip()[:60],
            cypher=cypher,
        )

    statement = statements[0]
    upper = statement.upper()

    for clause in _WRITE_CLAUSES:
        pattern = r"\b" + clause.replace(" ", r"\s+") + r"\b"
        if re.search(pattern, upper):
            raise CypherRefused(
                "write_clause",
                f"Write or schema clause {clause!r} is not permitted on the discovery graph",
                construct=clause,
                cypher=cypher,
            )

    # Procedure invocation. `CALL {` and `CALL (n) {` subqueries do not match
    # this pattern and are fine — their contents were covered by the clause scan
    # above, which ran over the whole statement.
    for match in _CALL_TARGET.finditer(statement):
        target = match.group(1).lower()
        if target not in allowed:
            raise CypherRefused(
                "procedure_not_allowed",
                f"Procedure {match.group(1)!r} is not on the read-only allowlist",
                construct=match.group(1),
                cypher=cypher,
            )

    # USE can redirect a query at another database, including `system`.
    if _USE_CLAUSE.search(statement):
        raise CypherRefused(
            "use_clause",
            "USE is not permitted; the target database is pinned by db.py",
            construct="USE",
            cypher=cypher,
        )

    # A read must project something. No RETURN, no YIELD, and no permitted
    # procedure call is not a shape we recognize, so it is refused.
    if not _PROJECTION.search(upper) and not _CALL_TARGET.search(statement):
        raise CypherRefused(
            "no_projection",
            "Query has no RETURN or YIELD; only read queries are permitted",
            construct=cypher.strip()[:60],
            cypher=cypher,
        )


def is_read_only(cypher: str) -> bool:
    """Boolean form of :func:`assert_read_only`, for tests and diagnostics.

    Prefer the raising form in production code — the refusal detail is the
    useful part.
    """
    try:
        assert_read_only(cypher)
    except CypherRefused:
        return False
    return True
