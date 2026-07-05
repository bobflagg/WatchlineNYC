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


def _render_portfolio_identification(tr: dict, prose: str) -> dict:
    """
    Render panel content for PortfolioIdentification (PBC-001 / RUL-00002).
    Returns a dict of placeholder -> html_string for injection into base.html.
    """
    import re as _re
    from watchline.fw.intents.portfolio_identification import _load_rule_from_graph

    raw  = tr.get("raw_results", [])
    rule = _load_rule_from_graph()

    def _parse_claim(claim_text: str) -> dict:
        """Extract structured fields from the PBC claim_text."""
        if not claim_text:
            return {}
        portfolio = _re.search(r"These (\d+) properties", claim_text)
        addr_conn = _re.search(r"(\d+) shared business address connection", claim_text)
        name_conn = _re.search(r"(\d+) shared name connection", claim_text)
        confidence = _re.search(r"confidence of this grouping is (\w+)", claim_text)
        return {
            "portfolio_size":      int(portfolio.group(1))  if portfolio  else None,
            "address_connections": int(addr_conn.group(1))  if addr_conn  else None,
            "name_connections":    int(name_conn.group(1))  if name_conn  else None,
            "confidence":          confidence.group(1)       if confidence else None,
        }

    def _confidence_pill(conf: str | None) -> str:
        cls = {
            "High":   "wl-status-observed",
            "Medium": "wl-status-stipulated",
            "Low":    "wl-status-disputed",
        }.get(conf or "", "wl-status-inferred")
        return f'<span class="wl-status-pill {cls}">{_esc(conf or "Unknown")}</span>'

    # De-duplicate by canonical_id — one card per distinct controller
    seen: set = set()
    controllers = []
    for row in raw:
        cid = row.get("controller_id")
        if cid not in seen:
            seen.add(cid)
            controllers.append(row)

    row0 = raw[0] if raw else {}
    building_has_phc = any(r.get("building_has_phc") for r in raw)

    # --- Controller cards (Evidence tab) ---
    cards_html = ""
    claim_text_blocks = ""
    for ctrl in controllers:
        parsed      = _parse_claim(ctrl.get("pbc_claim", ""))
        conf        = parsed.get("confidence")
        portfolio   = parsed.get("portfolio_size")
        addr_c      = parsed.get("address_connections")
        name_c      = parsed.get("name_connections")

        portfolio_str  = f"{portfolio} properties" if portfolio is not None else "—"
        connections_str = (
            f"{addr_c} address-based, {name_c} name-based"
            if addr_c is not None else "—"
        )

        cards_html += (
            f'<div class="wl-signal-card satisfied" style="margin-bottom:1rem;">'
            f'  <div class="wl-signal-label">{_esc(ctrl.get("controller_name", "Unknown"))}</div>'
            f'  <div class="wl-meta-row" style="margin-top:0.6rem;">'
            f'    <span class="wl-meta-key">Actor ID</span>'
            f'    <span class="wl-meta-val" style="font-family:monospace;font-size:0.8rem;">'
            f'      {_esc(ctrl.get("controller_id", "—"))}'
            f'    </span>'
            f'  </div>'
            f'  <div class="wl-meta-row">'
            f'    <span class="wl-meta-key">Type</span>'
            f'    <span class="wl-meta-val">{_esc(ctrl.get("actor_type", "—"))}</span>'
            f'  </div>'
            f'  <div class="wl-meta-row">'
            f'    <span class="wl-meta-key">Portfolio size</span>'
            f'    <span class="wl-meta-val">{_esc(portfolio_str)}</span>'
            f'  </div>'
            f'  <div class="wl-meta-row">'
            f'    <span class="wl-meta-key">Connections</span>'
            f'    <span class="wl-meta-val">{_esc(connections_str)}</span>'
            f'  </div>'
            f'  <div class="wl-meta-row">'
            f'    <span class="wl-meta-key">Confidence</span>'
            f'    <span class="wl-meta-val">{_confidence_pill(conf)}</span>'
            f'  </div>'
            f'  <div class="wl-meta-row">'
            f'    <span class="wl-meta-key">Interpretive status</span>'
            f'    <span class="wl-meta-val">'
            f'      <span class="wl-status-pill wl-status-inferred">Inferred</span>'
            f'    </span>'
            f'  </div>'
            f'</div>'
        )

        if ctrl.get("pbc_claim"):
            claim_text_blocks += (
                f'<div class="wl-threshold" style="margin-bottom:0.8rem;">'
                f'{_esc(ctrl["pbc_claim"])}'
                f'</div>'
            )

    if not cards_html:
        cards_html = (
            '<p style="color:#555;">No beneficial controller identified in the '
            'graph for this building.</p>'
        )

    phc_flag_html = (
        '<span class="wl-status-pill wl-status-disputed">'
        'Yes — Persistent Hazardous Conditions flagged</span>'
        if building_has_phc else
        '<span class="wl-status-pill wl-status-observed">No PHC flag</span>'
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl = _intent_tmpl("portfolio_identification")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{CONTROLLER_CARDS}}",  cards_html)
        .replace("{{ADDRESS}}",           _esc(row0.get("address")))
        .replace("{{BOROUGH}}",           _esc(row0.get("borough")))
        .replace("{{BBL}}",               _esc(row0.get("bbl")))
        .replace("{{RESIDENTIAL_UNITS}}", _esc(row0.get("residential_units")))
        .replace("{{PHC_FLAG}}",          phc_flag_html)
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}",          _esc(rule.get("version", "1.0")))
        .replace("{{AUTHORITY}}",             _esc(rule.get("authority", "")))
        .replace("{{AUTHOR}}",                _esc(rule.get("author", "")))
        .replace("{{EFFECTIVE_DATE}}",        _esc(rule.get("effective_date", "")))
        .replace("{{THRESHOLD_STATEMENT}}",   _esc(rule.get("threshold_description", "")))
        .replace("{{CLAIM_TEXT_BLOCKS}}",     claim_text_blocks)
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule.get("falsification_conditions", "")))
    )

    # --- Summary panel hero ---
    if controllers:
        if len(controllers) == 1:
            hero_label = _esc(controllers[0].get("controller_name", "Unknown"))
        else:
            names = ", ".join(_esc(c.get("controller_name", "Unknown")) for c in controllers)
            hero_label = f"Multiple controllers: {names}"

        first_parsed = _parse_claim(controllers[0].get("pbc_claim", ""))
        portfolio_n  = first_parsed.get("portfolio_size")
        conf_label   = first_parsed.get("confidence", "—")
        hero_sub = (
            f"Portfolio: {portfolio_n} properties · "
            f"Confidence: {conf_label} · "
            f"Interpretive status: Inferred · "
            f"Rule PBC-001"
        )
        hero_class = "wl-hero-identified"
        hero_icon  = "→"
    else:
        hero_label = "No controller identified"
        hero_sub   = "No BeneficialControl relationship found for this building."
        hero_class = "wl-hero-unknown"
        hero_icon  = "?"

    phc_pill = (
        '<span class="wl-signal-pill wl-pill-fail">PHC flagged</span>'
        if building_has_phc else ""
    )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Address</strong> {_esc(row0.get("address", ""))}, '
        f'{_esc(row0.get("borough", ""))}</span>'
        f'<span><strong>BBL</strong> {_esc(row0.get("bbl", ""))}</span>'
        f'<span><strong>Units</strong> {_esc(row0.get("residential_units", ""))}</span>'
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
        f'<div class="wl-signal-pills">{phc_pill}</div>'
        f'{facts}'
    )

    return {
        "SUMMARY_PANEL": hero_html + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_building_due_diligence(tr: dict, prose: str) -> dict:
    """
    Render panel content for BuildingDueDiligence (data retrieval, no rule).
    """
    raw  = tr.get("raw_results", [{}])
    row0 = raw[0] if raw else {}

    open_c       = row0.get("open_c", 0) or 0
    open_b       = row0.get("open_b", 0) or 0
    open_a       = row0.get("open_a", 0) or 0
    total_viol   = row0.get("total_violations", 0) or 0
    total_fil    = row0.get("total_filings", 0) or 0
    open_fil     = row0.get("open_filings", 0) or 0
    harassment   = row0.get("harassment_findings", 0) or 0
    total_ecb    = row0.get("total_ecb", 0) or 0
    balance_due  = row0.get("total_balance_due", 0.0) or 0.0
    has_phc      = row0.get("has_phc", False)
    phc_claim    = row0.get("phc_claim") or ""
    controllers  = row0.get("controllers") or []

    def _stat_card(label: str, value, danger: bool = False) -> str:
        color    = "#991b1b" if danger else "#0a1629"
        bg       = "#fef2f2" if danger else "#f8f9fb"
        border   = "#fca5a5" if danger else "#dde3ee"
        return (
            f'<div style="background:{bg};border:1.5px solid {border};'
            f'border-radius:6px;padding:0.9rem 1rem;">'
            f'  <div style="font-size:1.55rem;font-weight:700;color:{color};'
            f'font-family:\'Fraunces\',serif;">{_esc(value)}</div>'
            f'  <div style="font-size:0.75rem;color:#6b7a99;margin-top:0.2rem;'
            f'text-transform:uppercase;letter-spacing:0.06em;">{_esc(label)}</div>'
            f'</div>'
        )

    violation_cards = (
        _stat_card("Open Class C", open_c, danger=open_c > 0) +
        _stat_card("Open Class B", open_b, danger=open_b > 0) +
        _stat_card("Open Class A", open_a) +
        _stat_card("Total HPD violations", total_viol) +
        _stat_card("PHC flagged",
                   "Yes" if has_phc else "No", danger=has_phc) +
        _stat_card("Rent-stabilized units", row0.get("rs_units_current", "—"))
    )

    enforcement_cards = (
        _stat_card("Court filings (total)", total_fil) +
        _stat_card("Open filings", open_fil, danger=open_fil > 0) +
        _stat_card("Harassment findings", harassment, danger=harassment > 0) +
        _stat_card("ECB judgments", total_ecb) +
        _stat_card("ECB balance due",
                   f"${balance_due:,.0f}", danger=balance_due > 0)
    )

    # Controller list
    ctrl_names = ", ".join(
        c.get("name", "—") for c in controllers if c.get("name")
    ) or "Not identified"

    # PHC claim block for Rules tab
    phc_block = ""
    if phc_claim:
        phc_block = (
            f'<div class="wl-section-head">PHC-001 Claim (verbatim)</div>'
            f'<div class="wl-threshold">{_esc(phc_claim)}</div>'
        )

    # Load and split template
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("building_due_diligence")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{VIOLATION_CARDS}}",   violation_cards)
        .replace("{{ENFORCEMENT_CARDS}}", enforcement_cards)
        .replace("{{ADDRESS}}",           _esc(row0.get("address")))
        .replace("{{BOROUGH}}",           _esc(row0.get("borough")))
        .replace("{{BBL}}",               _esc(row0.get("bbl")))
        .replace("{{YEAR_BUILT}}",        _esc(row0.get("year_built")))
        .replace("{{BUILDING_CLASS}}",    _esc(row0.get("building_class")))
        .replace("{{RESIDENTIAL_UNITS}}", _esc(row0.get("residential_units")))
        .replace("{{RS_UNITS}}",          _esc(row0.get("rs_units_current")))
        .replace("{{RS_DEREGULATING}}",   "Yes" if row0.get("rs_deregulating") else "No")
        .replace("{{CONTROLLERS}}",       _esc(ctrl_names))
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{PHC_CLAIM_BLOCK}}", phc_block)
    )

    # Summary hero
    phc_pill = (
        '<span class="wl-signal-pill wl-pill-fail">PHC flagged</span>'
        if has_phc else ""
    )
    deregulating_pill = (
        '<span class="wl-signal-pill wl-pill-fail">Deregulating</span>'
        if row0.get("rs_deregulating") else ""
    )
    pills_html = ""
    if phc_pill or deregulating_pill:
        pills_html = (
            f'<div class="wl-signal-pills">{phc_pill}{deregulating_pill}</div>'
        )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Address</strong> {_esc(row0.get("address", ""))}, '
        f'{_esc(row0.get("borough", ""))}</span>'
        f'<span><strong>BBL</strong> {_esc(row0.get("bbl", ""))}</span>'
        f'<span><strong>Units</strong> {_esc(row0.get("residential_units", ""))}</span>'
        f'<span><strong>Built</strong> {_esc(row0.get("year_built", ""))}</span>'
        f'</div>'
    )

    hero_sub = (
        f'Open C: {open_c} · Open B: {open_b} · '
        f'Court filings: {total_fil} · '
        f'ECB balance: ${balance_due:,.0f}'
    )
    hero_html = (
        f'<div class="wl-summary-hero wl-hero-identified">'
        f'  <div class="wl-hero-icon">◎</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{_esc(row0.get("address", "—"))}</div>'
        f'    <div class="wl-hero-sub">{_esc(hero_sub)}</div>'
        f'  </div>'
        f'</div>'
        f'{pills_html}'
        f'{facts}'
    )

    return {
        "SUMMARY_PANEL": hero_html + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_network_exposure(tr: dict, prose: str) -> dict:
    """
    Render panel content for NetworkExposure (NE-001 / RUL-00008).
    """
    from watchline.fw.intents.network_exposure import _load_rule_from_graph

    raw       = tr.get("raw_results", [])
    rule_eval = tr.get("rule_evaluation") or {}
    rule      = _load_rule_from_graph()

    combined_portfolio = rule_eval.get("combined_portfolio", 0)
    combined_phc       = rule_eval.get("combined_phc", 0)
    combined_units     = rule_eval.get("combined_units", 0)
    combined_phc_rate  = rule_eval.get("combined_phc_rate", 0.0)
    affiliation_basis  = rule_eval.get("affiliation_basis", "")
    network_size       = rule_eval.get("network_size", len(raw))
    insufficient       = rule_eval.get("insufficient_data", False)

    # --- Actor table rows ---
    rows_html = ""
    for r in raw:
        size     = r.get("portfolio_size", 0) or 0
        phc      = r.get("phc_buildings", 0)  or 0
        units    = r.get("total_units", 0)     or 0
        phc_rate = round(phc / size, 3) if size > 0 else 0.0
        role     = "Named actor" if r.get("is_named_actor") else "Affiliated actor"
        rows_html += (
            f"<tr>"
            f"<td><strong>{_esc(r.get('actor_name', '—'))}</strong></td>"
            f"<td>{_esc(role)}</td>"
            f"<td>{size:,}</td>"
            f"<td>{phc}</td>"
            f"<td>{_rate_display(phc_rate)}</td>"
            f"<td>{units:,}</td>"
            f"</tr>"
        )

    combined_rate_html = _rate_display(combined_phc_rate)
    combined_row = (
        f'<tr style="font-weight:600;background:#f0f4fa;">'
        f'<td colspan="2">Combined network</td>'
        f'<td>{combined_portfolio:,}</td>'
        f'<td>{combined_phc}</td>'
        f'<td>{combined_rate_html}</td>'
        f'<td>{combined_units:,}</td>'
        f'</tr>'
    ) if not insufficient else ""

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("network_exposure")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{ACTOR_ROWS}}",       rows_html)
        .replace("{{COMBINED_ROW}}",     combined_row)
        .replace("{{AFFILIATION_BASIS}}", _esc(affiliation_basis))
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}",             _esc(rule.get("version", "1.0")))
        .replace("{{AUTHORITY}}",                _esc(rule.get("authority", "")))
        .replace("{{AUTHOR}}",                   _esc(rule.get("author", "")))
        .replace("{{EFFECTIVE_DATE}}",           _esc(rule.get("effective_date", "")))
        .replace("{{THRESHOLD_STATEMENT}}",      _esc(rule.get("threshold_description", "")))
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule.get("falsification_conditions", "")))
    )

    # --- Summary hero ---
    named_row  = next((r for r in raw if r.get("is_named_actor")), raw[0] if raw else {})
    named_name = _esc(named_row.get("actor_name", "—"))

    if insufficient:
        hero_class = "wl-hero-unknown"
        hero_icon  = "⚠"
        hero_label = "No affiliated network found"
        hero_sub   = "No ProbableAffiliation relationships found for this actor."
        verdict_pills = ""
    else:
        hero_class = "wl-hero-identified"
        hero_icon  = "⬡"
        hero_label = f"{named_name} — {network_size}-actor network"
        hero_sub   = (
            f"Combined portfolio: {combined_portfolio:,} buildings · "
            f"{combined_phc} PHC ({combined_phc_rate:.0%}) · "
            f"{combined_units:,} units · Rule NE-001 · Confidence: Medium"
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'{combined_phc} PHC buildings ({combined_phc_rate:.0%})</span>'
            f'<span class="wl-signal-pill" style="background:#e8f0fe;color:#1a4aab;'
            f'border:1px solid #4a7aba;">NE-001 · Inferred · Medium confidence</span>'
            f'</div>'
        )

    actor_names = " · ".join(
        _esc(r.get("actor_name", "")) for r in raw
    )
    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Actors</strong> {actor_names}</span>'
        f'<span><strong>Buildings</strong> {combined_portfolio:,}</span>'
        f'<span><strong>Units</strong> {combined_units:,}</span>'
        f'<span><strong>Source</strong> HPD</span>'
        f'</div>'
    ) if not insufficient else ""

    hero_html = (
        f'<div class="wl-summary-hero {hero_class}">'
        f'  <div class="wl-hero-icon">{hero_icon}</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{hero_label}</div>'
        f'    <div class="wl-hero-sub">{hero_sub}</div>'
        f'  </div>'
        f'</div>'
        f'{verdict_pills}'
        f'{facts}'
    )

    return {
        "SUMMARY_PANEL":  hero_html + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


# Registry: intent_category -> panel renderer function
_PANEL_RENDERERS = {
    "DeteriorationTrajectory":  _render_deterioration,
    "PortfolioIdentification":  _render_portfolio_identification,
    "BuildingDueDiligence":     _render_building_due_diligence,
    "NetworkExposure":          _render_network_exposure,
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
