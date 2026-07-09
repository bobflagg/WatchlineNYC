"""
scripts/verify_consistency.py

Phase 5 reconciliation verification: cross-graph consistency checks.

Connects to both Neo4j KGs (evidentiary + discovery) and runs a suite
of checks designed to catch any remaining substrate divergence.

Checks
------
  1. Connectivity — both databases reachable
  2. Building counts — evidentiary ≤ discovery (PLUTO is the superset)
  3. BBL format — all Building.bbl should be 10-char strings in both graphs
  4. Event source_name distribution — HPD-Litigations not HPD for litigations
  5. Event ID prefixes — no legacy EVT-DOB-{number} scheme (pre-ADR-003)
  6. Actor key namespace — discovery uses ACT-LL-* not bare ACT-*
  7. Spot-check BBLs — known test buildings exist in both graphs
  8. Cross-graph BBL overlap — random evidentiary sample present in discovery
  9. Idempotency guard — no bare CREATE (vs MERGE) in pipeline Cypher

Usage
-----
    uv run python scripts/verify_consistency.py

Exit code: 0 if all checks pass or warn, 1 if any check fails.
"""

import logging
import os
import re
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase, warnings as neo4j_warnings

# Suppress verbose "label does not exist" / "property does not exist"
# notifications from Neo4j — these are expected on an empty graph and
# just clutter the output. Actual errors still surface as exceptions.
logging.getLogger("neo4j").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=neo4j_warnings.Neo4jWarning)

load_dotenv()

# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USER     = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
EV_DB  = os.environ.get("NEO4J_EVIDENTIARY_DATABASE", "evidentiary")
DC_DB  = os.environ.get("NEO4J_DISCOVERY_DATABASE",   "neo4j")

# Known test buildings (BBL → description)
SPOT_BBLS = {
    "1009940001": "122 W 97th St, Manhattan (DT-001 smoke test)",
    "2022610001": "530 E 169th St, Bronx   (PortfolioIdentification test)",
    "2028530086": "1459 Wythe Pl, Bronx    (FineEvasion test)",
    "1000477502": "1 Police Plaza, Manhattan (PLUTO-only building)",
}

# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"

_results = {"passed": 0, "failed": 0, "warned": 0}


def ok(label, detail=""):
    _results["passed"] += 1
    print(f"  {PASS}  {label}" + (f"  ({detail})" if detail else ""))


def fail(label, detail=""):
    _results["failed"] += 1
    print(f"  {FAIL}  {label}" + (f"  ({detail})" if detail else ""))


def warn(label, detail=""):
    _results["warned"] += 1
    print(f"  {WARN}  {label}" + (f"  ({detail})" if detail else ""))


def section(title):
    print()
    print(f"── {title}")


def run_query(driver, database, cypher, params=None):
    with driver.session(database=database) as session:
        return list(session.run(cypher, **(params or {})))


# ---------------------------------------------------------------------------
# Check 1: Connectivity
# ---------------------------------------------------------------------------

def check_connectivity(driver):
    section("1. Connectivity")
    for db, label in [(EV_DB, "evidentiary"), (DC_DB, "discovery")]:
        try:
            run_query(driver, db, "RETURN 1 AS ping")
            ok(f"{label} database reachable", db)
        except Exception as e:
            fail(f"{label} database unreachable", str(e))


# ---------------------------------------------------------------------------
# Check 2: Building counts
# ---------------------------------------------------------------------------

def check_building_counts(driver):
    section("2. Building node counts")
    ev = run_query(driver, EV_DB, "MATCH (b:Building) RETURN count(b) AS n")[0]["n"]
    dc = run_query(driver, DC_DB, "MATCH (b:Building) RETURN count(b) AS n")[0]["n"]
    ok(f"Evidentiary buildings: {ev:,}")
    ok(f"Discovery  buildings:  {dc:,}")
    if ev == 0 and dc == 0:
        warn(
            "Both graphs are empty — checks 3-8 require loaded graphs",
            "run 'make evidentiary-build' and 'make discovery-ingest-all' first",
        )
        return False   # signal to caller that data checks should be skipped
    if dc >= ev:
        ok("Discovery ≥ Evidentiary (PLUTO is the superset)")
    else:
        fail(
            "Discovery < Evidentiary — unexpected",
            f"{dc:,} < {ev:,}: evidentiary graph has buildings not in discovery",
        )
    if ev < 400_000:
        warn("Evidentiary building count below 400K — graph may need rebuild")
    if dc < 800_000:
        warn("Discovery building count below 800K — PLUTO substrate may not be loaded")
    return True


# ---------------------------------------------------------------------------
# Check 3: BBL format
# ---------------------------------------------------------------------------

