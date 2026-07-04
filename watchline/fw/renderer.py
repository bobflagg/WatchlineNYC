"""
watchline/fw/renderer.py

LangGraph node: render_dashboard

Assembles a self-contained HTML dashboard for each pipeline response.
The renderer:
  1. Loads watchline.css and injects it into base.html
  2. Dispatches to the intent-specific panel renderer
  3. Populates base.html placeholders with panel content + shared metadata
  4. Returns the finished HTML string in state["dashboard_html"]

Architecture:
  - Templates live in watchline/fw/templates/
  - watchline.css is the single CSS source; injected inline for self-containment
  - Intent panel renderers are functions in this module, one per intent
  - The LLM prose string arrives from narrator.py via state["answer"]
  - No LLM calls here — pure data → HTML transformation
"""

import json
import html
import re
from pathlib import Path

from watchline.fw.state import WatchlineState

# ---------------------------------------------------------------------------
# Template paths
# ---------------------------------------------------------------------------

_TMPL_DIR   = Path(__file__).parent / "templates"
_BASE_HTML  = _TMPL_DIR / "base.html"
_CSS_FILE   = _TMPL_DIR / "watchline.css"
_INTENTS    = _TMPL_DIR / "intents"


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_logo_b64_cache: str | None = None

def _logo_img_tag() -> str:
    """
    Return an <img> tag with the logo base64-embedded for self-contained output.
    Reads logo_b64.txt (pre-encoded at deploy time) and caches in module scope.
    Falls back to empty string gracefully if file is absent.
    """
    global _logo_b64_cache
    if _logo_b64_cache is not None:
        return _logo_b64_cache
    logo_path = _TMPL_DIR / "logo_b64.txt"
    if logo_path.exists():
        b64 = logo_path.read_text(encoding="ascii").strip()
        _logo_b64_cache = (
            f'<img src="data:image/png;base64,{b64}" '
            f'class="wl-header-logo" alt="Watchline NYC logo" />'
        )
    else:
        _logo_b64_cache = ""
    return _logo_b64_cache


def _css() -> str:
    return _load(_CSS_FILE)


def _base() -> str:
    return _load(_BASE_HTML)


def _intent_tmpl(name: str) -> str:
    p = _INTENTS / f"{name}.html"
    return _load(p) if p.exists() else _load(_INTENTS / "stub.html")


# ---------------------------------------------------------------------------
# Shared rendering helpers
# ---------------------------------------------------------------------------

def _esc(value) -> str:
    """HTML-escape a value for safe injection into templates."""
    return html.escape(str(value)) if value is not None else "—"


def _verdict_badge(rule_eval: dict | None) -> str:
    if rule_eval is None:
        return ""
    if rule_eval.get("insufficient_data"):
        return (
            '<div class="wl-verdict wl-verdict-insufficient">'
            '⚠ Insufficient data to evaluate rule '
            f'{_esc(rule_eval.get("rule_id", ""))}'
            '</div>'
        )
    deteriorating = rule_eval.get("deteriorating")
    rule_id = _esc(rule_eval.get("rule_id", ""))
    if deteriorating is True:
        return (
            f'<div class="wl-verdict wl-verdict-satisfied">'
            f'✓ Satisfies Rule {rule_id} — Deteriorating'
            f'</div>'
        )
    elif deteriorating is False:
        return (
            f'<div class="wl-verdict wl-verdict-not-satisfied">'
            f'✗ Does not satisfy Rule {rule_id}'
            f'</div>'
        )
    return ""


def _stub_verdict_badge(intent_category: str) -> str:
    return (
        f'<div class="wl-verdict wl-verdict-stub">'
        f'◌ {_esc(intent_category)} — Coming soon'
        f'</div>'
    )


