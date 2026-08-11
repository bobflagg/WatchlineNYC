"""Hermetic tests for the operator-cluster network renderer (ui/cluster_viz.py).

Pure; no Streamlit, no Neo4j. Covers self-containment (inline SVG, no JS/host),
the summary, branded/unbranded, and that attacker-influenceable text is escaped.
"""

from __future__ import annotations

from watchline.discovery.ui.cluster_viz import to_html

_CLUSTER = {
    "name": "SCOTT CASTELLANO",
    "buildings": 356, "residential_units": 9637, "rent_stabilized_units": 3065,
    "records": [
        {"actor_id": "ACT-LL-100716", "buildings": 125},
        {"actor_id": "ACT-LL-100718", "buildings": 231},
        {"actor_id": "ACT-LL-100715", "buildings": 0},
    ],
    "name_edges": [{"source": "ACT-LL-100716", "target": "ACT-LL-100718"}],
    "events": [{"event_type": "Complaint", "events": 55147},
               {"event_type": "Violation", "events": 40061}],
}


def test_self_contained_svg_network():
    html = to_html(_CLUSTER)
    assert html.startswith("<!doctype html>")
    assert "<svg" in html
    assert "<script" not in html                 # no JavaScript
    assert 'src="http' not in html               # no external host
    assert "SCOTT CASTELLANO" in html
    assert "55,147" in html                       # event fingerprint, formatted


def test_summary_stats_present():
    html = to_html(_CLUSTER)
    assert "356" in html and "9,637" in html and "3,065" in html   # buildings/units/RS


def test_unbranded_drops_the_masthead():
    assert '<div class="mast">' in to_html(_CLUSTER, branded=True)
    assert '<div class="mast">' not in to_html(_CLUSTER, branded=False)


def test_names_are_escaped_not_executed():
    html = to_html({"name": "<script>alert(1)</script>", "buildings": 0,
                    "residential_units": 0, "rent_stabilized_units": 0,
                    "records": [], "name_edges": [], "events": []})
    assert "<script>alert(1)</script>" not in html      # not a live tag
    assert "&lt;script&gt;" in html                      # escaped to text


def test_empty_cluster_does_not_crash():
    html = to_html({"name": "X", "records": [], "name_edges": []})
    assert "<svg" in html
