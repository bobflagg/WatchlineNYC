"""Validation 5.5 — re-derive the vocabulary from live data and diff it.

Run with ``pytest -m integration``.

``vocab.py`` is a snapshot of a graph that changes on someone else's schedule.
A stale vocabulary does not raise — it quietly returns wrong counts, which is
precisely the failure mode the module exists to prevent. So the module's claims
are checked against the graph rather than trusted.

These are full scans over ~42.3M ``Event`` nodes and take a while. That is the
cost of knowing; run them before merging anything that touches event queries.

**A failure here is information, not necessarily a bug.** New values mean the
pipeline changed and ``vocab.py`` needs updating — the diff says exactly how.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent import db
from watchline.discovery.agent.vocab import (
    VALID_PAIRS,
    EventType,
    Source,
    Status,
    canonical_status,
    expected_raw_classes,
    expected_raw_statuses,
    status_filter,
)

pytestmark = pytest.mark.integration

SCAN_TIMEOUT = 900.0


@pytest.fixture(scope="module")
def live_pairs() -> set[tuple[str, str]]:
    result = db.read(
        "MATCH (e:Event) RETURN DISTINCT e.source_name AS source, e.event_type AS type",
        row_cap=200,
        timeout=SCAN_TIMEOUT,
    )
    return {(r["source"], r["type"]) for r in result.records}


@pytest.fixture(scope="module")
def live_statuses() -> dict[tuple[str, str], set[str | None]]:
    """Raw status values per pair, with HPD-Litigations left raw on purpose.

    Litigation values embed a date, so they are checked by prefix rather than
    enumerated.
    """
    result = db.read(
        """MATCH (e:Event)
           WHERE e.source_name <> 'HPD-Litigations'
           RETURN DISTINCT e.source_name AS source, e.event_type AS type,
                  e.status AS status""",
        row_cap=2000,
        timeout=SCAN_TIMEOUT,
    )
    found: dict[tuple[str, str], set[str | None]] = {}
    for row in result.records:
        found.setdefault((row["source"], row["type"]), set()).add(row["status"])
    return found


@pytest.fixture(scope="module")
def live_classes() -> dict[tuple[str, str], set[str]]:
    result = db.read(
        """MATCH (e:Event) WHERE e.violation_class IS NOT NULL
           RETURN DISTINCT e.source_name AS source, e.event_type AS type,
                  e.violation_class AS vc""",
        row_cap=2000,
        timeout=SCAN_TIMEOUT,
    )
    found: dict[tuple[str, str], set[str]] = {}
    for row in result.records:
        found.setdefault((row["source"], row["type"]), set()).add(row["vc"])
    return found


class TestPairMatrix:
    def test_no_unknown_pairs(self, live_pairs):
        declared = {(s.value, t.value) for s, t in VALID_PAIRS}
        undeclared = live_pairs - declared
        assert not undeclared, (
            f"Graph has (source, event_type) pairs vocab.py does not declare: "
            f"{sorted(undeclared)}. Add them to VALID_PAIRS."
        )

    def test_no_phantom_pairs(self, live_pairs):
        """Declaring a pair that no longer exists is also drift."""
        declared = {(s.value, t.value) for s, t in VALID_PAIRS}
        phantom = declared - live_pairs
        assert not phantom, (
            f"vocab.py declares pairs absent from the graph: {sorted(phantom)}"
        )


class TestStatusVocabulary:
    def test_every_live_status_is_mapped(self, live_statuses):
        """Validation 5.1 — nothing in the graph resolves to UNKNOWN unless
        vocab.py deliberately says so."""
        documented_unknowns = {
            (Source.ECB.value, EventType.JUDGMENT.value, "Unknown"),
            (Source.MARSHAL.value, EventType.EVICTION.value, "EAST"),
        }
        surprises: list[tuple[str, str, str]] = []
        for (source, event_type), values in live_statuses.items():
            for raw in values:
                if raw is None:
                    continue
                if canonical_status(source, event_type, raw) is Status.UNKNOWN:
                    if (source, event_type, raw) not in documented_unknowns:
                        surprises.append((source, event_type, raw))
        assert not surprises, (
            f"Live status values that map to UNKNOWN and are not documented as "
            f"such: {sorted(surprises)}. Either add them to vocab.py's mapping "
            f"or record them as known-bad."
        )

    def test_declared_raw_statuses_still_exist(self, live_statuses):
        for (source, event_type), declared in expected_raw_statuses().items():
            live = live_statuses.get((source.value, event_type.value), set())
            missing = {value for value in declared} - live
            assert not missing, (
                f"{source.value}/{event_type.value}: vocab.py declares raw "
                f"statuses no longer present: {sorted(missing)}"
            )

    def test_litigation_prefixes_cover_everything(self):
        """HPD-Litigations status is unbounded, so check the prefix set."""
        result = db.read(
            """MATCH (e:Event) WHERE e.source_name = 'HPD-Litigations'
               RETURN DISTINCT head(split(coalesce(e.status, ''), ' ')) AS token""",
            row_cap=2000,
            timeout=SCAN_TIMEOUT,
        )
        unmapped = [
            row["token"]
            for row in result.records
            if row["token"]
            and canonical_status("HPD-Litigations", "CourtFiling", row["token"])
            is Status.UNKNOWN
        ]
        assert not unmapped, (
            f"Unmapped HPD-Litigations status tokens: {sorted(unmapped)}"
        )


class TestClassVocabulary:
    def test_every_live_class_is_declared(self, live_classes):
        documented = {
            (source.value, event_type.value): set(values)
            for (source, event_type), values in expected_raw_classes().items()
        }
        surprises: dict[str, list[str]] = {}
        for (source, event_type), live in live_classes.items():
            declared = documented.get((source, event_type))
            if declared is None:
                surprises[f"{source}/{event_type}"] = sorted(live)
                continue
            extra = live - declared
            if extra:
                surprises[f"{source}/{event_type}"] = sorted(extra)
        assert not surprises, (
            f"violation_class values in the graph that vocab.py does not "
            f"declare: {surprises}"
        )

    def test_hpd_and_dob_still_overlap(self, live_classes):
        """The collision is the reason source_name is mandatory.

        If it ever stops being true, that is worth knowing — but the guard
        should not be removed on an assumption.
        """
        hpd = live_classes.get(("HPD", "Violation"), set())
        dob = live_classes.get(("DOB", "Violation"), set())
        assert hpd & dob, (
            "HPD and DOB violation_class no longer share any code. Confirm "
            "before relaxing anything that depends on the collision."
        )


class TestGeneratedFiltersReturnRealRows:
    """The generated predicates must actually match data.

    A filter that is syntactically valid but matches nothing looks exactly like
    a legitimately empty result, so assert real rows come back.
    """

    @pytest.mark.parametrize(
        ("source", "event_type"),
        [
            ("HPD", "Complaint"),
            ("HPD", "Violation"),
            ("DOB", "Violation"),
            ("ECB", "Judgment"),
        ],
    )
    def test_open_filter_matches_rows(self, source, event_type):
        raw_filter = status_filter(source, event_type, Status.OPEN)
        fragment, params = raw_filter.to_cypher("e.status")
        cypher = (
            "MATCH (e:Event) "
            "WHERE e.source_name = $source AND e.event_type = $type "
            f"AND {fragment} "
            "RETURN count(e) AS c"
        )
        result = db.read(
            cypher,
            {"source": source, "type": event_type, **params},
            timeout=SCAN_TIMEOUT,
        )
        assert result.single["c"] > 0, (
            f"Generated OPEN filter for {source}/{event_type} matched nothing: "
            f"{fragment} {params}"
        )

    def test_hpd_complaint_open_count_is_case_independent(self):
        """The half-the-rows regression, checked against live data.

        HPD complaints store 'OPEN'; a naive `status = 'Open'` returns zero.
        The generated filter must find them regardless of casing.
        """
        naive = db.read(
            "MATCH (e:Event) WHERE e.source_name = 'HPD' AND e.event_type = 'Complaint' "
            "AND e.status = 'Open' RETURN count(e) AS c",
            timeout=SCAN_TIMEOUT,
        ).single["c"]

        fragment, params = status_filter("HPD", "Complaint", Status.OPEN).to_cypher("e.status")
        canonical = db.read(
            "MATCH (e:Event) WHERE e.source_name = 'HPD' AND e.event_type = 'Complaint' "
            f"AND {fragment} RETURN count(e) AS c",
            params,
            timeout=SCAN_TIMEOUT,
        ).single["c"]

        assert canonical > 0
        assert naive == 0, (
            "Expected the naive Titlecase filter to miss all open HPD "
            f"complaints, but it found {naive}. The stored casing may have "
            "changed; update vocab.py."
        )

    def test_hazard_filter_excludes_class_i(self):
        """Quantify what including Class I would do to a hazard count.

        Class I is an administrative notice — an unresolved order or invalid
        registration — not a condition found on inspection. Counting it as a
        hazard overstates physical conditions in buildings.
        """
        from watchline.discovery.agent.vocab import class_filter, hpd_hazard_filter

        def count(raw_filter) -> int:
            fragment, params = raw_filter.to_cypher("e.violation_class")
            return db.read(
                "MATCH (e:Event) WHERE e.source_name = 'HPD' "
                f"AND e.event_type = 'Violation' AND {fragment} "
                "RETURN count(e) AS c",
                params,
                timeout=SCAN_TIMEOUT,
            ).single["c"]

        hazard_only = count(hpd_hazard_filter())
        all_classes = count(class_filter("HPD", "Violation", {"A", "B", "C", "I"}))
        informational = all_classes - hazard_only

        assert informational > 0, "Expected Class I rows to exist"
        assert hazard_only < all_classes
        # Guards against someone quietly folding I into the hazard scale.
        inflation = informational / hazard_only
        assert inflation > 0.05, (
            f"Class I is {inflation:.1%} of hazard violations "
            f"({informational:,} of {hazard_only:,}) — large enough that "
            "including it would materially misstate hazard counts"
        )

    def test_class_filter_does_not_leak_across_sources(self):
        """HPD class 'C' and DOB class 'C' must not be summed together."""
        from watchline.discovery.agent.vocab import class_filter

        counts = {}
        for source in ("HPD", "DOB"):
            fragment, params = class_filter(source, "Violation", "C").to_cypher(
                "e.violation_class"
            )
            counts[source] = db.read(
                "MATCH (e:Event) WHERE e.source_name = $source "
                f"AND e.event_type = 'Violation' AND {fragment} "
                "RETURN count(e) AS c",
                {"source": source, **params},
                timeout=SCAN_TIMEOUT,
            ).single["c"]

        unscoped = db.read(
            "MATCH (e:Event) WHERE e.event_type = 'Violation' "
            "AND toUpper(e.violation_class) = 'C' RETURN count(e) AS c",
            timeout=SCAN_TIMEOUT,
        ).single["c"]

        assert counts["HPD"] > 0 and counts["DOB"] > 0
        assert unscoped == counts["HPD"] + counts["DOB"], (
            "Unscoped class 'C' should equal HPD + DOB, demonstrating that an "
            f"unsourced filter conflates them: {counts} vs {unscoped}"
        )
