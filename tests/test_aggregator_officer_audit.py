"""Hermetic tests for the aggregator-officer classifier — the out-of-state signal is necessary but not
sufficient; the servicer-corp share is what separates a national servicer signer (Eric Moore) from a real
out-of-state owner (a Maine LIHTC developer, a NH fund)."""
from watchline.discovery.ingest.portfolio.aggregator_officer_audit import (
    is_institutional_officer, CURATED_SERVICER_OFFICERS)


def test_flags_out_of_state_servicer():
    assert is_institutional_officer(210, 99, 90) is True     # Eric Moore (Fannie/Selene/Shellpoint)
    assert is_institutional_officer(43, 100, 100) is True    # Teresa Boudreaux (Reverse Mortgage Solutions)


def test_keeps_out_of_state_real_owner_no_servicer_corp():
    # Charles Gendron (Maine developer), Jacob Sacks (NH "CCM Ventures") — far-state and at scale, but their
    # buildings are owner-LLCs, not servicer-owned. NOT flagged.
    assert is_institutional_officer(23, 100, 0) is False
    assert is_institutional_officer(21, 100, 5) is False


def test_keeps_local_owner_however_many_shell_llcs():
    # Mark Scharfman: 136 buildings, all NY (0% far) — a real owner, never flagged, even though his
    # owner-of-record diversity (per-building shell LLCs) matches an aggregator's.
    assert is_institutional_officer(136, 0, 0) is False


def test_keeps_small_out_of_state_owner():
    assert is_institutional_officer(3, 100, 100) is False    # below the scale gate


def test_curated_allowlist_is_the_rule_confirmed_servicers():
    assert CURATED_SERVICER_OFFICERS == {"ERIC MOORE", "KARLA BALLARD", "TERESA BOUDREAUX"}