def _highlight_cypher(cypher: str) -> str:
    """Apply simple syntax highlighting to a Cypher string."""
    keywords = (
        r"\b(MATCH|OPTIONAL\s+MATCH|WHERE|WITH|RETURN|ORDER\s+BY|LIMIT|"
        r"UNWIND|CREATE|MERGE|SET|DELETE|DETACH|CALL|YIELD|AS|AND|OR|NOT|"
        r"IN|IS\s+NULL|IS\s+NOT\s+NULL|CASE|WHEN|THEN|ELSE|END|"
        r"count|sum|collect|size|toFloat|toInteger|toString|"
        r"duration|date|toLower|split|DISTINCT|NULL|true|false)\b"
    )
    # Escape HTML first
    cypher = html.escape(cypher)
    # Comments
    cypher = re.sub(
        r"(//.+?)(\n|$)",
        r'<span class="cmt">\1</span>\2',
        cypher,
    )
    # Strings
    cypher = re.sub(
        r"(&#x27;[^&#x27;]*&#x27;|&quot;[^&quot;]*&quot;)",
        r'<span class="str">\1</span>',
        cypher,
    )
    # Keywords
    cypher = re.sub(
        keywords,
        r'<span class="kw">\1</span>',
        cypher,
        flags=re.IGNORECASE,
    )
    return cypher


def _rate_class(rate: float | None) -> str:
    if rate is None:
        return "wl-rate-none"
    if rate >= 0.7:
        return "wl-rate-high"
    if rate >= 0.4:
        return "wl-rate-mid"
    return "wl-rate-low"


def _rate_display(rate: float | None) -> str:
    if rate is None:
        return '<span class="wl-rate-none">—</span>'
    cls = _rate_class(rate)
    return f'<span class="{cls}">{rate:.0%}</span>'


def _years_str(years: list) -> str:
    if not years:
        return "—"
    if len(years) == 1:
        return str(years[0])
    return f"{years[0]}–{years[-1]}"


def _prose_to_html(prose: str) -> str:
    """
    Convert plain prose to HTML paragraphs.
    Also strips common Markdown artifacts in case the LLM ignores instructions.
    """
    # Strip Markdown headings, dividers, blockquotes
    clean = re.sub(r"^#{1,6}\s+", "", prose, flags=re.MULTILINE)
    clean = re.sub(r"^---+$", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"^>\s*", "", clean, flags=re.MULTILINE)
    # Strip bold/italic markers
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = re.sub(r"__(.+?)__", r"\1", clean)
    clean = re.sub(r"_(.+?)_", r"\1", clean)
    # Strip inline code
    clean = re.sub(r"`(.+?)`", r"\1", clean)
    # Convert Markdown bullet lists to inline text with em-dashes
    clean = re.sub(r"^[-*]\s+", "— ", clean, flags=re.MULTILINE)
    # Split into paragraphs and wrap
    paras = [p.strip() for p in clean.strip().split("\n\n") if p.strip()]
    # Join any single-newline breaks within a paragraph
    paras = [" ".join(p.splitlines()) for p in paras]
    return "".join(f"<p>{html.escape(para)}</p>" for para in paras)


# ---------------------------------------------------------------------------
# Intent-specific panel renderers
# ---------------------------------------------------------------------------

