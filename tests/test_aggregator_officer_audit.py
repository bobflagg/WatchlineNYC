"""Hermetic tests for the aggregator-officer classifier (the out-of-state institutional-signal
discriminator that owner-diversity can't provide — Scharfman vs Eric Moore)."""
from watchline.discovery.ingest.portfolio.aggregator_officer_audit import is_institutional_officer


def test_flags_out_of_state_at_scale():
    assert is_institutional_officer(210, 99) is True    # Eric Moore
    assert is_institutional_officer(43, 100) is True     # Teresa Boudreaux (OLIT servicer)


def test_keeps_local_owner_however_many_shell_llcs():
    # Mark Scharfman: 136 buildings, all NY (0% far) — a real owner, never flagged, even though his
    # owner-of-record diversity (per-building shell LLCs) matches an aggregator's.
    assert is_institutional_officer(136, 0) is False


def test_keeps_small_out_of_state_owner():
    # A snowbird with a couple of NYC buildings from FL is below the scale gate.
    assert is_institutional_officer(3, 100) is False


def test_keeps_one_stray_far_filing():
    # A big local owner with one out-of-state filing stays under the far-share gate.
    assert is_institutional_officer(80, 20) is False