def check_bbl_format(driver):
    section("3. BBL format validity (all should be 10-char strings)")
    for db, label in [(EV_DB, "evidentiary"), (DC_DB, "discovery")]:
        rows = run_query(
            driver, db,
            "MATCH (b:Building) WHERE size(b.bbl) <> 10 RETURN count(b) AS n"
        )
        bad = rows[0]["n"]
        if bad == 0:
            ok(f"{label}: all Building.bbl are 10 characters")
        else:
            fail(f"{label}: {bad:,} Building nodes have non-10-char bbl")


# ---------------------------------------------------------------------------
# Check 4: Event source_name — HPD-Litigations (ADR-004)
# ---------------------------------------------------------------------------

def check_source_names(driver):
    section("4. Event source_name distribution (ADR-004)")
    for db, label in [(EV_DB, "evidentiary"), (DC_DB, "discovery")]:
        rows = run_query(
            driver, db,
            """
            MATCH (e:Event)
            WHERE e.event_type = 'CourtFiling' AND e.source_name = 'HPD'
            RETURN count(e) AS n
            """
        )
        legacy_hpd_lit = rows[0]["n"]
        if legacy_hpd_lit == 0:
            ok(f"{label}: no CourtFiling events with legacy source_name='HPD'")
        else:
            fail(
                f"{label}: {legacy_hpd_lit:,} CourtFiling events still have source_name='HPD'",
                "expected 'HPD-Litigations' (ADR-004) — graph needs rebuild",
            )

        rows = run_query(
            driver, db,
            """
            MATCH (e:Event {event_type: 'CourtFiling', source_name: 'HPD-Litigations'})
            RETURN count(e) AS n
            """
        )
        ok(f"{label}: {rows[0]['n']:,} CourtFiling events with source_name='HPD-Litigations'")


# ---------------------------------------------------------------------------
# Check 5: Event ID prefixes — no legacy EVT-DOB-{number} (ADR-003)
# ---------------------------------------------------------------------------

def check_event_id_prefixes(driver):
    section("5. Event ID prefix distribution (ADR-003 — no legacy EVT-DOB-{number})")
    for db, label in [(EV_DB, "evidentiary"), (DC_DB, "discovery")]:
        rows = run_query(
            driver, db,
            """
            MATCH (e:Event)
            WHERE e.source_name = 'DOB'
            WITH e.event_id AS eid
            RETURN
              count(eid) AS total,
              count(CASE WHEN eid STARTS WITH 'EVT-DOB-' THEN 1 END) AS correct_prefix
            """
        )
        if rows:
            total   = rows[0]["total"]
            correct = rows[0]["correct_prefix"]
            if total > 0 and correct == total:
                ok(f"{label}: all {total:,} DOB events use EVT-DOB-* prefix")
            elif total == 0:
                warn(f"{label}: no DOB Event nodes found — graph may need rebuild")
            else:
                fail(
                    f"{label}: {total - correct:,} of {total:,} DOB events have wrong prefix",
                    "graph needs rebuild to migrate pre-ADR-003 event_ids",
                )


# ---------------------------------------------------------------------------
# Check 6: Actor key namespace — ACT-LL- in discovery (ADR-006)
# ---------------------------------------------------------------------------

def check_actor_namespaces(driver):
    section("6. Actor key namespace (ADR-006 — ACT-LL- not bare ACT- in discovery)")
    rows = run_query(
        driver, DC_DB,
        """
        MATCH (a:Actor)
        WHERE a.actor_id STARTS WITH 'ACT-'
          AND NOT a.actor_id STARTS WITH 'ACT-LL-'
          AND NOT a.actor_id STARTS WITH 'ACT-ACRIS-'
        RETURN count(a) AS n
        """
    )
    legacy = rows[0]["n"]
    if legacy == 0:
        ok("Discovery: no bare ACT-* actors (all use ACT-LL- or ACT-ACRIS-)")
    else:
        fail(
            f"Discovery: {legacy:,} Actor nodes still use legacy ACT-* key (not ACT-LL-*)",
            "discovery graph needs rebuild to apply ADR-006",
        )

    rows = run_query(
        driver, DC_DB,
        "MATCH (a:Actor WHERE a.actor_id STARTS WITH 'ACT-LL-') RETURN count(a) AS n"
    )
    ok(f"Discovery: {rows[0]['n']:,} Actor nodes correctly keyed ACT-LL-*")


# ---------------------------------------------------------------------------
# Check 7: Spot-check known BBLs
# ---------------------------------------------------------------------------