def _render_deterioration(tr: dict, prose: str) -> dict:
    """
    Render panel content for DeteriorationTrajectory (DT-001).
    Returns a dict of placeholder -> html_string for injection into base.html.
    """
    raw         = tr.get("raw_results", [{}])
    row0        = raw[0] if raw else {}
    rule_eval   = tr.get("rule_evaluation", {})
    trajectory  = row0.get("annual_trajectory", [])
    cy_issued   = row0.get("current_year_issued", 0)
    cy_over_180 = row0.get("current_year_over_180", 0)

    # Sort trajectory by year
    trajectory = sorted(
        [r for r in trajectory if r is not None],
        key=lambda r: r["year"],
    )

    # --- Trajectory table rows ---
    rows_html = ""
    for r in trajectory:
        rate_html = _rate_display(r.get("resolution_rate"))
        rows_html += (
            f"<tr>"
            f"<td>{r['year']}</td>"
            f"<td>{r.get('issued', '—')}</td>"
            f"<td>{r.get('eligible', '—')}</td>"
            f"<td>{r.get('resolved_of_eligible', '—')}</td>"
            f"<td>{rate_html}</td>"
            f"</tr>"
        )

    # --- Current year block ---
    cy_block = (
        f'<p style="font-size:0.85rem;color:#6b7a99;margin-bottom:1.4rem;">'
        f'<strong>2026 (partial year, early signal only):</strong> '
        f'{cy_issued} Class C violation(s) issued so far; '
        f'{cy_over_180} open more than 180 days. '
        f'This partial year does not contribute to rule evaluation.'
        f'</p>'
    )

    # --- Signal cards ---
    sa = rule_eval.get("signal_a_detail", {})
    sb = rule_eval.get("signal_b_detail", {})

    def _signal_class(satisfied):
        if satisfied is True:  return "satisfied"
        if satisfied is False: return "not-satisfied"
        return "unknown"

    def _signal_verdict(satisfied, label_true, label_false):
        if satisfied is True:  return f"✓ {label_true}"
        if satisfied is False: return f"✗ {label_false}"
        return "⚠ Unable to evaluate"

    sa_class   = _signal_class(rule_eval.get("signal_a_satisfied"))
    sb_class   = _signal_class(rule_eval.get("signal_b_satisfied"))
    sa_verdict = _signal_verdict(
        rule_eval.get("signal_a_satisfied"),
        "Issuance increasing", "Issuance stable or declining"
    )
    sb_verdict = _signal_verdict(
        rule_eval.get("signal_b_satisfied"),
        "Resolution rate declining", "Resolution rate stable or improving"
    )

    # Window years label
    all_years    = [r["year"] for r in trajectory]
    window_label = _years_str(all_years) if all_years else "—"

    # Threshold statement — strip for HTML injection
    threshold = _esc(rule_eval.get("threshold_statement", ""))

    # Load and split template on section markers.
    # Only recognised section names are accepted to guard against stray %% in comments.
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl = _intent_tmpl("deterioration")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{TRAJECTORY_ROWS}}", rows_html)
        .replace("{{CURRENT_YEAR_BLOCK}}", cy_block)
        .replace("{{ADDRESS}}", _esc(row0.get("address")))
        .replace("{{BOROUGH}}", _esc(row0.get("borough")))
        .replace("{{BBL}}", _esc(row0.get("bbl")))
        .replace("{{RESIDENTIAL_UNITS}}", _esc(row0.get("residential_units")))
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}", _esc(rule_eval.get("rule_version", "1.0")))
        .replace("{{WINDOW_YEARS}}", _esc(window_label))
        .replace("{{THRESHOLD_STATEMENT}}", threshold)
        .replace("{{SIGNAL_A_CLASS}}", sa_class)
        .replace("{{SIGNAL_A_VERDICT}}", sa_verdict)
        .replace("{{SIGNAL_A_EARLY_YEARS}}", _esc(_years_str(sa.get("early_years", []))))
        .replace("{{SIGNAL_A_EARLY_VAL}}", _esc(sa.get("early_avg_issued", "—")))
        .replace("{{SIGNAL_A_RECENT_YEARS}}", _esc(_years_str(sa.get("recent_years", []))))
        .replace("{{SIGNAL_A_RECENT_VAL}}", _esc(sa.get("recent_avg_issued", "—")))
        .replace("{{SIGNAL_B_CLASS}}", sb_class)
        .replace("{{SIGNAL_B_VERDICT}}", sb_verdict)
        .replace("{{SIGNAL_B_EARLY_YEARS}}", _esc(_years_str(sb.get("early_years", []))))
        .replace("{{SIGNAL_B_EARLY_VAL}}", _esc(f"{sb['early_avg_rate']:.0%}" if sb.get("early_avg_rate") is not None else "—"))
        .replace("{{SIGNAL_B_RECENT_YEARS}}", _esc(_years_str(sb.get("recent_years", []))))
        .replace("{{SIGNAL_B_RECENT_VAL}}", _esc(f"{sb['recent_avg_rate']:.0%}" if sb.get("recent_avg_rate") is not None else "—"))
        .replace("{{AUTHORITY}}", _esc(rule_eval.get("authority", "Watchline editorial judgment")))
        .replace("{{AUTHOR}}", _esc(rule_eval.get("author", "Watchline NYC project team")))
        .replace("{{EFFECTIVE_DATE}}", _esc(rule_eval.get("effective_date", "")))
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule_eval.get("falsification_conditions", "")))
    )

    # --- Summary panel hero block ---
    rule_eval   = tr.get("rule_evaluation", {}) or {}
    row0        = (tr.get("raw_results") or [{}])[0]

    # Verdict hero
    deteriorating = rule_eval.get("deteriorating")
    insufficient  = rule_eval.get("insufficient_data", False)
    if insufficient:
        hero_class = "wl-hero-unknown"
        hero_icon  = "⚠"
        hero_label = "Insufficient data to evaluate"
        hero_sub   = "Fewer than 3 full calendar years of Class C violation history available."
    elif deteriorating is True:
        hero_class = "wl-hero-deteriorating"
        hero_icon  = "↓"
        hero_label = "Deteriorating"
        hero_sub   = f"Satisfies Rule {_esc(rule_eval.get('rule_id', 'DT-001'))} · Interpretive status: Inferred"
    elif deteriorating is False:
        hero_class = "wl-hero-stable"
        hero_icon  = "✓"
        hero_label = "Not deteriorating"
        hero_sub   = f"Does not satisfy Rule {_esc(rule_eval.get('rule_id', 'DT-001'))} · Interpretive status: Inferred"
    else:
        hero_class = "wl-hero-unknown"
        hero_icon  = "—"
        hero_label = "No rule evaluation"
        hero_sub   = ""

    # Signal pills (only when rule was evaluated)
    signal_pills = ""
    if not insufficient and deteriorating is not None:
        sa = rule_eval.get("signal_a_satisfied")
        sb = rule_eval.get("signal_b_satisfied")
        def _pill(label, satisfied):
            cls = "wl-pill-ok" if satisfied else "wl-pill-fail"
            icon = "✓" if satisfied else "✗"
            return f'<span class="wl-signal-pill {cls}">{icon} {label}</span>'
        signal_pills = (
            f'<div class="wl-signal-pills">'
            f'{_pill("Signal A: Issuance rising", sa)}'
            f'{_pill("Signal B: Resolution declining", sb)}'
            f'</div>'
        )

    # Key facts strip
    address  = _esc(row0.get("address", ""))
    borough  = _esc(row0.get("borough", ""))
    bbl      = _esc(row0.get("bbl", ""))
    units    = _esc(row0.get("residential_units", ""))
    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Address</strong> {address}, {borough}</span>'
        f'<span><strong>BBL</strong> {bbl}</span>'
        f'<span><strong>Units</strong> {units}</span>'
        f'<span><strong>Source</strong> HPD</span>'
        f'</div>'
    )

    hero_html = (
        f'<div class="wl-summary-hero {hero_class}">'
        f'  <div class="wl-hero-icon">{hero_icon}</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{hero_label}</div>'
        f'    <div class="wl-hero-sub">{hero_sub}</div>'
        f'  </div>'
        f'</div>'
        f'{signal_pills}'
        f'{facts}'
    )

    return {
        # Summary panel: verdict hero + key facts + prose
        "SUMMARY_PANEL": (
            hero_html +
            f'<div class="wl-prose">{_prose_to_html(prose)}</div>'
        ),
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL": rules_html,
    }


