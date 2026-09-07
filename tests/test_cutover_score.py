"""Hermetic tests for the Track-A cutover gate scorer (Option B)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.eval.cutover_score import per_item_loss, score_cutover, S1, S2


def test_per_item_loss_encodes_the_refinement_structure():
    assert per_item_loss(S1, "DIFFERENT") == (0.0, 5.0)   # v2 correct split, legacy false-merge
    assert per_item_loss(S1, "SAME") == (1.0, 0.0)        # v2 false-split, legacy correct
    assert per_item_loss(S2, "DIFFERENT") == (5.0, 5.0)   # both false-merge (agreement)
    assert per_item_loss(S2, "SAME") == (0.0, 0.0)


def _key(pid, stratum):
    return {"pair_id": pid, "stratum": stratum}


def test_clean_case_passes_and_v2_beats_legacy():
    # all splits correct (gold DIFFERENT): v2 better than legacy -> diff <= 0 <= delta, no severe merges.
    key = [_key(f"s{i}", S1) for i in range(10)] + [_key(f"m{i}", S2) for i in range(10)]
    ann = ([{"pair_id": f"s{i}", "label": "DIFFERENT"} for i in range(10)]      # v2 correct splits
           + [{"pair_id": f"m{i}", "label": "SAME"} for i in range(10)])        # retained merges correct
    out = score_cutover(key, ann, bootstrap_n=500)
    assert out["verdict"] == "PASS"
    assert out["loss_diff_upper95"] <= 0.0                # v2 strictly better here
    assert out["fs_v2"]["k"] == 0 and out["fm_v2"]["k"] == 0


def test_severe_false_merge_vetoes():
    key = [_key("m1", S2)]
    ann = [{"pair_id": "m1", "label": "DIFFERENT", "severe": True}]   # a severe false merge among retained
    out = score_cutover(key, ann, bootstrap_n=200)
    assert out["severe_veto_ok"] is False and out["verdict"] == "FAIL"
    assert out["fm_v2"]["k"] == 1


def test_many_false_splits_break_noninferiority():
    # v2 wrongly splits (gold SAME on S1) -> v2 worse than legacy -> diff upper > delta -> FAIL.
    key = [_key(f"s{i}", S1) for i in range(20)]
    ann = [{"pair_id": f"s{i}", "label": "SAME"} for i in range(20)]
    out = score_cutover(key, ann, bootstrap_n=500)
    assert out["noninferiority_ok"] is False and out["verdict"] == "FAIL"
    assert out["fs_v2"]["k"] == 20


def test_indeterminate_excluded_from_primary_but_in_worstcase_and_coverage():
    key = [_key("m1", S2), _key("m2", S2)]
    ann = [{"pair_id": "m1", "label": "SAME"}, {"pair_id": "m2", "label": "INDETERMINATE"}]
    out = score_cutover(key, ann, bootstrap_n=200)
    assert out["determinate"] == 1 and out["indeterminate"] == 1
    assert out["coverage"] == 0.5
    assert out["fm_v2"]["n"] == 1                          # indeterminate not in the determinate denominator
    assert out["worst_case_fm_v2_rate"] == 0.5             # 1 indeterminate counted as an error / (1+1)


def test_deployment_weight_flag_defaults_false():
    out = score_cutover([_key("s1", S1)], [{"pair_id": "s1", "label": "DIFFERENT"}], bootstrap_n=100)
    assert out["weights_are_deployment"] is False          # guards against mistaking an unweighted run
