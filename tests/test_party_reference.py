"""Hermetic tests for party-reference stable keying (Option B Phase 2, contracts C1/C0)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.party_reference import (
    NORMALIZATION_VERSION, normalize_name, party_reference_id)


def test_id_is_stable_and_deterministic():
    a = party_reference_id("Steven Croman", "156 W 56 St, NEW YORK NY")
    b = party_reference_id("Steven Croman", "156 W 56 St, NEW YORK NY")
    assert a == b                                   # deterministic (SHA-1, not salted hash)
    assert a.startswith(f"PR-{NORMALIZATION_VERSION}-") and len(a) == len(f"PR-{NORMALIZATION_VERSION}-") + 12


def test_case_and_whitespace_do_not_change_the_key():
    assert party_reference_id("STEVEN  CROMAN ", "100 MAIN ST") == \
           party_reference_id("steven croman", "100 MAIN ST")


def test_borough_suffix_collapses_via_shared_address_norm():
    # normalize_address (shared with the pipeline) strips a trailing ", BOROUGH NY".
    assert party_reference_id("ACME LLC", "100 MAIN ST, BRONX NY") == \
           party_reference_id("ACME LLC", "100 MAIN ST")


def test_distinct_parties_get_distinct_ids():
    assert party_reference_id("ACME LLC", "100 MAIN ST") != party_reference_id("ACME CORP", "100 MAIN ST")
    assert party_reference_id("JOHN SMITH", "1 A ST") != party_reference_id("JOHN SMITH", "2 B ST")


def test_corporate_suffix_is_not_stripped():
    # distinct entities must not collapse (suffix stripping is a resolution decision, not reference-identity)
    assert normalize_name("ACME LLC") != normalize_name("ACME CORP")
    assert normalize_name("ACME LLC") == "ACME LLC"


def test_empty_and_none_are_handled():
    assert normalize_name(None) == "" and normalize_name("  ") == ""
    # keys still computable (won't crash) for missing fields
    assert party_reference_id(None, None).startswith("PR-")
