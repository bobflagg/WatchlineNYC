"""Adversarial suite for the Cypher guard — validation checks 3.1 through 3.4.

Hermetic: no Neo4j, no network.

This guard has **two** failure modes and both are tested here:

1. Letting a write through — the obvious one.
2. Refusing a legitimate read — equally a bug, because it makes tools fail
   mysteriously on valid data. :class:`TestLegitimateReadsAreAllowed` and
   :class:`TestRealQueriesAreAllowed` exist for this, and one of them
   (``'http://x'``) caught a real over-refusal in the baseline guard.

From Phase 5 this receives model-generated Cypher, so "an attacker" here is
not hypothetical — it is a language model that has read attacker-controlled
free text out of ``Event.raw_record``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from watchline.discovery.agent.cypher_guard import (
    ALLOWED_PROCEDURES,
    CypherRefused,
    assert_read_only,
    is_read_only,
)


def refusal(cypher: str) -> CypherRefused:
    """Assert *cypher* is refused and return the exception for inspection."""
    with pytest.raises(CypherRefused) as exc:
        assert_read_only(cypher)
    return exc.value


class TestBareWrites:
    @pytest.mark.parametrize(
        "cypher",
        [
            "CREATE (n)",
            "CREATE (n:Building {bbl: '1000010010'})",
            "MERGE (n:Building {bbl: '1'})",
            "MATCH (n) SET n.x = 1",
            "MATCH (n) SET n:Landlord",
            "MATCH (n) REMOVE n.x",
            "MATCH (n) REMOVE n:Landlord",
            "MATCH (n) DELETE n",
            "MATCH (n) DETACH DELETE n",
            "MATCH (a)-[r]->(b) DELETE r",
            "MATCH (n) WITH n LIMIT 1 SET n.probe = true RETURN n",
        ],
    )
    def test_refused(self, cypher):
        assert refusal(cypher).category == "write_clause"


class TestCasingAndWhitespace:
    @pytest.mark.parametrize(
        "cypher",
        [
            "cReAtE (n)",
            "create (n)",
            "CrEaTe (n)",
            "MATCH(n)\n\tSET n.x=1",
            "MATCH (n)\r\n  set  n.x = 1",
            "MATCH (n) DETACH\n\nDELETE n",
            "CALL {  MATCH (n) CREATE (m) RETURN m }",
            "MATCH (n) CALL   {  CREATE (x) } RETURN n",
        ],
    )
    def test_refused(self, cypher):
        assert not is_read_only(cypher)

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) RETURN n IN TRANSACTIONS",
            "MATCH (n) RETURN n IN\nTRANSACTIONS",
            "MATCH (n) RETURN n IN    TRANSACTIONS",
        ],
    )
    def test_multiword_clauses_tolerate_internal_whitespace(self, cypher):
        """Multi-word clauses must not be evadable by reformatting."""
        assert not is_read_only(cypher)


class TestComments:
    @pytest.mark.parametrize(
        "cypher",
        [
            "// harmless\nCREATE (n)",
            "/* harmless */ CREATE (n)",
            "MATCH (n) RETURN n // then\nCREATE (x)",
            "MATCH (n) RETURN 1 /* gap */ CREATE (x)",
            "/* a /* b */ CREATE (x)",
            "CREATE // comment after the write\n (n)",
        ],
    )
    def test_comments_cannot_hide_a_write(self, cypher):
        assert not is_read_only(cypher)

    @pytest.mark.parametrize(
        "cypher",
        [
            "/* unterminated CREATE (n)",
            "MATCH (n) RETURN n /* trailing",
        ],
    )
    def test_unterminated_block_comment_refused(self, cypher):
        """Fail closed (task 3.5) — do not guess at malformed input."""
        assert refusal(cypher).category == "unterminated"


class TestStringLiterals:
    """A literal must neither trigger nor conceal a refusal."""

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (b:Building) WHERE b.address = 'CREATE ME' RETURN b.bbl",
            "MATCH (b:Building) WHERE b.address = 'DELETED 2019' RETURN b.bbl",
            'MATCH (b:Building) WHERE b.address = "SET BACK FROM ROAD" RETURN b.bbl',
            "MATCH (e:Event) WHERE e.raw_record CONTAINS 'DETACH DELETE' RETURN e.event_id",
            "MATCH (n) WHERE n.x = 'a\\'b CREATE (m)' RETURN n",
            "MATCH (n) WHERE n.`CREATE` = 1 RETURN n",
            "MATCH (n) WHERE n.x = '// not a comment' RETURN n",
            "MATCH (n) WHERE n.x = '/* not a comment */' RETURN n",
        ],
    )
    def test_keywords_inside_literals_are_allowed(self, cypher):
        """Over-refusal is a failure too — these are legitimate reads."""
        assert is_read_only(cypher), f"Legitimate read was refused: {cypher}"

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) WHERE n.url = 'http://x' RETURN n",
            "MATCH (n) WHERE n.url = 'https://example.com/a/b' RETURN n",
            "MATCH (e:Event) WHERE e.raw_record CONTAINS 'https://a//b' RETURN e.event_id",
            "MATCH (b:Building) WHERE b.rs_pdfsoa_2023 STARTS WITH 'https://' RETURN b.bbl",
        ],
    )
    def test_urls_in_literals_are_allowed(self, cypher):
        """Regression: the two-pass guard stripped ``//`` in a URL as a comment.

        That ate the rest of the line — including the RETURN — and the query was
        refused as unprojected. ``Event.raw_record`` embeds source JSON and
        ``Building.rs_pdfsoa_2023`` holds a URL, so this was reachable with real
        data, not a contrived case. Fixed by scanning comments and literals in a
        single left-to-right pass.
        """
        assert is_read_only(cypher), f"Legitimate read with a URL was refused: {cypher}"

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) WHERE n.x = '/*' CREATE (m) RETURN n",
            "MATCH (n) WHERE n.x = \"//\" CREATE (m) RETURN n",
        ],
    )
    def test_literals_cannot_conceal_a_write(self, cypher):
        """A literal that merely *looks* like a comment opener changes nothing."""
        assert not is_read_only(cypher)

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) WHERE n.x = 'oops RETURN n",
            'MATCH (n) WHERE n.x = "oops RETURN n',
            "MATCH (n) WHERE n.`oops = 1 RETURN n",
        ],
    )
    def test_unterminated_literal_refused(self, cypher):
        assert refusal(cypher).category == "unterminated"


class TestMultiStatement:
    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) RETURN n; CREATE (x)",
            "MATCH (n) RETURN n ; DROP INDEX foo",
            "CALL db.labels() YIELD label RETURN label; CREATE (x)",
        ],
    )
    def test_refused(self, cypher):
        assert refusal(cypher).category == "multi_statement"

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) RETURN n;",
            "MATCH (n) RETURN n ;  ",
            "MATCH (n) WHERE n.x = 'a;b' RETURN n",
        ],
    )
    def test_trailing_semicolon_and_semicolon_in_literal_are_fine(self, cypher):
        """A single statement is still a single statement."""
        assert is_read_only(cypher)


class TestProcedureAllowlist:
    @pytest.mark.parametrize(
        "cypher",
        [
            "CALL apoc.create.node(['X'], {}) YIELD node RETURN node",
            "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'RETURN 1', {}) YIELD batches RETURN batches",
            "CALL apoc.util.sleep(1000)",
            "CALL dbms.components() YIELD name RETURN name",
            "CALL dbms.security.createUser('x', 'y')",
            "CALL db.awaitIndexes()",
            "CALL db.createLabel('X')",
            "CALL tx.getMetaData()",
            "CALL some.procedure.that.does.not.exist() YIELD x RETURN x",
        ],
    )
    def test_non_allowlisted_procedures_refused(self, cypher):
        """Validation 3.2 — the allowlist is closed, including for
        procedures that do not exist."""
        assert not is_read_only(cypher)

    @pytest.mark.parametrize("procedure", sorted(ALLOWED_PROCEDURES))
    def test_every_allowlisted_procedure_passes(self, procedure):
        """Nothing on the allowlist may be blocked by another rule.

        Catches the case where a procedure is added to the allowlist but its
        name happens to contain a denylisted substring.
        """
        assert is_read_only(f"CALL {procedure}() YIELD x RETURN x")

    def test_allowlist_case_insensitive(self):
        assert is_read_only("CALL DB.LABELS() YIELD label RETURN label")
        assert is_read_only("call Db.Labels() yield label return label")

    def test_allowlist_is_injectable_for_tests(self):
        """The allowlist can be narrowed, but narrowing must actually apply."""
        with pytest.raises(CypherRefused):
            assert_read_only(
                "CALL db.labels() YIELD label RETURN label",
                allowed_procedures=frozenset(),
            )

    def test_call_subquery_is_not_a_procedure(self):
        """`CALL {` and `CALL (n) {` are subqueries, not procedure calls."""
        assert is_read_only("CALL { MATCH (n) RETURN n LIMIT 1 } RETURN n")
        assert is_read_only(
            "MATCH (b:Building) CALL (b) { MATCH (b)-[:HAS_EVENT]->(e) RETURN e LIMIT 1 } RETURN e"
        )

    def test_no_allowlisted_procedure_can_write(self):
        """Guards the allowlist against a careless future addition."""
        forbidden_fragments = ("create", "delete", "merge", "set", "drop", "remove")
        for procedure in ALLOWED_PROCEDURES:
            assert not any(frag in procedure for frag in forbidden_fragments), (
                f"{procedure!r} looks like it may write; justify or remove it"
            )


class TestSchemaAndAdmin:
    @pytest.mark.parametrize(
        "cypher",
        [
            "CREATE INDEX foo FOR (b:Building) ON (b.address)",
            "CREATE TEXT INDEX foo IF NOT EXISTS FOR (b:Building) ON (b.address)",
            "CREATE FULLTEXT INDEX foo FOR (n:Landlord) ON EACH [n.name]",
            "DROP INDEX foo",
            "DROP CONSTRAINT foo",
            "CREATE CONSTRAINT foo FOR (b:Building) REQUIRE b.bbl IS UNIQUE",
            "ALTER CURRENT GRAPH TYPE SET {}",
            "ALTER USER watchline SET PASSWORD 'x'",
            "CREATE USER bob SET PASSWORD 'x'",
            "GRANT ROLE reader TO bob",
            "REVOKE ROLE reader FROM bob",
            "DENY WRITE ON GRAPH discovery TO reader",
            "TERMINATE TRANSACTIONS 'x'",
            "START DATABASE discovery",
            "STOP DATABASE discovery",
        ],
    )
    def test_refused(self, cypher):
        assert not is_read_only(cypher)

    @pytest.mark.parametrize(
        "cypher",
        [
            "USE system SHOW DATABASES",
            "USE neo4j MATCH (n) RETURN n",
            "USE `system` MATCH (n) RETURN n",
        ],
    )
    def test_use_refused(self, cypher):
        """The database is pinned by db.py; redirection is not negotiable."""
        assert not is_read_only(cypher)


class TestBulkLoadAndTransactionClauses:
    @pytest.mark.parametrize(
        "cypher",
        [
            "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
            "LOAD CSV WITH HEADERS FROM 'http://x/y.csv' AS row RETURN row",
            "USING PERIODIC COMMIT 500 LOAD CSV FROM 'x' AS r RETURN r",
            "MATCH (n) CALL { WITH n RETURN n } IN TRANSACTIONS",
            "MATCH (n) FOREACH (x IN [1] | SET n.y = x)",
        ],
    )
    def test_refused(self, cypher):
        assert not is_read_only(cypher)


class TestUnicodeEvasion:
    @pytest.mark.parametrize(
        "cypher",
        [
            "ＣＲＥＡＴＥ (n) RETURN n",  # fullwidth
            "ＭＥＲＧＥ (n) RETURN n",
            "MATCH (n) ＳＥＴ n.x = 1 RETURN n",
        ],
    )
    def test_compatibility_forms_are_normalized_then_refused(self, cypher):
        """NFKC normalization before matching (task 3.4).

        Whether Neo4j would execute these is beside the point — normalizing can
        only make the guard stricter, and relying on the server to reject them
        would make this layer depend on the layer below it.
        """
        assert not is_read_only(cypher)


class TestFailsClosed:
    @pytest.mark.parametrize(
        "cypher",
        [
            "",
            "   ",
            "\n\t ",
            "// only a comment",
            "/* only a comment */",
            "MATCH (n)",  # no projection
            "MATCH (n) WHERE n.x = 1",
            "WITH 1 AS x",
            "not cypher at all",
        ],
    )
    def test_unprojected_or_empty_refused(self, cypher):
        assert not is_read_only(cypher)

    @pytest.mark.parametrize("value", [None, 123, [], {}, object()])
    def test_non_string_refused(self, value):
        with pytest.raises(CypherRefused):
            assert_read_only(value)  # type: ignore[arg-type]


class TestRefusalsAreStructured:
    """Validation 3.3 — Phase 5 hands these back to the deep agent."""

    def test_carries_category_reason_and_construct(self):
        exc = refusal("MATCH (n) SET n.x = 1")
        assert exc.category == "write_clause"
        assert "SET" in exc.construct
        assert exc.reason
        assert exc.cypher == "MATCH (n) SET n.x = 1"

    def test_message_is_actionable(self):
        exc = refusal("CALL apoc.create.node([], {}) YIELD node RETURN node")
        assert "allowlist" in str(exc).lower() or "not permitted" in str(exc).lower()

    @pytest.mark.parametrize(
        ("cypher", "expected"),
        [
            ("", "empty"),
            ("MATCH (n) RETURN n; CREATE (x)", "multi_statement"),
            ("CREATE (n)", "write_clause"),
            ("CALL dbms.components() YIELD name RETURN name", "procedure_not_allowed"),
            ("USE system MATCH (n) RETURN n", "use_clause"),
            ("MATCH (n)", "no_projection"),
            ("MATCH (n) WHERE n.x = 'oops RETURN n", "unterminated"),
        ],
    )
    def test_categories_are_distinct_and_stable(self, cypher, expected):
        assert refusal(cypher).category == expected


class TestLegitimateReadsAreAllowed:
    """Over-refusal check. Every one of these is a valid read."""

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (b:Building {bbl: $bbl}) RETURN b.bbl AS bbl",
            "MATCH (b:Building)-[:HAS_EVENT]->(e:Event) RETURN e.event_id LIMIT 10",
            "MATCH (l:Landlord)-[ac:APPARENT_CONTROL]->(b:Building) RETURN l.name, ac.method",
            "MATCH (n:Event) WHERE n.event_date > date('2025-01-01') RETURN count(n) AS c",
            "MATCH (b:Building) RETURN DISTINCT b.borough AS boro, count(*) AS c ORDER BY c DESC",
            "CALL db.labels() YIELD label RETURN label ORDER BY label",
            "MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 5",
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN b.bbl",
            "MATCH (b:Building) WITH b LIMIT 10 RETURN collect(b.bbl) AS bbls",
            "PROFILE MATCH (b:Building {bbl: $bbl}) RETURN b.bbl",
            "EXPLAIN MATCH (b:Building {bbl: $bbl}) RETURN b.bbl",
            "SHOW INDEXES YIELD name, type RETURN name, type",
            # words that merely *contain* denylisted clauses
            "MATCH (n) WHERE n.name = $created RETURN n",
            "MATCH (n) RETURN n.dataset AS dataset",
            "MATCH (n) RETURN n.offset AS offset",
            "MATCH (n) RETURN n.subset AS subset",
            "MATCH (n) RETURN n.remover AS remover",
            "MATCH (n) RETURN n.mergers AS mergers",
        ],
    )
    def test_allowed(self, cypher):
        assert is_read_only(cypher), f"Legitimate read was refused: {cypher}"


class TestRealQueriesAreAllowed:
    """Validation 3.4 — the guard must not block the actual workload.

    These are the queries this repository genuinely issues (db.py's schema
    assertions, the integration count snapshot, the survey queries that
    produced specs/roadmap.md section 2). If the guard refuses one of these, the
    allowlist or a clause pattern is wrong.
    """

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n:Building) RETURN count(n) AS c",
            "MATCH ()-[r:HAS_EVENT]->() RETURN count(r) AS c",
            "MATCH ()-[r:APPARENT_CONTROL]->() RETURN count(r) AS c",
            "CALL db.labels() YIELD label RETURN label",
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
            "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties "
            "RETURN name, type, entityType, labelsOrTypes, properties",
            "MATCH (b:Building) WHERE b.address IS NOT NULL "
            "RETURN b.address AS a, b.borough AS boro, b.bbl AS bbl LIMIT 6",
            "MATCH (e:Event) WHERE e.event_type IS NOT NULL "
            "RETURN DISTINCT e.source_name AS s, e.event_type AS t ORDER BY s, t",
            "MATCH (e:Event) WHERE e.event_type = 'Violation' "
            "RETURN DISTINCT e.source_name AS s, e.violation_class AS vc ORDER BY s, vc LIMIT 30",
            "MATCH (p:Portfolio) RETURN p.method AS m, p.run_id AS rid, count(*) AS c "
            "ORDER BY c DESC LIMIT 5",
            "MATCH (l:Landlord)-[ac:APPARENT_CONTROL]->(b:Building) "
            "WHERE b.dof_ownername IS NOT NULL "
            "RETURN b.bbl AS bbl, b.dof_ownername AS recorded_owner, "
            "l.name AS apparent_controller, ac.method AS method LIMIT 5",
            "MATCH (n:Landlord) WHERE n.bizaddr IS NOT NULL RETURN n.bizaddr AS a SKIP 500 LIMIT 15",
            "MATCH (b:Building) RETURN DISTINCT size(b.bbl) AS len, count(*) AS c ORDER BY len",
            "MATCH (b:Building) WHERE b.borough = 'Manhattan' AND b.address STARTS WITH '456 WEST 24' "
            "RETURN b.bbl AS bbl, b.address AS a, b.dof_ownername AS dof LIMIT 5",
            "MATCH (e:Event) WHERE e.raw_record CONTAINS $needle RETURN count(e) AS c",
        ],
    )
    def test_allowed(self, cypher):
        assert is_read_only(cypher), f"Real workload query was refused: {cypher}"


class TestEveryCypherLiteralInTheRepoIsAllowed:
    """Validation 3.4, completed — the guard must not block the real workload.

    Rather than maintaining a hand-copied list, this walks the AST of every
    module and checks every plain string literal that looks like a complete
    Cypher statement. Over-refusal is the failure mode this catches, and it
    catches it in code nobody thought to add to a list.

    Two things are excluded, both deliberately. Files listed in
    :data:`INTENTIONAL_REFUSALS` exist to prove writes *are* refused, so their
    Cypher is supposed to fail. And f-string parts are skipped, since a
    fragment is not a statement.

    The literal must also *start* with a Cypher keyword. Searching for "MATCH"
    anywhere matched prose — ``geocode.py``'s docstring says "must match the
    release" and "returns", which is not a query.
    """

    #: Modules whose Cypher is intentionally non-read.
    INTENTIONAL_REFUSALS = frozenset(
        {
            "test_cypher_guard.py",  # the adversarial suite itself
            "test_db.py",  # asserts db.read refuses write shapes
            "test_db_readonly.py",  # probes the server's own refusal
            "test_investigator.py",  # feeds run_cypher deliberate write shapes
            "operators.py",  # analytics/operators.py: GDS runs via its own write session, not the agent path
        }
    )

    _OPENERS = (
        "MATCH ",
        "OPTIONAL MATCH ",
        "CALL ",
        "UNWIND ",
        "SHOW ",
        "PROFILE ",
        "EXPLAIN ",
        "WITH ",
    )

    @classmethod
    def _cypher_literals(cls) -> list[tuple[str, str]]:
        import ast

        repo_root = Path(__file__).resolve().parent.parent
        found: list[tuple[str, str]] = []
        for path in sorted(
            [
                *(repo_root / "watchline").rglob("*.py"),
                *(repo_root / "scripts").rglob("*.py"),
                *(repo_root / "tests").rglob("*.py"),
            ]
        ):
            if path.name in cls.INTENTIONAL_REFUSALS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # Only standalone constants. Parts of an f-string are fragments.
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                text = node.value
                upper = " ".join(text.split()).upper()
                if upper.startswith(cls._OPENERS) and (
                    "RETURN" in upper or "YIELD" in upper
                ):
                    found.append((str(path.relative_to(repo_root)), text))
        return found

    def test_found_a_meaningful_number(self):
        """Guard against the walker silently finding nothing."""
        literals = self._cypher_literals()
        assert len(literals) >= 20, (
            f"Only found {len(literals)} Cypher literals; the AST walk is "
            "probably broken, which would make this test vacuous"
        )

    def test_all_allowed(self):
        literals = self._cypher_literals()
        refused = []
        for source, cypher in literals:
            try:
                assert_read_only(cypher)
            except CypherRefused as exc:
                refused.append(f"{source}: [{exc.category}] {' '.join(cypher.split())[:120]}")
        assert not refused, (
            "The guard refuses Cypher this repository actually issues. Either "
            "the query is wrong or the guard over-refuses:\n  " + "\n  ".join(refused)
        )
