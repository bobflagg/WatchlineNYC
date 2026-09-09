"""Hermetic tests for the cluster_gated common-name veto — specifically the surname escalation that fixes the
S2 false-merge leaks (GREG COHEN, ERIC MOORE): a common SURNAME triggers the address requirement even when the
(surname, first-initial) subset stays below name_cap. Needs the `ingest` extra (pandas).

    uv run --extra ingest pytest tests/test_cluster_gated.py
"""
import pandas as pd

from watchline.discovery.ingest.portfolio.splink_source import cluster_gated


def _nodes(rows):
    # rows: (uid, last, init, house, street_norm)
    return pd.DataFrame(rows, columns=["unique_id", "last_name", "first_initial", "biz_house", "biz_street_norm"])


def _preds(pairs):
    # every candidate edge above threshold with agreeing first names (gamma != 0)
    return pd.DataFrame([{"unique_id_l": a, "unique_id_r": b, "match_probability": 0.99, "gamma_first_name": 2}
                         for a, b in pairs])


# A common surname (COHEN=280 summed) whose (COHEN,G) subset is only 9 (< name_cap=15) — the leak profile —
# plus a rare surname (CROMAN=8) that must still merge across a typo'd office (4 vs 424 West 51).
_NAME_FREQ = pd.DataFrame([
    ("COHEN", "G", 9), ("COHEN", "D", 271),   # surname total 280
    ("CROMAN", "S", 8),                        # surname total 8
], columns=["last_name", "first_initial", "identities"])

_NODES = _nodes([
    ("c1", "COHEN", "G", "3030", "NORTHERN"),
    ("c2", "COHEN", "G", "3030", "NORTHERN"),   # same office as c1
    ("c3", "COHEN", "G", "11", "131"),          # STRAY: same full name, different office
    ("r1", "CROMAN", "S", "4", "W 51"),
    ("r2", "CROMAN", "S", "424", "W 51"),       # Croman's typo'd office (different addr key)
])
_PREDS = _preds([("c1", "c2"), ("c1", "c3"), ("c2", "c3"), ("r1", "r2")])


def _clusters(**kw):
    out = cluster_gated(_PREDS, _NODES, threshold=0.95, name_freq=_NAME_FREQ, **kw)
    return dict(zip(out["unique_id"], out["cluster_id"]))


def test_surname_escalation_splits_common_name_stray_keeps_rare_cross_office():
    c = _clusters()  # default surname_cap=50
    assert c["c1"] == c["c2"], "same-office common-surname records still merge"
    assert c["c3"] != c["c1"], "common-surname stray at a DIFFERENT office is split off (COHEN=280>cap)"
    assert c["r1"] == c["r2"], "rare-surname cross-office typo merge is preserved (CROMAN=8<cap)"


def test_escalation_is_load_bearing_without_it_the_stray_merges():
    # With the surname cap effectively disabled, the pre-fix behaviour returns: (COHEN,G)=9 < name_cap, so the
    # stray c3 merges despite the different office — the exact leak the fix closes.
    c = _clusters(surname_cap=10_000)
    assert c["c3"] == c["c1"], "without surname escalation the common-name stray over-merges (the leak)"
