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


def _render_rent_stabilization(tr: dict, prose: str) -> dict:
    """
    Render panel content for RentStabilization (RS-001 / RUL-00010).
    """
    from watchline.fw.intents.rent_stabilization import (
        _load_rule_from_graph, _RS_YEAR_FIELDS,
    )

    raw       = tr.get("raw_results", [{}])
    row0      = raw[0] if raw else {}
    rule_eval = tr.get("rule_evaluation") or {}
    rule      = _load_rule_from_graph()

    deregulating    = rule_eval.get("deregulating")
    insufficient    = rule_eval.get("insufficient_data", False)
    no_rs_history   = rule_eval.get("no_rs_history", False)
    units_lost      = rule_eval.get("units_lost", 0) or 0
    pct_lost        = rule_eval.get("pct_lost")
    rs_change       = rule_eval.get("rs_change")
    earliest_year   = rule_eval.get("earliest_year", "—")
    latest_year     = rule_eval.get("latest_year", "—")

    # --- Year-by-year table rows with trend arrows ---
    year_data = [
        (yr, int(row0[key]))
        for yr, key in _RS_YEAR_FIELDS
        if row0.get(key) is not None
    ]
    rs_current_val = row0.get("rs_current")
    if rs_current_val is not None:
        int_current = int(rs_current_val)
        if not year_data or year_data[-1][1] != int_current:
            year_data.append(("Current", int_current))

    rows_html = ""
    for i, (yr, count) in enumerate(year_data):
        if i == 0:
            trend_html = '<span style="color:#6b7a99;">—</span>'
        else:
            diff = count - year_data[i - 1][1]
            if diff > 0:
                trend_html = f'<span style="color:#166534;">↑ +{diff}</span>'
            elif diff < 0:
                trend_html = f'<span style="color:#991b1b;">↓ {diff}</span>'
            else:
                trend_html = '<span style="color:#6b7a99;">→ 0</span>'
        rows_html += (
            f"<tr>"
            f"<td>{_esc(yr)}</td>"
            f"<td>{count:,}</td>"
            f"<td>{trend_html}</td>"
            f"</tr>"
        )

    if not rows_html:
        rows_html = '<tr><td colspan="3" style="color:#6b7a99;">No DHCR rent-stabilization data found for this building.</td></tr>'

    # --- Summary stats block ---
    if not no_rs_history and units_lost > 0:
        pct_str = f" ({pct_lost:.1f}% of earliest registered count)" if pct_lost is not None else ""
        rs_summary_block = (
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.8rem;'
            f'margin:1rem 0 1.4rem;">'
            + _stat_mini("Units lost", f"{units_lost:,}")
            + _stat_mini("Percent lost", f"{pct_lost:.1f}%" if pct_lost is not None else "—",
                         danger=units_lost > 0)
            + _stat_mini("DHCR deregulating flag",
                         "Yes" if rule_eval.get("rs_deregulating") else "No",
                         danger=bool(rule_eval.get("rs_deregulating")))
            + _stat_mini("Net change", _esc(rs_change) if rs_change is not None else "—",
                         danger=rs_change is not None and rs_change < 0)
            + f'</div>'
        )
    elif no_rs_history:
        rs_summary_block = (
            '<p style="color:#6b7a99;font-size:0.9rem;margin:1rem 0;">'
            'This building has no DHCR rent-stabilization registration history.</p>'
        )
    else:
        rs_summary_block = (
            '<p style="color:#6b7a99;font-size:0.9rem;margin:1rem 0;">'
            'No rent-stabilized units have been lost over the available data window.</p>'
        )

    # --- DHCR Statement of Account link ---
    pdfsoa_url = row0.get("pdfsoa_url")
    pdfsoa_block = ""
    if pdfsoa_url:
        pdfsoa_block = (
            f'<div style="margin:0 0 1.2rem;">'
            f'<span style="font-size:0.8rem;text-transform:uppercase;'
            f'letter-spacing:0.06em;color:#6b7a99;">Primary source &nbsp;</span>'
            f'<a href="{_esc(pdfsoa_url)}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#1a4aab;font-size:0.9rem;">'
            f'2023 DHCR Statement of Account (PDF)</a>'
            f'</div>'
        )

    # --- Signal card helpers ---
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
        "Unit count has declined", "Unit count stable or increasing",
    )
    sb_verdict = _signal_verdict(
        rule_eval.get("signal_b_satisfied"),
        "DHCR deregistration flag set", "DHCR deregistration flag not set",
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("rent_stabilization")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{RS_YEAR_ROWS}}",    rows_html)
        .replace("{{RS_SUMMARY_BLOCK}}", rs_summary_block)
        .replace("{{PDFSOA_LINK}}",     pdfsoa_block)
        .replace("{{ADDRESS}}",         _esc(row0.get("address")))
        .replace("{{BOROUGH}}",         _esc(row0.get("borough")))
        .replace("{{BBL}}",             _esc(row0.get("bbl")))
        .replace("{{RESIDENTIAL_UNITS}}", _esc(row0.get("residential_units")))
        .replace("{{RS_CURRENT}}",      _esc(row0.get("rs_current")))
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}",             _esc(rule.get("version", "1.0")))
        .replace("{{EARLIEST_YEAR}}",            _esc(earliest_year))
        .replace("{{LATEST_YEAR}}",              _esc(latest_year))
        .replace("{{AUTHORITY}}",                _esc(rule.get("authority", "")))
        .replace("{{AUTHOR}}",                   _esc(rule.get("author", "")))
        .replace("{{EFFECTIVE_DATE}}",           _esc(rule.get("effective_date", "")))
        .replace("{{THRESHOLD_STATEMENT}}",      _esc(rule.get("threshold_description", "")))
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule.get("falsification_conditions", "")))
        .replace("{{SIGNAL_A_CLASS}}",  sa_class)
        .replace("{{SIGNAL_A_VERDICT}}", sa_verdict)
        .replace("{{RS_CHANGE}}",        _esc(rs_change) if rs_change is not None else "—")
        .replace("{{SIGNAL_B_CLASS}}",  sb_class)
        .replace("{{SIGNAL_B_VERDICT}}", sb_verdict)
        .replace("{{DEREGULATING_FLAG}}", "Yes" if rule_eval.get("rs_deregulating") else "No")
    )

    # --- Summary hero ---
    if no_rs_history or insufficient:
        hero_class = "wl-hero-unknown"
        hero_icon  = "—"
        hero_label = "No rent-stabilized history"
        hero_sub   = "This building has no DHCR rent-stabilization registration data."
        verdict_pills = ""
    elif deregulating is True:
        hero_class = "wl-hero-deteriorating"
        hero_icon  = "↓"
        hero_label = "Deregulating"
        hero_sub   = (
            f"Lost {units_lost:,} RS units"
            + (f" ({pct_lost:.1f}%)" if pct_lost is not None else "")
            + f" · DHCR deregistration active"
            + f" · Rule RS-001 · Interpretive status: Inferred"
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">↓ {units_lost:,} RS units lost</span>'
            f'<span class="wl-signal-pill wl-pill-fail">DHCR deregistration active</span>'
            f'</div>'
        )
    elif rule_eval.get("signal_a_satisfied") and not rule_eval.get("signal_b_satisfied"):
        hero_class = "wl-hero-unknown"
        hero_icon  = "⚠"
        hero_label = "Unit decline — no deregistration signal"
        hero_sub   = (
            f"Lost {units_lost:,} RS units but DHCR deregistration flag is not set. "
            f"Does not satisfy Rule RS-001."
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">↓ {units_lost:,} RS units lost</span>'
            f'<span class="wl-signal-pill wl-pill-ok">No deregistration flag</span>'
            f'</div>'
        )
    else:
        hero_class = "wl-hero-stable"
        hero_icon  = "✓"
        hero_label = "No deregulation signal"
        hero_sub   = "Unit count stable or increasing. Does not satisfy Rule RS-001."
        verdict_pills = ""

    rs_current_display = _esc(row0.get("rs_current", "—"))
    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Address</strong> {_esc(row0.get("address", ""))}, '
        f'{_esc(row0.get("borough", ""))}</span>'
        f'<span><strong>BBL</strong> {_esc(row0.get("bbl", ""))}</span>'
        f'<span><strong>Residential units</strong> {_esc(row0.get("residential_units", ""))}</span>'
        f'<span><strong>RS units (current)</strong> {rs_current_display}</span>'
        f'</div>'
    )

    hero_html = (
        f'<div class="wl-summary-hero {hero_class}">'
        f'  <div class="wl-hero-icon">{hero_icon}</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{hero_label}</div>'
        f'    <div class="wl-hero-sub">{_esc(hero_sub)}</div>'
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


def _stat_mini(label: str, value, danger: bool = False) -> str:
    """Compact stat card for use in grid layouts."""
    color  = "#991b1b" if danger else "#0a1629"
    bg     = "#fef2f2" if danger else "#f8f9fb"
    border = "#fca5a5" if danger else "#dde3ee"
    return (
        f'<div style="background:{bg};border:1.5px solid {border};'
        f'border-radius:6px;padding:0.7rem 0.9rem;">'
        f'  <div style="font-size:1.2rem;font-weight:700;color:{color};'
        f'font-family:\'Fraunces\',serif;">{value}</div>'
        f'  <div style="font-size:0.73rem;color:#6b7a99;margin-top:0.2rem;'
        f'text-transform:uppercase;letter-spacing:0.06em;">{_esc(label)}</div>'
        f'</div>'
    )


def _render_worst_first(tr: dict, prose: str) -> dict:
    """
    Render panel content for WorstFirst (dataset-level ranking, no rule).
    """
    raw = tr.get("raw_results", [])

    # --- Ranked table rows ---
    rows_html = ""
    for rank, r in enumerate(raw, start=1):
        name          = r.get("name") or "—"
        portfolio     = int(r.get("portfolio_size") or 0)
        phc           = int(r.get("phc_count") or 0)
        units         = int(r.get("total_units") or 0)
        phc_rate      = float(r.get("phc_rate") or 0.0)
        rate_html     = _rate_display(phc_rate)
        rank_style    = ' style="font-weight:700;color:#0a1629;"' if rank <= 3 else ""
        rows_html += (
            f"<tr>"
            f"<td{rank_style}>{rank}</td>"
            f"<td{rank_style}>{_esc(name)}</td>"
            f"<td>{portfolio:,}</td>"
            f"<td><strong>{phc:,}</strong></td>"
            f"<td>{rate_html}</td>"
            f"<td>{units:,}</td>"
            f"</tr>"
        )

    if not rows_html:
        rows_html = '<tr><td colspan="6" style="color:#6b7a99;">No results returned.</td></tr>'

    # --- Aggregate summary block ---
    total_phc      = sum(int(r.get("phc_count") or 0) for r in raw)
    total_portfolio = sum(int(r.get("portfolio_size") or 0) for r in raw)
    total_units    = sum(int(r.get("total_units") or 0) for r in raw)

    aggregate_block = (
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);'
        f'gap:0.8rem;margin-top:1.2rem;">'
        + _stat_mini("Landlords ranked", str(len(raw)))
        + _stat_mini("Combined PHC buildings", f"{total_phc:,}", danger=True)
        + _stat_mini("Combined portfolio buildings", f"{total_portfolio:,}")
        + f'</div>'
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("worst_first")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{RANKING_ROWS}}",    rows_html)
        .replace("{{AGGREGATE_BLOCK}}", aggregate_block)
    )

    rules_html = tmpl_map.get("RULES", "")

    # --- Summary hero ---
    top = raw[0] if raw else {}
    top_name = _esc(top.get("name", "—"))
    top_phc  = int(top.get("phc_count") or 0)
    top_port = int(top.get("portfolio_size") or 0)
    top_rate = float(top.get("phc_rate") or 0.0)

    hero_html = (
        f'<div class="wl-summary-hero wl-hero-deteriorating">'
        f'  <div class="wl-hero-icon">↓</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">#{1} {top_name}</div>'
        f'    <div class="wl-hero-sub">'
        f'      {top_phc} PHC buildings of {top_port} ({top_rate:.0%} rate) · '
        f'      {len(raw)} landlords ranked · PHC-001 · Inferred'
        f'    </div>'
        f'  </div>'
        f'</div>'
        f'<div class="wl-signal-pills">'
        f'  <span class="wl-signal-pill wl-pill-fail">'
        f'  {total_phc:,} combined PHC buildings in top {len(raw)}</span>'
        f'</div>'
        f'<div class="wl-facts-strip">'
        f'<span><strong>Ranked</strong> {len(raw)} landlords</span>'
        f'<span><strong>Combined PHC</strong> {total_phc:,} buildings</span>'
        f'<span><strong>Combined portfolio</strong> {total_portfolio:,} buildings</span>'
        f'<span><strong>Source</strong> HPD via Watchline</span>'
        f'</div>'
    )

    return {
        "SUMMARY_PANEL":  hero_html + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_portfolio_condition(tr: dict, prose: str) -> dict:
    """
    Render panel content for PortfolioCondition (PHC-001 aggregated).
    """
    from watchline.fw.intents.portfolio_condition import _load_phc_rule_from_graph

    raw       = tr.get("raw_results", [{}])
    row0      = raw[0] if raw else {}
    rule_eval = tr.get("rule_evaluation") or {}
    rule      = _load_phc_rule_from_graph()

    actor_name     = row0.get("name", "—")
    canonical_id   = row0.get("canonical_id", "—")
    portfolio_size = rule_eval.get("portfolio_size", 0) or 0
    phc_buildings  = rule_eval.get("phc_buildings", 0) or 0
    phc_rate       = rule_eval.get("phc_rate", 0.0) or 0.0
    high_phc_rate  = rule_eval.get("high_phc_rate", False)
    pbc_claim      = row0.get("pbc_claim") or ""

    non_phc = portfolio_size - phc_buildings

    # --- Summary stat cards ---
    summary_cards = (
        _stat_mini("Portfolio size", f"{portfolio_size:,}")
        + _stat_mini("PHC buildings", f"{phc_buildings:,}", danger=phc_buildings > 0)
        + _stat_mini("Non-PHC buildings", f"{non_phc:,}")
        + _stat_mini("PHC rate", f"{phc_rate:.0%}", danger=high_phc_rate)
        + _stat_mini("High-PHC flag (≥50%)",
                     "Yes" if high_phc_rate else "No", danger=high_phc_rate)
        + _stat_mini("Rule applied", "PHC-001")
    )

    # --- PBC claim block ---
    pbc_claim_block = ""
    if pbc_claim:
        pbc_claim_block = (
            f'<div class="wl-section-head">Probable Beneficial Control Claim (verbatim)</div>'
            f'<div class="wl-threshold" style="margin-bottom:1.4rem;">'
            f'{_esc(pbc_claim)}</div>'
        )

    # --- PHC buildings table ---
    raw_list = row0.get("phc_building_list") or []
    phc_list = sorted(
        [b for b in raw_list if b is not None],
        key=lambda b: (b.get("borough") or "", b.get("address") or ""),
    )

    phc_table = ""
    if phc_list:
        rows_html = ""
        for b in phc_list:
            rows_html += (
                f"<tr>"
                f"<td>{_esc(b.get('address', '—'))}</td>"
                f"<td>{_esc(b.get('borough', '—'))}</td>"
                f"<td>{_esc(b.get('units', '—'))}</td>"
                f"<td><span class='wl-status-pill wl-status-disputed'"
                f" style='font-size:0.72rem;'>PHC</span></td>"
                f"</tr>"
            )
        overflow_note = ""
        if len(phc_list) > len(phc_list):  # placeholder; list is always full
            overflow_note = ""
        phc_table = (
            f'<div class="wl-section-head">'
            f'Buildings with Persistent Hazardous Conditions ({len(phc_list)})</div>'
            f'<table class="wl-table">'
            f'<thead><tr>'
            f'<th>Address</th><th>Borough</th><th>Units</th><th>PHC status</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>'
        )
    elif portfolio_size > 0:
        phc_table = (
            '<div class="wl-section-head">PHC Buildings</div>'
            '<p style="color:#166534;font-size:0.9rem;margin:0.5rem 0 1.4rem;">'
            'No buildings in this portfolio have been flagged for Persistent '
            'Hazardous Conditions.</p>'
        )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("portfolio_condition")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{SUMMARY_CARDS}}",   summary_cards)
        .replace("{{PBC_CLAIM_BLOCK}}", pbc_claim_block)
        .replace("{{PHC_TABLE}}",       phc_table)
        .replace("{{ACTOR_NAME}}",      _esc(actor_name))
        .replace("{{CANONICAL_ID}}",    _esc(canonical_id))
    )

    high_phc_label = (
        '<span class="wl-status-pill wl-status-disputed">Yes — high PHC rate</span>'
        if high_phc_rate else
        '<span class="wl-status-pill wl-status-observed">No</span>'
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}",             _esc(rule.get("version", "1.0")))
        .replace("{{AUTHORITY}}",                _esc(rule.get("authority", "")))
        .replace("{{AUTHOR}}",                   _esc(rule.get("author", "")))
        .replace("{{EFFECTIVE_DATE}}",           _esc(rule.get("effective_date", "")))
        .replace("{{THRESHOLD_STATEMENT}}",      _esc(rule.get("threshold_description", "")))
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule.get("falsification_conditions", "")))
        .replace("{{PHC_BUILDINGS}}",    str(phc_buildings))
        .replace("{{PORTFOLIO_SIZE}}",   str(portfolio_size))
        .replace("{{PHC_RATE_DISPLAY}}", f"{phc_rate:.0%}")
        .replace("{{HIGH_PHC_LABEL}}",   high_phc_label)
    )

    # --- Summary hero ---
    if not portfolio_size:
        hero_class = "wl-hero-unknown"
        hero_icon  = "—"
        hero_label = "No portfolio found"
        hero_sub   = "No buildings under probable beneficial control found for this actor."
        verdict_pills = ""
    elif high_phc_rate:
        hero_class = "wl-hero-deteriorating"
        hero_icon  = "↓"
        hero_label = f"{phc_buildings} of {portfolio_size} buildings with PHC"
        hero_sub   = (
            f"{phc_rate:.0%} PHC rate · exceeds 50% threshold · "
            f"Rule PHC-001 · Interpretive status: Inferred"
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'{phc_buildings} PHC buildings ({phc_rate:.0%})</span>'
            f'<span class="wl-signal-pill wl-pill-fail">High-PHC-rate flag</span>'
            f'</div>'
        )
    elif phc_buildings > 0:
        hero_class = "wl-hero-unknown"
        hero_icon  = "⚠"
        hero_label = f"{phc_buildings} of {portfolio_size} buildings with PHC"
        hero_sub   = (
            f"{phc_rate:.0%} PHC rate · below 50% threshold · "
            f"Rule PHC-001 · Interpretive status: Inferred"
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'{phc_buildings} PHC buildings ({phc_rate:.0%})</span>'
            f'</div>'
        )
    else:
        hero_class = "wl-hero-stable"
        hero_icon  = "✓"
        hero_label = f"No PHC buildings in {portfolio_size}-building portfolio"
        hero_sub   = "No buildings in this portfolio satisfy Rule PHC-001."
        verdict_pills = ""

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Actor</strong> {_esc(actor_name)}</span>'
        f'<span><strong>Portfolio</strong> {portfolio_size:,} buildings</span>'
        f'<span><strong>PHC</strong> {phc_buildings:,} buildings</span>'
        f'<span><strong>Source</strong> HPD</span>'
        f'</div>'
    )

    hero_html = (
        f'<div class="wl-summary-hero {hero_class}">'
        f'  <div class="wl-hero-icon">{hero_icon}</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{_esc(hero_label)}</div>'
        f'    <div class="wl-hero-sub">{_esc(hero_sub)}</div>'
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


def _render_fine_evasion(tr: dict, prose: str) -> dict:
    """
    Render panel content for FineEvasion (FE-001 / RUL-00011).
    """
    from watchline.fw.intents.fine_evasion import _load_rule_from_graph

    raw       = tr.get("raw_results", [{}])
    row0      = raw[0] if raw else {}
    rule_eval = tr.get("rule_evaluation") or {}
    rule      = _load_rule_from_graph()

    evasion_flagged        = rule_eval.get("evasion_flagged", False)
    insufficient           = rule_eval.get("insufficient_data", False)
    total_balance_due      = rule_eval.get("total_balance_due", 0.0) or 0.0
    total_penalties        = rule_eval.get("total_penalties_imposed", 0.0) or 0.0
    total_paid             = rule_eval.get("total_paid", 0.0) or 0.0
    total_judgments        = rule_eval.get("total_judgments", 0) or 0
    judgments_with_balance = rule_eval.get("judgments_with_balance", 0) or 0

    # --- Stat cards ---
    stat_cards = (
        _stat_mini("Total judgments (w/ balance data)", total_judgments)
        + _stat_mini("Judgments with balance", judgments_with_balance,
                     danger=judgments_with_balance > 0)
        + _stat_mini("Total penalties imposed",
                     f"${total_penalties:,.0f}" if total_penalties else "—")
        + _stat_mini("Total paid",
                     f"${total_paid:,.0f}" if total_paid else "—")
        + _stat_mini("Total outstanding balance",
                     f"${total_balance_due:,.0f}" if total_balance_due else "$0",
                     danger=total_balance_due > 0)
        + _stat_mini("Rule FE-001 threshold", "$10,000")
    )

    # --- Outstanding items table ---
    raw_items = row0.get("outstanding_items") or []
    items = sorted(
        [it for it in raw_items if it is not None],
        key=lambda x: float(x.get("balance") or 0),
        reverse=True,
    )

    outstanding_table = ""
    if items:
        rows_html = ""
        display_items = items[:15]
        for it in display_items:
            date_val = it.get("date")
            date_str = str(date_val) if date_val is not None else "—"
            desc = str(it.get("description") or "—")
            desc_display = desc[:60] + "…" if len(desc) > 60 else desc
            penalty = it.get("penalty")
            paid    = it.get("paid")
            balance = it.get("balance")
            status  = it.get("status") or "—"
            rows_html += (
                f"<tr>"
                f"<td>{_esc(date_str)}</td>"
                f"<td title='{_esc(desc)}'>{_esc(desc_display)}</td>"
                f"<td>${float(penalty):,.0f}</td>" if penalty is not None
                else f"<td>—</td>"
            )
            rows_html += (
                f"<td>${float(paid):,.0f}</td>" if paid is not None
                else f"<td>—</td>"
            )
            rows_html += (
                f'<td style="color:#991b1b;font-weight:600;">'
                f'${float(balance):,.0f}</td>'
                if balance is not None else "<td>—</td>"
            )
            rows_html += f"<td>{_esc(status)}</td></tr>"

        overflow_note = ""
        if len(items) > 15:
            overflow_note = (
                f'<p style="font-size:0.8rem;color:#6b7a99;margin-top:0.5rem;">'
                f'Showing 15 of {len(items)} outstanding items, sorted by balance descending.</p>'
            )

        outstanding_table = (
            f'<div class="wl-section-head">Outstanding Judgments</div>'
            f'<table class="wl-table">'
            f'<thead><tr>'
            f'<th>Date</th><th>Description</th>'
            f'<th>Penalty</th><th>Paid</th><th>Balance due</th><th>Status</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>'
            f'{overflow_note}'
        )
    elif not insufficient:
        outstanding_table = (
            '<p style="color:#166534;font-size:0.9rem;margin:1rem 0;">'
            'No outstanding ECB judgment balances found for this building.</p>'
        )

    # --- Signal card ---
    if insufficient:
        signal_class   = "unknown"
        signal_verdict = "⚠ No ECB judgment data found for this building"
    elif evasion_flagged:
        signal_class   = "satisfied"
        signal_verdict = f"✓ Satisfies FE-001 — outstanding balance ${total_balance_due:,.0f} exceeds $10,000 threshold"
    else:
        signal_class   = "not-satisfied"
        signal_verdict = (
            f"✗ Does not satisfy FE-001 — outstanding balance "
            f"${total_balance_due:,.0f} does not exceed $10,000 threshold"
        )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("fine_evasion")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{STAT_CARDS}}",        stat_cards)
        .replace("{{OUTSTANDING_TABLE}}", outstanding_table)
        .replace("{{ADDRESS}}",           _esc(row0.get("address")))
        .replace("{{BOROUGH}}",           _esc(row0.get("borough")))
        .replace("{{BBL}}",               _esc(row0.get("bbl")))
        .replace("{{RESIDENTIAL_UNITS}}", _esc(row0.get("residential_units")))
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_VERSION}}",             _esc(rule.get("version", "1.0")))
        .replace("{{AUTHORITY}}",                _esc(rule.get("authority", "")))
        .replace("{{AUTHOR}}",                   _esc(rule.get("author", "")))
        .replace("{{EFFECTIVE_DATE}}",           _esc(rule.get("effective_date", "")))
        .replace("{{THRESHOLD_STATEMENT}}",      _esc(rule.get("threshold_description", "")))
        .replace("{{FALSIFICATION_CONDITIONS}}", _esc(rule.get("falsification_conditions", "")))
        .replace("{{SIGNAL_CLASS}}",             signal_class)
        .replace("{{SIGNAL_VERDICT}}",           _esc(signal_verdict))
        .replace("{{TOTAL_BALANCE_DISPLAY}}",    f"${total_balance_due:,.0f}")
        .replace("{{JUDGMENTS_WITH_BALANCE}}",   str(judgments_with_balance))
        .replace("{{TOTAL_JUDGMENTS}}",          str(total_judgments))
    )

    # --- Summary hero ---
    if insufficient:
        hero_class = "wl-hero-unknown"
        hero_icon  = "—"
        hero_label = "No ECB judgment history"
        hero_sub   = "No ECB/OATH judgment records found for this building."
        verdict_pills = ""
    elif evasion_flagged:
        hero_class = "wl-hero-deteriorating"
        hero_icon  = "⚠"
        hero_label = f"${total_balance_due:,.0f} outstanding ECB balance"
        hero_sub   = (
            f"{judgments_with_balance} judgment(s) with unpaid balance · "
            f"Rule FE-001 satisfied · Interpretive status: Inferred"
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'${total_balance_due:,.0f} outstanding</span>'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'{judgments_with_balance} unpaid judgment(s)</span>'
            f'</div>'
        )
    elif total_balance_due > 0:
        hero_class = "wl-hero-unknown"
        hero_icon  = "⚠"
        hero_label = f"${total_balance_due:,.0f} outstanding — below threshold"
        hero_sub   = (
            f"Outstanding balance present but does not exceed $10,000. "
            f"Does not satisfy Rule FE-001."
        )
        verdict_pills = (
            f'<div class="wl-signal-pills">'
            f'<span class="wl-signal-pill wl-pill-fail">'
            f'${total_balance_due:,.0f} outstanding</span>'
            f'<span class="wl-signal-pill wl-pill-ok">Below $10,000 threshold</span>'
            f'</div>'
        )
    else:
        hero_class = "wl-hero-stable"
        hero_icon  = "✓"
        hero_label = "No outstanding ECB balance"
        hero_sub   = f"{total_judgments} ECB judgment(s) reviewed — no unpaid balances."
        verdict_pills = ""

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Address</strong> {_esc(row0.get("address", ""))}, '
        f'{_esc(row0.get("borough", ""))}</span>'
        f'<span><strong>BBL</strong> {_esc(row0.get("bbl", ""))}</span>'
        f'<span><strong>Units</strong> {_esc(row0.get("residential_units", ""))}</span>'
        f'<span><strong>Source</strong> NYC OATH / ECB</span>'
        f'</div>'
    )

    hero_html = (
        f'<div class="wl-summary-hero {hero_class}">'
        f'  <div class="wl-hero-icon">{hero_icon}</div>'
        f'  <div class="wl-hero-body">'
        f'    <div class="wl-hero-label">{_esc(hero_label)}</div>'
        f'    <div class="wl-hero-sub">{_esc(hero_sub)}</div>'
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


def _render_enforcement_accountability(tr: dict, prose: str) -> dict:
    """
    Render panel content for EnforcementAccountability (Rule EA-001).
    """
    raw  = tr.get("raw_results", [])
    ev   = tr.get("rule_evaluation") or {}

    r                = raw[0] if raw else {}
    bbl              = _esc(r.get("bbl", "—"))
    address          = _esc(r.get("address", "—"))
    borough          = _esc(r.get("borough", "—"))
    units            = int(r.get("residential_units") or 0)
    long_open_c      = int(ev.get("long_open_c_count") or r.get("long_open_c") or 0)
    court_actions    = int(ev.get("court_actions") or r.get("court_actions_in_period") or 0)
    earliest_date    = str(ev.get("earliest_stale_date") or r.get("earliest_stale_date") or "—")
    gap              = bool(ev.get("accountability_gap", False))
    insufficient     = bool(ev.get("insufficient_data", False))

    stale_items = [x for x in (r.get("stale_violations") or []) if x is not None]
    stale_items.sort(key=lambda x: int(x.get("days_open") or 0), reverse=True)

    # --- Stat cards ---
    cards_html = (
        _stat_mini("Open Class C (> 1 yr)", str(long_open_c), danger=long_open_c >= 3)
        + _stat_mini("Court filings in period", str(court_actions),
                     danger=(court_actions == 0 and long_open_c >= 3))
        + _stat_mini("Earliest stale violation", earliest_date if earliest_date != "None" else "—")
    )

    # --- Stale violations table ---
    if stale_items:
        rows = ""
        for item in stale_items[:20]:
            days    = int(item.get("days_open") or 0)
            desc    = _esc(str(item.get("description") or "—"))[:120]
            code    = _esc(str(item.get("violation_code") or "—"))
            date_s  = _esc(str(item.get("date") or "—"))
            badge   = (
                '<span style="color:#c0392b;font-weight:700;">●</span>'
                if days > 730
                else '<span style="color:#e67e22;">●</span>'
            )
            rows += (
                f"<tr>"
                f"<td>{date_s}</td>"
                f"<td>{badge} {days:,}d</td>"
                f"<td style='font-family:monospace;font-size:0.8rem;'>{code}</td>"
                f"<td style='font-size:0.82rem;'>{desc}</td>"
                f"</tr>"
            )
        if len(stale_items) > 20:
            rows += (
                f'<tr><td colspan="4" style="color:#6b7a99;font-size:0.82rem;">'
                f'+ {len(stale_items) - 20} additional violations not shown</td></tr>'
            )
        stale_html = (
            f'<table class="wl-table"><thead><tr>'
            f'<th>Opened</th><th>Days open</th><th>Code</th><th>Description</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    else:
        stale_html = (
            '<p style="color:#6b7a99;font-size:0.85rem;">'
            'No open Class C violations older than 365 days found for this building.</p>'
        )

    # --- Signal card ---
    signal_satisfied = gap
    signal_color     = "#c0392b" if signal_satisfied else "#27ae60"
    signal_icon      = "✗" if signal_satisfied else "✓"
    signal_label     = (
        "Accountability gap: rule EA-001 SATISFIED"
        if signal_satisfied
        else "No accountability gap: rule EA-001 NOT satisfied"
    )
    signal_detail = (
        f"{long_open_c} open Class C violations > 365 days, "
        f"{court_actions} court filings since {earliest_date}"
        if earliest_date not in ("—", "None", None)
        else f"{long_open_c} open Class C violations > 365 days, {court_actions} court filings"
    )
    signal_card = (
        f'<div style="border-left:4px solid {signal_color};'
        f'padding:0.8rem 1rem;background:#fafbfc;margin-bottom:0.8rem;">'
        f'<div style="font-weight:700;color:{signal_color};">{signal_icon} {signal_label}</div>'
        f'<div style="font-size:0.85rem;color:#555;margin-top:0.3rem;">{signal_detail}</div>'
        f'</div>'
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("enforcement_accountability")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    rule = tr.get("rule_evaluation") or {}
    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{STAT_CARDS}}", cards_html)
        .replace("{{STALE_TABLE}}", stale_html)
        .replace("{{ADDRESS}}", address)
        .replace("{{BOROUGH}}", borough)
        .replace("{{BBL}}", bbl)
        .replace("{{UNITS}}", f"{units:,}" if units else "—")
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_TITLE}}",        _esc(rule.get("rule_title", "Enforcement Accountability Gap")))
        .replace("{{RULE_ID}}",           _esc(rule.get("rule_id", "EA-001")))
        .replace("{{GRAPH_RULE_ID}}",     "RUL-00012")
        .replace("{{RULE_VERSION}}",      _esc(rule.get("rule_version", "1.0")))
        .replace("{{AUTHORITY}}",         _esc(rule.get("authority", "")))
        .replace("{{THRESHOLD_LOGIC}}",   _esc(rule.get("threshold_logic", "long_open_c >= 3 AND court_actions_in_period == 0")))
        .replace("{{SIGNAL_CARD}}",       signal_card)
        .replace("{{THRESHOLD_STATEMENT}}", _esc(rule.get("threshold_statement", "")))
    )

    # --- Summary hero ---
    if insufficient:
        hero_html = (
            '<div class="wl-summary-hero wl-hero-stable">'
            '  <div class="wl-hero-icon">?</div>'
            '  <div class="wl-hero-body">'
            '    <div class="wl-hero-label">No data for this building</div>'
            '    <div class="wl-hero-sub">EA-001 · Inferred · Insufficient data</div>'
            '  </div>'
            '</div>'
        )
    elif gap:
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-deteriorating">'
            f'  <div class="wl-hero-icon">!</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">Enforcement accountability gap</div>'
            f'    <div class="wl-hero-sub">'
            f'      {long_open_c} stale Class C violations · 0 court filings · EA-001 satisfied · Inferred'
            f'    </div>'
            f'  </div>'
            f'</div>'
            f'<div class="wl-signal-pills">'
            f'  <span class="wl-signal-pill wl-pill-fail">'
            f'  EA-001: {long_open_c} stale Class C · 0 court actions</span>'
            f'</div>'
        )
    else:
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-stable">'
            f'  <div class="wl-hero-icon">✓</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">No enforcement accountability gap</div>'
            f'    <div class="wl-hero-sub">'
            f'      {long_open_c} stale Class C violation(s) · {court_actions} court filing(s) · EA-001 not satisfied'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Stale Class C</strong> {long_open_c}</span>'
        f'<span><strong>Court filings (period)</strong> {court_actions}</span>'
        f'<span><strong>Rule</strong> EA-001</span>'
        f'<span><strong>Source</strong> HPD</span>'
        f'</div>'
    )

    return {
        "SUMMARY_PANEL":  hero_html + facts + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_geographic_concentration(tr: dict, prose: str) -> dict:
    """
    Render panel content for GeographicConcentration (no rule — PHC aggregation).
    """
    raw = tr.get("raw_results", [])

    borough_filter = (tr.get("params") or {}).get("borough") or "All boroughs"
    is_filtered    = borough_filter != "All boroughs"

    # --- City-wide aggregates ---
    total_phc   = sum(int(r.get("phc_buildings") or 0) for r in raw)
    total_units = sum(int(r.get("affected_units") or 0) for r in raw)
    num_boroughs = len(raw)

    # --- Summary stat cards ---
    cards_html = (
        _stat_mini("Boroughs shown",     str(num_boroughs))
        + _stat_mini("Total PHC buildings", f"{total_phc:,}", danger=True)
        + _stat_mini("Affected units",    f"{total_units:,}", danger=True)
    )

    # --- Borough breakdown table ---
    if raw:
        rows = ""
        for r in raw:
            boro  = _esc(r.get("borough") or "—")
            phc   = int(r.get("phc_buildings") or 0)
            units = int(r.get("affected_units") or 0)
            pct   = f"{phc / total_phc:.0%}" if total_phc else "—"
            rows += (
                f"<tr>"
                f"<td><strong>{boro}</strong></td>"
                f"<td style='text-align:right;'>{phc:,}</td>"
                f"<td style='text-align:right;'>{pct}</td>"
                f"<td style='text-align:right;'>{units:,}</td>"
                f"</tr>"
            )
        borough_table = (
            f'<table class="wl-table"><thead><tr>'
            f'<th>Borough</th><th>PHC buildings</th>'
            f'<th>% of city PHC</th><th>Affected units</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    else:
        borough_table = (
            '<p style="color:#6b7a99;font-size:0.85rem;">No PHC buildings found.</p>'
        )

    # --- Top buildings section (shown for all results) ---
    top_buildings_html = ""
    for r in raw:
        boro     = _esc(r.get("borough") or "—")
        top_bldgs = [b for b in (r.get("top_buildings") or []) if b is not None]
        if not top_bldgs:
            continue
        bldg_rows = "".join(
            f"<tr>"
            f"<td style='font-size:0.82rem;'>{_esc(str(b.get('address') or '—'))}</td>"
            f"<td style='text-align:right;'>{int(b.get('units') or 0):,}</td>"
            f"</tr>"
            for b in top_bldgs
        )
        top_buildings_html += (
            f'<div class="wl-section-head" style="margin-top:1.2rem;">'
            f'Largest PHC Buildings — {boro}</div>'
            f'<table class="wl-table"><thead><tr>'
            f'<th>Address</th><th>Units</th>'
            f'</tr></thead><tbody>{bldg_rows}</tbody></table>'
        )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("geographic_concentration")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{SUMMARY_CARDS}}",       cards_html)
        .replace("{{BOROUGH_TABLE}}",       borough_table)
        .replace("{{TOP_BUILDINGS_SECTION}}", top_buildings_html)
        .replace("{{BOROUGH_FILTER}}",      _esc(borough_filter))
    )

    rules_html = tmpl_map.get("RULES", "")

    # --- Hero ---
    if not raw:
        hero_html = (
            '<div class="wl-summary-hero wl-hero-stable">'
            '  <div class="wl-hero-icon">?</div>'
            '  <div class="wl-hero-body">'
            '    <div class="wl-hero-label">No PHC buildings found</div>'
            '    <div class="wl-hero-sub">PHC-001 · No results</div>'
            '  </div>'
            '</div>'
        )
    else:
        top_boro     = raw[0]
        top_boro_name = _esc(top_boro.get("borough") or "—")
        top_boro_phc  = int(top_boro.get("phc_buildings") or 0)
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-deteriorating">'
            f'  <div class="wl-hero-icon">↓</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">'
            f'      {"" if is_filtered else f"Most: "}{top_boro_name} — {top_boro_phc:,} PHC buildings'
            f'    </div>'
            f'    <div class="wl-hero-sub">'
            f'      {total_phc:,} total PHC buildings · {total_units:,} affected units · '
            f'      {borough_filter} · PHC-001 · Inferred'
            f'    </div>'
            f'  </div>'
            f'</div>'
            f'<div class="wl-signal-pills">'
            f'  <span class="wl-signal-pill wl-pill-fail">'
            f'  {total_phc:,} PHC buildings in {borough_filter}</span>'
            f'</div>'
        )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Filter</strong> {_esc(borough_filter)}</span>'
        f'<span><strong>PHC buildings</strong> {total_phc:,}</span>'
        f'<span><strong>Affected units</strong> {total_units:,}</span>'
        f'<span><strong>Rule</strong> PHC-001</span>'
        f'</div>'
    )

    return {
        "SUMMARY_PANEL":  hero_html + facts + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_concealment_detection(tr: dict, prose: str) -> dict:
    """
    Render panel content for ConcealmentDetection (RUL-00003/RUL-00004).
    No new rule — computes address-to-name connection ratio from Evidence summary.
    """
    raw = tr.get("raw_results", [])
    ev  = tr.get("rule_evaluation") or {}

    r                  = raw[0] if raw else {}
    name               = _esc(r.get("name") or "—")
    portfolio_size     = int(ev.get("portfolio_size") or r.get("portfolio_size") or 0)
    addr_edges         = int(ev.get("addr_edges") or 0)
    name_edges         = int(ev.get("name_edges") or 0)
    addr_name_ratio    = ev.get("addr_name_ratio")
    distinct_names     = int(ev.get("distinct_names") or r.get("distinct_names") or 0)
    name_diversity     = ev.get("name_diversity")
    observed_names     = list(ev.get("observed_names") or r.get("observed_names") or [])
    observed_names     = [n for n in observed_names if n]
    concealment        = bool(ev.get("concealment_flagged", False))
    insufficient       = bool(ev.get("insufficient_data", False))
    confidence         = _esc(ev.get("confidence") or r.get("confidence") or "—")
    rationale          = _esc(ev.get("rationale") or r.get("rationale") or "—")

    # --- Ratio display ---
    if name_edges == 0:
        ratio_str = f"{addr_edges}:0 (name-only portfolio)"
    else:
        ratio_str = f"{addr_edges}:{name_edges} ({addr_name_ratio}×)"

    # --- Stat cards ---
    cards_html = (
        _stat_mini("Portfolio size",      f"{portfolio_size:,}")
        + _stat_mini("Address connections", str(addr_edges), danger=concealment)
        + _stat_mini("Name connections",   str(name_edges))
        + _stat_mini("Addr:name ratio",    ratio_str, danger=concealment)
        + _stat_mini("Distinct entity names", str(distinct_names))
        + _stat_mini("Names per building",
                     f"{name_diversity:.2f}" if name_diversity is not None else "—",
                     danger=(name_diversity or 0) > 0.5)
    )

    # --- Signal banner ---
    if concealment:
        signal_banner = (
            f'<div style="border-left:4px solid #c0392b;padding:0.6rem 1rem;'
            f'background:#fff5f5;margin-bottom:1rem;">'
            f'<strong style="color:#c0392b;">High concealment signal</strong> — '
            f'address-based connections ({addr_edges}) exceed name-based ({name_edges}) '
            f'by {ratio_str}. Threshold: > 10×.'
            f'</div>'
        )
    elif insufficient:
        signal_banner = (
            '<div style="border-left:4px solid #999;padding:0.6rem 1rem;'
            'background:#f8f8f8;margin-bottom:1rem;">'
            '<strong style="color:#999;">Insufficient data</strong> — '
            'no HPD registration connection data found for this actor.'
            '</div>'
        )
    else:
        signal_banner = (
            f'<div style="border-left:4px solid #27ae60;padding:0.6rem 1rem;'
            f'background:#f0fff4;margin-bottom:1rem;">'
            f'<strong style="color:#27ae60;">No strong concealment signal</strong> — '
            f'address-to-name ratio ({ratio_str}) is below the 10× threshold.'
            f'</div>'
        )

    # --- Observed names table ---
    if observed_names:
        rows = "".join(
            f"<tr><td>{i}</td><td>{_esc(n)}</td></tr>"
            for i, n in enumerate(sorted(observed_names), start=1)
        )
        names_table = (
            f'<div class="wl-section-head">Observed Entity Names ({distinct_names})</div>'
            f'<p style="font-size:0.82rem;color:#6b7a99;margin-bottom:0.5rem;">'
            f'Raw registrant name strings from HPD registration records grouped into this portfolio.</p>'
            f'<table class="wl-table"><thead><tr><th>#</th><th>Name</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    else:
        names_table = (
            '<p style="color:#6b7a99;font-size:0.85rem;">No entity name observations available.</p>'
        )

    # --- Signal card for Rules tab ---
    s_color  = "#c0392b" if concealment else "#27ae60"
    s_icon   = "✗" if concealment else "✓"
    s_label  = "Concealment signal PRESENT" if concealment else "No strong concealment signal"
    s_detail = (
        f"Address-based connections: {addr_edges} · "
        f"Name-based connections: {name_edges} · "
        f"Ratio: {ratio_str} · Threshold: > 10×"
    )
    signal_card = (
        f'<div style="border-left:4px solid {s_color};'
        f'padding:0.8rem 1rem;background:#fafbfc;margin-bottom:0.8rem;">'
        f'<div style="font-weight:700;color:{s_color};">{s_icon} {s_label}</div>'
        f'<div style="font-size:0.85rem;color:#555;margin-top:0.3rem;">{s_detail}</div>'
        f'</div>'
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("concealment_detection")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{STAT_CARDS}}",    cards_html)
        .replace("{{SIGNAL_BANNER}}", signal_banner)
        .replace("{{NAMES_TABLE}}",   names_table)
        .replace("{{ACTOR_NAME}}",    name)
        .replace("{{PORTFOLIO_SIZE}}", f"{portfolio_size:,}")
        .replace("{{CONFIDENCE}}",    confidence)
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{SIGNAL_CARD}}",        signal_card)
        .replace("{{THRESHOLD_STATEMENT}}", _esc(ev.get("threshold_statement", "")))
        .replace("{{RATIONALE}}",          rationale)
    )

    # --- Hero ---
    if insufficient:
        hero_html = (
            '<div class="wl-summary-hero wl-hero-stable">'
            '  <div class="wl-hero-icon">?</div>'
            '  <div class="wl-hero-body">'
            '    <div class="wl-hero-label">No connection data available</div>'
            '    <div class="wl-hero-sub">RMT-001/002 · Insufficient data</div>'
            '  </div>'
            '</div>'
        )
    elif concealment:
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-deteriorating">'
            f'  <div class="wl-hero-icon">!</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">High concealment signal</div>'
            f'    <div class="wl-hero-sub">'
            f'      {addr_edges} address connections vs {name_edges} name connections · '
            f'      ratio {ratio_str} · Inferred'
            f'    </div>'
            f'  </div>'
            f'</div>'
            f'<div class="wl-signal-pills">'
            f'  <span class="wl-signal-pill wl-pill-fail">'
            f'  Addr:name ratio {ratio_str} exceeds 10×</span>'
            f'</div>'
        )
    else:
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-stable">'
            f'  <div class="wl-hero-icon">✓</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">No strong concealment signal</div>'
            f'    <div class="wl-hero-sub">'
            f'      {addr_edges} address connections · {name_edges} name connections · '
            f'      ratio {ratio_str} · below 10× threshold'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Addr connections</strong> {addr_edges}</span>'
        f'<span><strong>Name connections</strong> {name_edges}</span>'
        f'<span><strong>Entity names</strong> {distinct_names}</span>'
        f'<span><strong>PBC confidence</strong> {confidence}</span>'
        f'</div>'
    )

    return {
        "SUMMARY_PANEL":  hero_html + facts + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


def _render_recidivism(tr: dict, prose: str) -> dict:
    """
    Render panel content for Recidivism (Rule RCV-001).
    Two signals: multi-borough PHC spread and multi-year open Class C persistence.
    """
    raw = tr.get("raw_results", [])
    ev  = tr.get("rule_evaluation") or {}

    r                 = raw[0] if raw else {}
    name              = _esc(r.get("name") or ev.get("name") or "—")
    portfolio_size    = int(ev.get("portfolio_size") or r.get("portfolio_size") or 0)
    phc_buildings     = int(ev.get("phc_buildings") or r.get("phc_buildings") or 0)
    phc_borough_count = int(ev.get("phc_borough_count") or r.get("phc_borough_count") or 0)
    phc_boroughs      = list(ev.get("phc_boroughs") or r.get("phc_boroughs") or [])
    multi_year_bldgs  = int(ev.get("multi_year_buildings") or r.get("multi_year_buildings") or 0)
    recidivist        = bool(ev.get("recidivist", False))
    signal_a          = bool(ev.get("signal_a", False))
    signal_b          = bool(ev.get("signal_b", False))
    insufficient      = bool(ev.get("insufficient_data", False))

    affected = [x for x in (ev.get("affected_buildings") or r.get("notable_buildings") or []) if x is not None]

    # --- Stat cards ---
    cards_html = (
        _stat_mini("Portfolio size",        f"{portfolio_size:,}")
        + _stat_mini("PHC buildings",       f"{phc_buildings:,}", danger=phc_buildings > 0)
        + _stat_mini("PHC boroughs",        str(phc_borough_count), danger=signal_a)
        + _stat_mini("Multi-year buildings", str(multi_year_bldgs), danger=signal_b)
        + _stat_mini("PHC rate",            f"{phc_buildings/portfolio_size:.0%}" if portfolio_size else "—",
                     danger=phc_buildings > 0)
        + _stat_mini("Rule result",         "RCV-001 satisfied" if recidivist else "Not satisfied",
                     danger=recidivist)
    )

    # --- Signal summary banner ---
    borough_list = ", ".join(b for b in phc_boroughs if b)
    signal_summary = ""
    if signal_a:
        signal_summary += (
            f'<div style="border-left:4px solid #c0392b;padding:0.6rem 1rem;'
            f'background:#fff5f5;margin-bottom:0.6rem;">'
            f'<strong style="color:#c0392b;">Signal A: Multi-borough persistence</strong> — '
            f'PHC-flagged buildings in {phc_borough_count} boroughs ({borough_list})'
            f'</div>'
        )
    if signal_b:
        signal_summary += (
            f'<div style="border-left:4px solid #c0392b;padding:0.6rem 1rem;'
            f'background:#fff5f5;margin-bottom:0.6rem;">'
            f'<strong style="color:#c0392b;">Signal B: Multi-year persistence</strong> — '
            f'{multi_year_bldgs} building(s) with open Class C violations from 3+ years ago'
            f'</div>'
        )
    if not signal_a and not signal_b and not insufficient:
        signal_summary = (
            '<div style="border-left:4px solid #27ae60;padding:0.6rem 1rem;'
            'background:#f0fff4;margin-bottom:0.6rem;">'
            '<strong style="color:#27ae60;">Neither signal satisfied</strong> — '
            'PHC buildings limited to one borough and no multi-year violations found'
            '</div>'
        )

    # --- Notable buildings table ---
    if affected:
        affected_sorted = sorted(
            affected,
            key=lambda x: (-int(x.get("years_with_open_c") or 0), x.get("borough", ""))
        )
        rows = ""
        for bldg in affected_sorted[:25]:
            addr   = _esc(str(bldg.get("address") or "—"))
            boro   = _esc(str(bldg.get("borough") or "—"))
            units  = int(bldg.get("units") or 0)
            yrs    = int(bldg.get("years_with_open_c") or 0)
            has_phc = bool(bldg.get("has_phc", False))
            phc_badge = (
                '<span style="color:#c0392b;font-weight:700;">PHC</span>'
                if has_phc else ""
            )
            yr_badge = (
                f'<span style="color:#e67e22;font-weight:700;">{yrs}yr</span>'
                if yrs >= 3 else (f"{yrs}yr" if yrs else "—")
            )
            rows += (
                f"<tr>"
                f"<td>{addr}</td>"
                f"<td>{boro}</td>"
                f"<td style='text-align:right;'>{units or '—'}</td>"
                f"<td style='text-align:center;'>{phc_badge}</td>"
                f"<td style='text-align:center;'>{yr_badge}</td>"
                f"</tr>"
            )
        if len(affected) > 25:
            rows += (
                f'<tr><td colspan="5" style="color:#6b7a99;font-size:0.82rem;">'
                f'+ {len(affected) - 25} additional buildings not shown</td></tr>'
            )
        notable_html = (
            f'<div class="wl-section-head">Notable Buildings</div>'
            f'<table class="wl-table"><thead><tr>'
            f'<th>Address</th><th>Borough</th><th>Units</th>'
            f'<th>PHC</th><th>Yrs open C</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    else:
        notable_html = (
            '<p style="color:#6b7a99;font-size:0.85rem;">'
            'No notable buildings found (no PHC claims and no multi-year open violations).</p>'
        )

    # --- Signal cards for Rules tab ---
    def _sig_card(label: str, sat: bool, detail: str) -> str:
        color = "#c0392b" if sat else "#27ae60"
        icon  = "✗" if sat else "✓"
        verdict = "SATISFIED" if sat else "not satisfied"
        return (
            f'<div style="border-left:4px solid {color};'
            f'padding:0.8rem 1rem;background:#fafbfc;margin-bottom:0.8rem;">'
            f'<div style="font-weight:700;color:{color};">{icon} Signal {label}: {verdict}</div>'
            f'<div style="font-size:0.85rem;color:#555;margin-top:0.3rem;">{detail}</div>'
            f'</div>'
        )

    signal_cards = (
        _sig_card("A (multi-borough)",
                  signal_a,
                  f"PHC buildings in {phc_borough_count} borough(s): {borough_list or '—'}. "
                  f"Threshold: > 1 borough.")
        + _sig_card("B (multi-year)",
                    signal_b,
                    f"{multi_year_bldgs} building(s) with Class C violations open 3+ years. "
                    f"Threshold: ≥ 1 such building.")
    )

    # --- Load and split template ---
    _KNOWN_SECTIONS = {"EVIDENCE", "RULES"}
    tmpl     = _intent_tmpl("recidivism")
    sections = tmpl.split("%%")
    tmpl_map = {}
    for i in range(1, len(sections) - 1, 2):
        key = sections[i].strip()
        if key in _KNOWN_SECTIONS:
            tmpl_map[key] = sections[i + 1]

    rule = tr.get("rule_evaluation") or {}
    evidence_html = (
        tmpl_map.get("EVIDENCE", "")
        .replace("{{STAT_CARDS}}",      cards_html)
        .replace("{{SIGNAL_SUMMARY}}", signal_summary)
        .replace("{{NOTABLE_TABLE}}",  notable_html)
        .replace("{{ACTOR_NAME}}",     name)
        .replace("{{PORTFOLIO_SIZE}}", f"{portfolio_size:,}")
        .replace("{{PHC_BOROUGHS}}",   borough_list or "—")
    )

    rules_html = (
        tmpl_map.get("RULES", "")
        .replace("{{RULE_TITLE}}",          _esc(rule.get("rule_title", "Recidivism")))
        .replace("{{RULE_ID}}",             _esc(rule.get("rule_id", "RCV-001")))
        .replace("{{GRAPH_RULE_ID}}",       "RUL-00013")
        .replace("{{RULE_VERSION}}",        _esc(rule.get("rule_version", "1.0")))
        .replace("{{AUTHORITY}}",           _esc(rule.get("authority", "")))
        .replace("{{THRESHOLD_LOGIC}}",     _esc(rule.get("threshold_logic", "")))
        .replace("{{SIGNAL_CARDS}}",        signal_cards)
        .replace("{{THRESHOLD_STATEMENT}}", _esc(rule.get("threshold_statement", "")))
    )

    # --- Hero ---
    if insufficient:
        hero_html = (
            '<div class="wl-summary-hero wl-hero-stable">'
            '  <div class="wl-hero-icon">?</div>'
            '  <div class="wl-hero-body">'
            '    <div class="wl-hero-label">No portfolio data found</div>'
            '    <div class="wl-hero-sub">RCV-001 · Insufficient data</div>'
            '  </div>'
            '</div>'
        )
    elif recidivist:
        signals_fired = []
        if signal_a:
            signals_fired.append(f"PHC in {phc_borough_count} boroughs")
        if signal_b:
            signals_fired.append(f"{multi_year_bldgs} multi-year buildings")
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-deteriorating">'
            f'  <div class="wl-hero-icon">!</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">Recidivism pattern detected</div>'
            f'    <div class="wl-hero-sub">'
            f'      {" · ".join(signals_fired)} · RCV-001 satisfied · Inferred'
            f'    </div>'
            f'  </div>'
            f'</div>'
            f'<div class="wl-signal-pills">'
            + ("".join(
                f'<span class="wl-signal-pill wl-pill-fail">{s}</span>'
                for s in signals_fired
            ))
            + f'</div>'
        )
    else:
        hero_html = (
            f'<div class="wl-summary-hero wl-hero-stable">'
            f'  <div class="wl-hero-icon">✓</div>'
            f'  <div class="wl-hero-body">'
            f'    <div class="wl-hero-label">No recidivism pattern detected</div>'
            f'    <div class="wl-hero-sub">'
            f'      PHC in {phc_borough_count} borough(s) · {multi_year_bldgs} multi-year buildings · RCV-001 not satisfied'
            f'    </div>'
            f'  </div>'
            f'</div>'
        )

    facts = (
        f'<div class="wl-facts-strip">'
        f'<span><strong>Portfolio</strong> {portfolio_size:,} buildings</span>'
        f'<span><strong>PHC buildings</strong> {phc_buildings:,}</span>'
        f'<span><strong>PHC boroughs</strong> {phc_borough_count}</span>'
        f'<span><strong>Multi-year</strong> {multi_year_bldgs}</span>'
        f'</div>'
    )

    return {
        "SUMMARY_PANEL":  hero_html + facts + f'<div class="wl-prose">{_prose_to_html(prose)}</div>',
        "EVIDENCE_PANEL": evidence_html,
        "RULES_PANEL":    rules_html,
    }


# Registry: intent_category -> panel renderer function
_PANEL_RENDERERS = {
    "DeteriorationTrajectory":      _render_deterioration,
    "PortfolioIdentification":      _render_portfolio_identification,
    "BuildingDueDiligence":         _render_building_due_diligence,
    "RentStabilization":            _render_rent_stabilization,
    "FineEvasion":                  _render_fine_evasion,
    "WorstFirst":                   _render_worst_first,
    "PortfolioCondition":           _render_portfolio_condition,
    "EnforcementAccountability":    _render_enforcement_accountability,
    "ConcealmentDetection":         _render_concealment_detection,
    "GeographicConcentration":      _render_geographic_concentration,
    "Recidivism":                   _render_recidivism,
    "NetworkExposure":              _render_network_exposure,
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