# Registry: intent_category -> panel renderer function
_PANEL_RENDERERS = {
    "DeteriorationTrajectory": _render_deterioration,
}


# ---------------------------------------------------------------------------
# Stub panel renderer
# ---------------------------------------------------------------------------

def _render_stub(tr: dict, prose: str, intent_category: str) -> dict:
    stub = _intent_tmpl("stub").replace("{{INTENT_LABEL}}", _esc(intent_category))
    parts = stub.split("\n\n")
    return {
        "SUMMARY_PANEL": parts[0] if len(parts) > 0 else stub,
        "EVIDENCE_PANEL": parts[1] if len(parts) > 1 else "",
        "RULES_PANEL": parts[2] if len(parts) > 2 else "",
    }


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_dashboard(state: WatchlineState) -> dict:
    """
    LangGraph node. Assembles the HTML dashboard and stores it in
    state['dashboard_html'].
    """
    tr             = state.get("traversal_results", {})
    prose          = state.get("answer", "")
    intent         = state.get("intent", {})
    intent_cat     = intent.get("intent_category", "General")
    rule_eval      = tr.get("rule_evaluation")
    raw            = tr.get("raw_results", [{}])
    row0           = raw[0] if raw else {}

    # Entity header fields
    address        = row0.get("address") or intent.get("address") or intent.get("actor_name") or "—"
    borough        = row0.get("borough") or intent.get("borough") or ""
    bbl            = row0.get("bbl") or tr.get("params", {}).get("bbl") or ""
    entity_title   = f"{address}, {borough}" if borough else address
    entity_meta    = f"BBL {bbl}" if bbl else ""

    # Intent display label
    intent_labels = {
        "DeteriorationTrajectory":    "Deterioration Trajectory",
        "PortfolioIdentification":    "Portfolio Identification",
        "PortfolioCondition":         "Portfolio Condition",
        "Recidivism":                 "Recidivism",
        "WorstFirst":                 "Worst-First Prioritization",
        "ConcealmentDetection":       "Concealment Detection",
        "EnforcementAccountability":  "Enforcement Accountability",
        "GeographicConcentration":    "Geographic Concentration",
        "OwnershipChange":            "Ownership Change",
        "BuildingDueDiligence":       "Building Due Diligence",
        "RentStabilization":          "Rent Stabilization",
        "FineEvasion":                "Fine Evasion",
        "General":                    "General Query",
    }
    intent_label = intent_labels.get(intent_cat, intent_cat)

    # Dispatch to panel renderer
    is_stub = tr.get("not_supported", False) or intent_cat not in _PANEL_RENDERERS
    if is_stub:
        panels = _render_stub(tr, prose, intent_label)
        verdict_html = _stub_verdict_badge(intent_label)
    else:
        renderer = _PANEL_RENDERERS[intent_cat]
        panels   = renderer(tr, prose)
        verdict_html = _verdict_badge(rule_eval)

    # Handler owns the Cypher — retrieve it for the Query tab
    handler = tr.get("handler")
    cypher  = handler.get_cypher() if handler and hasattr(handler, "get_cypher") else ""
    params  = tr.get("params", {})

    # Assemble the full dashboard from base template
    dashboard = (
        _base()
        .replace("{{INJECTED_CSS}}",     _css())
        .replace("{{DASHBOARD_TITLE}}",  _esc(entity_title))
        .replace("{{LOGO_IMG}}",         _logo_img_tag())
        .replace("{{INTENT_LABEL}}",     _esc(intent_label))
        .replace("{{ENTITY_TITLE}}",     _esc(entity_title))
        .replace("{{ENTITY_META}}",      _esc(entity_meta))
        .replace("{{VERDICT_BADGE}}",    verdict_html)
        .replace("{{SUMMARY_PANEL}}",    panels.get("SUMMARY_PANEL", ""))
        .replace("{{EVIDENCE_PANEL}}",   panels.get("EVIDENCE_PANEL", ""))
        .replace("{{RULES_PANEL}}",      panels.get("RULES_PANEL", ""))
        .replace("{{CYPHER_HIGHLIGHTED}}", _highlight_cypher(cypher) if cypher else "— no query recorded —")
        .replace("{{TRAVERSAL_TYPE}}",   _esc(tr.get("traversal_type", "—")))
        .replace("{{QUERY_PARAMS}}",     _esc(json.dumps(params)))
        .replace("{{RECORD_COUNT}}",     _esc(len(raw)))
    )

    return {"dashboard_html": dashboard}
