"""Deterministic branded HTML rendering of a result (pure — no Streamlit).

Turns ``(question, answer_markdown, Evidence)`` into a single **self-contained** HTML
page in the Watchline identity — the "referral-ready" document. No LLM: a template
plus a markdown→HTML pass. The narrative carries graph- and web-sourced text that is
attacker-influenceable, so markdown is rendered with **raw HTML disabled** — a
``<script>`` in the narrative is escaped to text, never executed. Mirrors
``to_markdown``; the app offers Download / Open-in-new-tab.

Pure and deterministic: ``generated_at`` (and optional cost/model/trust) are passed
in, so the output is a function of its inputs and hermetically testable.
"""

from __future__ import annotations

import base64
import html as _html
import re
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

__all__ = ["to_html", "REPORT_CSS"]

# --------------------------------------------------------------------------- #
# Logo (embedded so the output is one portable file)
# --------------------------------------------------------------------------- #
_LOGO = Path(__file__).with_name("logo.png")


def _logo_data_uri() -> str:
    try:
        b64 = base64.b64encode(_LOGO.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except OSError:  # missing logo degrades to no image, never a crash
        return ""


_LOGO_DATA_URI = _logo_data_uri()

# --------------------------------------------------------------------------- #
# Markdown → HTML (raw HTML disabled = escaped), with heading ids + a badge pass
# --------------------------------------------------------------------------- #
_MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")

_TAG = re.compile(r"(<[^>]+>)")
_STATUS = re.compile(r"\b(OPEN|PENDING|CLOSED|RESOLVED|ACTIVE)\b")
_STATUS_CLASS = {"OPEN": "open", "PENDING": "pending", "ACTIVE": "pending",
                 "CLOSED": "resolved", "RESOLVED": "resolved"}


def _esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value))


