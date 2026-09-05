"""Hermetic tests for the pure scoring helpers (no DB)."""
from __future__ import annotations

import pytest

pytest.importorskip("psycopg2")   # score.py imports the pg connection helper at module load
from watchline.discovery.ingest.portfolio.eval import score as S


def test_wilson_bounds():
    assert S.wilson(0, 0) == (0.0, 0.0, 0.0)
    p, lo, hi = S.wilson(10, 10)
    assert p == 1.0 and 0.0 < lo < 1.0 and 0.9 < hi <= 1.0   # Wilson upper < 1 even at p=1
    p, lo, hi = S.wilson(5, 10)
    assert abs(p - 0.5) < 1e-9 and lo < 0.5 < hi


def test_kappa():
    assert S.cohens_kappa([("SAME", "SAME"), ("DIFFERENT", "DIFFERENT")]) == 1.0
    k = S.cohens_kappa([("SAME", "DIFFERENT"), ("DIFFERENT", "SAME")])
    assert k is not None and k < 0.1


def test_mcnemar():
    assert S.mcnemar(0, 0) == 1.0
    assert S.mcnemar(12, 0) < 0.01          # one-sided pile-up -> significant


def test_gold_label_adjudicator_wins_then_agreement_then_unresolved():
    adj = [{"annotator_id": "ann_1", "label": "SAME", "evidence_tiers": ["T1"]},
           {"annotator_id": "ann_2", "label": "DIFFERENT", "evidence_tiers": []},
           {"annotator_id": "adjudicator", "label": "DIFFERENT", "evidence_tiers": ["T3"]}]
    assert S.gold_label(adj) == ("DIFFERENT", ["T3"])
    agree = [{"annotator_id": "ann_1", "label": "SAME", "evidence_tiers": ["T1"]},
             {"annotator_id": "ann_2", "label": "SAME", "evidence_tiers": ["T2"]}]
    g, tiers = S.gold_label(agree)
    assert g == "SAME" and set(tiers) == {"T1", "T2"}
    disagree = [{"annotator_id": "ann_1", "label": "SAME", "evidence_tiers": []},
                {"annotator_id": "ann_2", "label": "DIFFERENT", "evidence_tiers": []}]
    assert S.gold_label(disagree)[0] == "UNRESOLVED"


def test_corroboration_class():
    assert S.corroboration_class("acris-deed", "SAME", ["T1"]) == "C2"           # deed-only
    assert S.corroboration_class("acris-deed", "SAME", ["T1", "T2"]) == "C1"     # cross-source
    assert S.corroboration_class("splink-fellegi-sunter", "SAME", ["T1"]) == "C1"
    assert S.corroboration_class("acris-deed", "DIFFERENT", ["T1"]) is None
