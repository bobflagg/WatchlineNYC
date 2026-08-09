"""Hermetic tests for the pure HTML report renderer (ui/report.py). No Streamlit.

Deterministic given a fixed ``generated_at``; covers branding/self-containment, the
markdown→HTML narrative (tables/headings/TOC), provenance, evidence, badges, and —
importantly — that attacker-influenceable narrative text is escaped, not executed.
"""

from __future__ import annotations

from watchline.discovery.ui.cost import Cost, Usage
from watchline.discovery.ui.report import to_html
from watchline.discovery.ui.stream import Evidence

_NARRATIVE = (
    "## Executive Summary\n\n"
    "The portfolio shows worsening conditions.\n\n"
    "| Metric | Value |\n|---|---|\n| Open violations | 1,399 |\n\n"
    "### Detail\n\nThe most recent case is PENDING.\n\n"
    "> Key takeaway: conditions are worsening.\n"
)


def _evidence() -> Evidence:
    return Evidence(
        caveats=[{"tool": "lookup_building_ownership", "element": "apparent_control",
                  "text": "Apparent control is inferred, not a legal finding."}],
        citations=[{"tool": "deep_investigation → lookup_landlord", "source_name": None, "run_id": "run-9"}],
        web_sources=[{"title": "Steven Croman — Wikipedia", "url": "https://en.wikipedia.org/wiki/Steven_Croman"}],
        web_searches=2,
        resolved_reference={"type": "landlord", "id": "ACT-LL-105699", "via": "indexed"},
    )


def _html(narrative=_NARRATIVE, evidence=None, **kw) -> str:
    kw.setdefault("generated_at", "2026-08-06")
    kw.setdefault("model", "claude-sonnet-5")
    kw.setdefault("trust_level", "vetted")
    kw.setdefault("cost", Cost(usage=Usage(model="claude-sonnet-5"), usd=0.0123))
    return to_html("Who controls ACT-LL-105699?", narrative,
                   _evidence() if evidence is None else evidence, **kw)


def test_self_contained_and_branded():
    html = _html()
    assert html.startswith("<!doctype html>")
    assert "Watchline NYC — Discovery" in html
    assert "data:image/png;base64," in html          # logo embedded
    assert 'src="http' not in html                   # no external image/script host


def test_unbranded_preview_omits_the_masthead():
    # branded=True keeps the full masthead (standalone artifact); branded=False drops
    # it entirely (the in-app preview, where the app already frames the result).
    branded = _html()
    assert 'class="masthead"' in branded and '<img class="logo"' in branded
    plain = _html(branded=False)
    assert 'class="masthead"' not in plain
    assert '<img class="logo"' not in plain
    assert 'class="provenance' in plain                  # metadata strip retained (rounded)


def test_narrative_markdown_becomes_styled_html():
    html = _html()
    assert '<div class="tablewrap"><table>' in html  # tables wrapped for scroll
    assert '<h2 id="executive-summary"' in html      # heading carries an id
    assert "<blockquote>" in html                    # callout-styled blockquote


def test_toc_omitted_when_few_sections():
    # _NARRATIVE has only two headings — below the threshold, so no contents list.
    assert 'class="toc"' not in _html()


def test_toc_rendered_and_linked_when_enough_sections():
    md = "".join(f"## Section {i}\n\nbody text\n\n" for i in range(1, 6))  # 5 sections
    html = _html(narrative=md)
    assert 'class="toc"' in html
    assert 'href="#section-1"' in html and 'href="#section-5"' in html


def test_provenance_strip_shows_context_and_cost():
    html = _html()
    assert "2026-08-06" in html and "vetted" in html
    assert "2 web searches" in html
    assert "$0.0123" in html


def test_status_words_become_badges():
    html = _html()
    assert '<span class="badge pending">PENDING</span>' in html


def test_status_words_inside_tags_are_not_badged():
    # A status token inside a tag (here, a link href) must survive untouched; only the
    # standalone word in text becomes a badge.
    html = to_html("q", "[link](https://example.com/OPEN) and OPEN here.", None,
                   generated_at="2026-08-06")
    assert 'href="https://example.com/OPEN"' in html          # untouched inside the tag
    assert '<span class="badge open">OPEN</span>' in html     # standalone word badged


def test_evidence_citations_caveats_sources_and_legend():
    html = _html()
    assert "Evidence &amp; Sources" in html
    assert "Graph-verified" in html and "Web-sourced" in html          # legend
    assert "Apparent control is inferred" in html                       # caveat text
    assert '<span class="chip">apparent_control</span>' in html         # element chip
    assert "run-9" in html
    assert 'href="https://en.wikipedia.org/wiki/Steven_Croman"' in html
    assert "Resolved reference" in html and "ACT-LL-105699" in html


def test_web_searches_note_when_no_sources():
    ev = _evidence()
    ev.web_sources = []
    html = _html(evidence=ev)
    assert "Web searches performed: 2 (no sources returned)" in html


def test_narrative_html_is_escaped_not_executed():
    danger = "## X\n\n<script>alert(1)</script> and <img src=x onerror=alert(1)>\n"
    html = _html(narrative=danger)
    assert "<script>alert(1)</script>" not in html            # not a live tag
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html    # escaped to text
    assert "<img src=x onerror" not in html                   # the malicious img is inert