def _slug(text: str, seen: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    slug, n = base, 2
    while slug in seen:
        slug, n = f"{base}-{n}", n + 1
    seen.add(slug)
    return slug


def _badgeify(html_str: str) -> str:
    """Wrap status tokens in badge spans — but only in the text *between* tags, so
    it can never corrupt attributes or markup."""
    parts = _TAG.split(html_str)
    for i in range(0, len(parts), 2):  # even indices are text, odd are <tags>
        parts[i] = _STATUS.sub(
            lambda m: f'<span class="badge {_STATUS_CLASS[m.group(1)]}">{m.group(1)}</span>',
            parts[i],
        )
    return "".join(parts)


def _render_markdown(md_text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Render the narrative; return (html, toc) where toc is (level, text, slug)."""
    tokens = _MD.parse(md_text or "")
    seen: set[str] = set()
    toc: list[tuple[int, str, str]] = []
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.tag in ("h2", "h3"):
            text = tokens[i + 1].content if i + 1 < len(tokens) else ""
            slug = _slug(text, seen)
            tok.attrSet("id", slug)
            toc.append((int(tok.tag[1]), text, slug))
    html_str = _MD.renderer.render(tokens, _MD.options, {})
    # Wrap tables so wide ones scroll rather than break the layout.
    html_str = html_str.replace("<table>", '<div class="tablewrap"><table>').replace(
        "</table>", "</table></div>")
    return _badgeify(html_str), toc


# --------------------------------------------------------------------------- #
# Fragments
# --------------------------------------------------------------------------- #
#: Only show the contents list when there is enough structure to be worth
#: navigating — a short, few-section answer doesn't need one.
_TOC_MIN_HEADINGS = 4


def _toc_html(toc: list[tuple[int, str, str]]) -> str:
    if len(toc) < _TOC_MIN_HEADINGS:
        return ""
    items = "".join(
        f'<li class="lvl{lvl}"><a href="#{slug}">{_esc(text)}</a></li>'
        for lvl, text, slug in toc
    )
    return f'<nav class="toc" aria-label="Contents"><b>Contents</b><ol>{items}</ol></nav>'


def _provenance_html(generated_at, model, trust_level, cost, evidence, *, standalone=False) -> str:
    bits: list[tuple[str, str]] = []
    if model:
        bits.append(("Model", _esc(model)))
    if trust_level:
        bits.append(("Trust", _esc(trust_level)))
    tools = len(evidence.citations) if evidence else 0
    webn = evidence.web_searches if evidence else 0
    bits.append(("Tools", f"{tools} graph · {webn} web search{'' if webn == 1 else 'es'}"))
    if cost is not None:
        bits.append(("Est. cost", f"${cost.usd:.4f}"))
    inner = "".join(f"<span><b>{_esc(k)}</b> {v}</span>" for k, v in bits)
    cls = "provenance standalone" if standalone else "provenance"
    return f'<div class="{cls}">{inner}</div>'


_LEGEND = (
    '<div class="legend">'
    '<span><i class="dot graph"></i> Graph-verified — direct from HPD/DOB/ACRIS/court records</span>'
    '<span><i class="dot infer"></i> Inferred — graph clustering (apparent control, portfolio)</span>'
    '<span><i class="dot web"></i> Web-sourced — public reporting, lower confidence</span>'
    '</div>'
)


def _evidence_html(evidence) -> str:
    if evidence is None:
        return ""
    out = ['<section id="evidence"><h2 class="ev-title">Evidence &amp; Sources</h2>', _LEGEND]

    rr = evidence.resolved_reference
    if rr:
        out.append(
            f'<p class="rr"><b>Resolved reference</b> — read as {_esc(rr.get("type"))} '
            f'<code>{_esc(rr.get("id"))}</code> (via {_esc(rr.get("via"))}).</p>')

    if evidence.citations:
        out.append('<div class="refhead">Citations · graph-verified</div><ul class="sources">')
        for c in evidence.citations:
            bits = [f'<code>{_esc(c.get("tool"))}</code>']
            if c.get("source_name"):
                bits.append(f'source <b>{_esc(c.get("source_name"))}</b>')
            if c.get("run_id"):
                bits.append(f'run <code>{_esc(c.get("run_id"))}</code>')
            out.append("<li>" + " · ".join(bits) + "</li>")
        out.append("</ul>")

    if evidence.caveats:
        out.append('<div class="refhead">Caveats · what the record does and does not establish</div>'
                   '<div class="caveats">')
        for c in evidence.caveats:
            out.append(f'<div class="cav"><span class="chip">{_esc(c.get("element"))}</span> '
                       f'{_esc(c.get("text"))}</div>')
        out.append("</div>")

    if evidence.web_sources:
        out.append('<div class="refhead">Web sources · lower confidence, never treated as ownership</div>'
                   '<ul class="sources">')
        for w in evidence.web_sources:
            url = w.get("url")
            title = _esc(w.get("title") or w.get("url") or "source")
            if url:
                out.append(f'<li><a href="{_esc(url)}" rel="noopener noreferrer" '
                           f'target="_blank">{title}</a></li>')
            else:
                out.append(f"<li>{title}</li>")
        out.append("</ul>")
    elif evidence.web_searches:
        out.append('<div class="refhead">Web sources · lower confidence, never treated as ownership</div>'
                   f'<p class="muted">Web searches performed: {int(evidence.web_searches)} '
                   '(no sources returned)</p>')

    out.append("</section>")
    return "".join(out)


_DISCLAIMER = (
    "Analytical work product generated from public records. Graph-derived relationships "
    "(e.g., apparent control, portfolio grouping) are inferences, not legal determinations — "
    "see the Reliability Caveats."
)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def to_html(question, answer, evidence, *, generated_at=None, cost=None,
            model=None, trust_level=None, branded=True) -> str:
    """A self-contained branded HTML page for one result. Pure — no I/O beyond the
    (import-time, cached) embedded logo."""
    narrative, toc = _render_markdown(answer or "")
    # The masthead (brand banner + kicker + disclaimer) belongs to the standalone
    # artifact (download / open-in-tab). The in-app preview passes branded=False and
    # drops it entirely — the app already frames the result. Fall back to text only
    # if the logo failed to embed.
    masthead = ""
    if branded:
        brand = (
            f'<img class="logo" src="{_LOGO_DATA_URI}" alt="Watchline NYC — Discovery">'
            if _LOGO_DATA_URI else
            '<div class="brandtext"><div class="eyebrow">Accountability infrastructure for NYC housing</div>'
            '<h1>Watchline NYC — Discovery</h1></div>')
        kicker = "Result report · grounded in the public record"
        if generated_at:
            _d, _, _t = generated_at.partition(" ")
            kicker += f" on {_d} at {_t}" if _t else f" on {_d}"
        masthead = (
            f'<header class="masthead">{brand}<div class="mast-right">'
            f'<div class="kicker">{_esc(kicker)}</div>'
            f'<div class="mast-disclaimer">{_DISCLAIMER}</div>'
            "</div></header>")
    question_block = (
        f'<div class="question"><b>Investigation request</b>{_esc(question)}</div>'
        if question else "")

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Watchline NYC — Discovery · Result report</title>"
        f"<style>{REPORT_CSS}</style></head><body><div class=\"wrap\">"
        f"{masthead}"
        f"{_provenance_html(generated_at, model, trust_level, cost, evidence, standalone=not branded)}"
        f"{question_block}"
        '<main class="doc">'
        f"{_toc_html(toc)}"
        f'<div class="narrative">{narrative}</div>'
        f"{_evidence_html(evidence)}"
        "</main>"
        '<div class="footer"><span class="brandline"><span class="fdot"></span> '
        "Generated by Watchline NYC — Discovery <span class=\"fdot\"></span></span></div>"
        "</div></body></html>"
    )


# --------------------------------------------------------------------------- #
# Stylesheet (Watchline identity; scopes the rendered markdown under .narrative)
# --------------------------------------------------------------------------- #
REPORT_CSS = """
:root{
  --navy:#0a1629;--navy-2:#12243f;--gold:#d4a017;--ink:#1b2430;--muted:#5c6b80;--faint:#8290a3;
  --line:#e3e7ee;--bg:#eef1f5;--card:#fff;--danger:#b0261c;--danger-bg:#fbeae7;
  --warn:#8a5a00;--warn-bg:#fdf3df;--ok:#256a4c;--ok-bg:#e7f4ee;--info-bg:#eef3fb;
  --serif:Georgia,"Iowan Old Style","Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--serif);font-size:16px;line-height:1.6}
.wrap{max-width:920px;margin:0 auto;padding:28px 18px 64px}
.masthead{display:flex;align-items:center;gap:26px;
  background:linear-gradient(180deg,var(--navy),var(--navy-2));
  border-left:6px solid var(--gold);border-radius:12px 12px 0 0;padding:24px 30px;color:#fff;
  box-shadow:0 12px 30px rgba(10,22,41,.28)}
.masthead .logo{width:220px;max-width:42%;height:auto;flex:none;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.35)}
.masthead .brandtext{flex:none}
.masthead .eyebrow{font-family:var(--sans);font-size:.6rem;letter-spacing:.26em;text-transform:uppercase;color:var(--gold);font-weight:700;margin-bottom:.35rem}
.masthead h1{font-family:var(--sans);font-weight:800;font-size:1.7rem;line-height:1.12;margin:0}
.masthead .mast-right{min-width:0}
.masthead .kicker{font-family:var(--sans);color:#e7edf5;font-size:1.02rem;font-weight:600;margin-bottom:.5rem;white-space:nowrap}
.masthead .mast-disclaimer{font-family:var(--sans);color:#aebace;font-size:.82rem;line-height:1.5}
.provenance{display:flex;flex-wrap:wrap;justify-content:center;gap:8px 22px;font-family:var(--sans);font-size:.76rem;color:var(--muted);
  background:var(--navy-2);border-left:6px solid var(--gold);border-radius:0 0 12px 12px;padding:10px 30px}
.provenance.standalone{border-radius:12px}
.provenance span{white-space:nowrap}
.provenance b{color:var(--gold);font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:.68rem;margin-right:.35rem}
.question{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--gold);border-radius:10px;
  padding:16px 20px;margin:18px 0 24px;color:var(--muted);font-size:.98rem}
.question b{font-family:var(--sans);color:var(--navy);text-transform:uppercase;letter-spacing:.08em;font-size:.7rem;display:block;margin-bottom:.35rem}
.doc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:34px 40px;box-shadow:0 6px 22px rgba(20,35,60,.06)}
a{color:#1c4e86;text-decoration:none;border-bottom:1px solid #b9cbe4}
a:hover{border-bottom-color:#1c4e86}
code{font-family:var(--mono);font-size:.85em;background:#eef1f5;padding:.05em .4em;border-radius:5px;color:var(--navy-2)}
.toc{font-family:var(--sans);font-size:.85rem;background:var(--info-bg);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:0 0 22px}
.toc b{color:var(--navy);text-transform:uppercase;letter-spacing:.1em;font-size:.68rem;display:block;margin-bottom:.5rem}
.toc ol{margin:0;padding-left:1.2rem;columns:2;column-gap:28px;list-style:decimal}
.toc li{margin:.16rem 0;break-inside:avoid}
.toc li.lvl3{margin-left:.6rem;list-style:circle;font-size:.95em}
.toc a{border:none;color:#33414f}
.toc a:hover{color:var(--navy)}
/* narrative (rendered markdown) */
.narrative h1,.narrative h2{font-family:var(--sans);font-weight:800;color:var(--navy);line-height:1.2;
  padding-bottom:.45rem;border-bottom:2px solid var(--gold);margin:2rem 0 1rem;font-size:1.28rem}
.narrative h3{font-family:var(--sans);font-weight:800;color:var(--navy-2);margin:1.5rem 0 .6rem;font-size:1.08rem}
.narrative h4{font-family:var(--sans);font-weight:700;color:var(--navy-2);margin:1.2rem 0 .5rem;font-size:1rem}
.narrative p{margin:.7rem 0}
.narrative ul,.narrative ol{padding-left:1.3rem}
.narrative li{margin:.3rem 0}
.narrative strong{color:var(--navy-2)}
.narrative hr{border:none;border-top:1px solid var(--line);margin:1.6rem 0}
.narrative blockquote{margin:1rem 0;background:var(--info-bg);border:1px solid #d3e0f2;border-left:4px solid #1c4e86;
  border-radius:10px;padding:12px 18px;color:#22344b}
.narrative blockquote p{margin:.3rem 0}
.tablewrap{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:10px}
.narrative table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:.86rem}
.narrative thead th{background:var(--navy);color:#fff;text-align:left;font-weight:600;padding:10px 12px;white-space:nowrap}
.narrative tbody td{padding:9px 12px;border-top:1px solid var(--line);vertical-align:top}
.narrative tbody tr:nth-child(even){background:#f7f9fc}
.narrative tbody td:first-child{font-weight:600;color:var(--navy-2)}
/* badges */
.badge{font-family:var(--sans);font-size:.68rem;font-weight:700;letter-spacing:.04em;padding:.12em .55em;border-radius:999px;text-transform:uppercase;white-space:nowrap}
.badge.open{background:var(--danger-bg);color:var(--danger)}
.badge.pending{background:var(--warn-bg);color:var(--warn)}
.badge.resolved{background:var(--ok-bg);color:var(--ok)}
/* evidence */
#evidence{margin-top:30px;border-top:1px solid var(--line);padding-top:8px}
.ev-title{font-family:var(--sans);font-weight:800;color:var(--navy);font-size:1.16rem;
  padding-bottom:.5rem;border-bottom:2px solid var(--gold);margin:1.2rem 0 1rem}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;font-family:var(--sans);font-size:.8rem;color:var(--muted);margin:0 0 1rem}
.legend .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:.4rem;vertical-align:baseline}
.legend .dot.graph{background:var(--navy)}
.legend .dot.infer{background:var(--gold)}
.legend .dot.web{background:#6f8db3}
.refhead{font-family:var(--sans);font-weight:700;color:var(--navy);margin:1.3rem 0 .5rem;font-size:.9rem;text-transform:uppercase;letter-spacing:.06em}
.sources{padding-left:1.2rem}
.sources li{margin:.4rem 0}
.rr{font-size:.95rem}
.muted{color:var(--muted)}
.caveats{background:#f7f8fa;border:1px solid var(--line);border-radius:10px;padding:6px 20px}
.caveats .cav{padding:12px 0;border-top:1px solid var(--line);font-size:.92rem;color:#3b4757}
.caveats .cav:first-child{border-top:none}
.chip{font-family:var(--mono);font-size:.76rem;background:var(--navy);color:#fff;padding:.12em .5em;border-radius:5px}
.footer{text-align:center;color:var(--faint);font-family:var(--sans);font-size:.8rem;margin-top:34px}
.footer .brandline{display:inline-flex;align-items:center;gap:.5rem}
.footer .fdot{width:6px;height:6px;border-radius:50%;background:var(--gold)}
@media (max-width:640px){
  .doc{padding:22px 18px}
  .masthead{flex-direction:column;align-items:flex-start;gap:16px;padding:20px}
  .masthead h1{font-size:1.5rem}
  .masthead .logo{width:130px}
  .provenance,.disclaimer{padding-left:20px;padding-right:20px}
  .toc ol{columns:1}
}
@media print{
  body{background:#fff;font-size:11.5pt}
  .wrap{max-width:none;padding:0}
  .doc,.masthead,.tablewrap,.caveats,.question{box-shadow:none}
  .masthead{border-radius:0}
  .narrative h2,.narrative h3,#evidence,.narrative table,.caveats .cav{break-inside:avoid}
  thead th{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""