def check_spot_bbls(driver):
    section("7. Spot-check known building BBLs")
    for bbl, desc in SPOT_BBLS.items():
        for db, label in [(EV_DB, "ev"), (DC_DB, "dc")]:
            rows = run_query(
                driver, db,
                "MATCH (b:Building {bbl: $bbl}) RETURN b.bbl AS bbl LIMIT 1",
                {"bbl": bbl},
            )
            if rows:
                ok(f"[{label}] {bbl} — {desc}")
            else:
                # Evidentiary may legitimately miss PLUTO-only buildings with no violations
                if label == "ev" and bbl == "1000477502":
                    warn(f"[{label}] {bbl} absent — expected (PLUTO-only, no violations)")
                else:
                    fail(f"[{label}] {bbl} MISSING — {desc}")


# ---------------------------------------------------------------------------
# Check 8: Cross-graph BBL overlap
# ---------------------------------------------------------------------------

def check_cross_graph_overlap(driver):
    section("8. Cross-graph BBL overlap (evidentiary sample ⊆ discovery)")
    ev_bbls = run_query(
        driver, EV_DB,
        "MATCH (b:Building) RETURN b.bbl AS bbl LIMIT 1000"
    )
    ev_sample = [r["bbl"] for r in ev_bbls]
    if not ev_sample:
        warn("No evidentiary buildings to sample")
        return

    dc_matches = run_query(
        driver, DC_DB,
        "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
        {"bbls": ev_sample},
    )
    matched = set(dc_matches[0]["matched"]) if dc_matches else set()
    missing = [b for b in ev_sample if b not in matched]

    pct = 100 * len(matched) / len(ev_sample)
    if len(missing) == 0:
        ok(f"All {len(ev_sample)} sampled evidentiary BBLs found in discovery")
    elif pct >= 95:
        warn(
            f"{len(missing)} of {len(ev_sample)} sampled BBLs absent from discovery ({pct:.1f}% match)",
            "small discrepancy may be acceptable if graphs were built from different snapshots",
        )
    else:
        fail(
            f"{len(missing)} of {len(ev_sample)} sampled BBLs absent from discovery ({pct:.1f}% match)",
            f"examples: {missing[:3]}",
        )


# ---------------------------------------------------------------------------
# Check 9: Idempotency guard — no bare CREATE in pipeline Cypher
# ---------------------------------------------------------------------------

def check_idempotency():
    section("9. Idempotency guard — no bare CREATE in substrate pipeline Cypher")
    root = Path(__file__).parent.parent / "watchline"

    # Overlay pipelines intentionally use CREATE for run-scoped objects:
    #   portfolio/ — Portfolio + Actor nodes keyed by random UUID4; fresh each run
    #   phc001/   — Claim + Evidence nodes versioned per evaluation run
    # Only check substrate pipelines (buildings, violations, events, shared).
    OVERLAY_DIRS = {"portfolio", "phc001"}

    pipeline_files = []
    for f in root.rglob("*/ingest/**/*.py"):
        if not any(part in OVERLAY_DIRS for part in f.parts):
            pipeline_files.append(f)
    pipeline_files += list(root.glob("shared/*.py"))

    # Pattern: CREATE ( — a node creation. CREATE INDEX / CONSTRAINT are fine.
    bare_create_re = re.compile(r"\bCREATE\s*\(", re.IGNORECASE)

    violations = []
    for fpath in sorted(pipeline_files):
        text = fpath.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if bare_create_re.search(stripped):
                violations.append(f"{fpath.relative_to(root.parent)}:{i}  {stripped[:80]}")

    if not violations:
        ok(f"No bare CREATE( in {len(pipeline_files)} substrate pipeline files")
    else:
        fail(f"{len(violations)} bare CREATE( found in substrate pipelines — should be MERGE:")
        for v in violations[:10]:
            print(f"       {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print("Watchline NYC — Phase 5 Reconciliation Verification")
    print("=" * 55)
    print(f"  Evidentiary DB: {EV_DB}  Discovery DB: {DC_DB}")
    print(f"  Neo4j URI:      {NEO4J_URI}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        check_connectivity(driver)
        graphs_loaded = check_building_counts(driver)
        if graphs_loaded:
            check_bbl_format(driver)
            check_source_names(driver)
            check_event_id_prefixes(driver)
            check_actor_namespaces(driver)
            check_spot_bbls(driver)
            check_cross_graph_overlap(driver)
        else:
            print()
            print("  Skipping checks 3-8 — load graphs first, then re-run 'make verify'.")
    finally:
        driver.close()

    check_idempotency()

    p = _results["passed"]
    f = _results["failed"]
    w = _results["warned"]

    print()
    print("=" * 55)
    print(f"  Passed: {p}   Failed: {f}   Warnings: {w}")
    if f == 0:
        print("  All checks passed (some warnings may reflect expected graph state).")
    else:
        print(f"  {f} check(s) failed. Review output above.")
    print()

    sys.exit(0 if f == 0 else 1)


if __name__ == "__main__":
    main()
