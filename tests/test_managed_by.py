"""Hermetic tests for the MANAGED_BY manager-name normalizer.

Pure function; gated on the ingest extra (pandas import in the module). Skips cleanly
without it. Run under ``uv run --extra ingest pytest``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pandas")

from watchline.discovery.ingest.portfolio.managed_by import norm_manager


def test_folds_form_and_geo_variants_to_one_brand():
    for v in ("ORSID NY", "ORSID REALTY", "ORSID REALTY CORP", "ORSID REALTY CORP.",
              "ORSID NEW YORK"):
        assert norm_manager(v) == "ORSID", v


def test_strips_corporate_and_descriptor_suffixes():
    assert norm_manager("AKAM ASSOCIATES, INC.") == "AKAM"
    assert norm_manager("FIRSTSERVICE RESIDENTIAL") == "FIRSTSERVICE"
    assert norm_manager("THE ANDREWS ORGANIZATION") == "ANDREWS"
    assert norm_manager("DOUGLAS ELLIMAN PROPERTY MANAGEMENT") == "DOUGLAS ELLIMAN"


def test_generic_only_name_falls_back_to_full_name_not_empty():
    # Nothing distinctive survives the strip -> keep the full collapsed name, never empty.
    assert norm_manager("MANAGEMENT LLC") == "MANAGEMENT LLC"
    assert norm_manager("THE REALTY GROUP") == "THE REALTY GROUP"


def test_null_and_blank_are_none():
    assert norm_manager(None) is None
    assert norm_manager("") is None
    assert norm_manager("   ") is None


def test_placeholder_agent_strings_are_dropped():
    for junk in ("NONE", "none", "N/A", "N A", "NA", "UNKNOWN", "SAME AS OWNER",
                 "MANAGING AGENT", "NONE LLC"):
        assert norm_manager(junk) is None, junk
    # a real brand that merely CONTAINS a placeholder-ish token still resolves
    assert norm_manager("SAMSON MANAGEMENT") == "SAMSON"


def test_known_limitation_concatenation_not_split():
    # Documented residual: a concatenated variant is NOT merged with the spaced brand
    # (left un-merged rather than risk over-splitting). ORSIDNY stays its own key.
    assert norm_manager("ORSIDNY") == "ORSIDNY"
    assert norm_manager("ORSID NY") == "ORSID"
