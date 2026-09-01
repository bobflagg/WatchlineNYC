"""Hermetic test for the aggregator-audit address normalizer (dependency-light, base tier)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.aggregator_audit import _norm


def test_norm_strips_borough_suffix_and_collapses_whitespace():
    # The ', <BOROUGH> NY' suffix (present on ~90% of bizaddrs, absent on the rest) is dropped so
    # the same office isn't split into two degree buckets.
    assert _norm("156 WEST 56 STREET 6 FL, MANHATTAN NY") == "156 WEST 56 STREET 6 FL"
    assert _norm("156 west 56 street 6 fl") == "156 WEST 56 STREET 6 FL"
    assert _norm("99  PARK   AVENUE 14 FL , NEW YORK NY") == "99 PARK AVENUE 14 FL"


def test_norm_handles_null_and_blank():
    assert _norm(None) == ""
    assert _norm("") == ""


def test_norm_keeps_unit_designators_distinct():
    # Different floors/suites are genuinely different offices — must NOT be collapsed together.
    assert _norm("770 LEXINGTON AVENUE") != _norm("770 LEXINGTON AVENUE 7 FL")
