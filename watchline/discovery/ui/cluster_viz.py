"""Render a resolved-operator cluster as a self-contained network diagram.

Pure and deterministic: takes the ``top_operator`` payload from the operator
analysis (records + ``name_edges`` + portfolio) and emits a standalone HTML page
with an inline SVG — no JavaScript, no external hosts (same offline discipline as
the HTML report). Rendered in the artifact panel via ``st.iframe``.

The picture: one **operator** at the centre; its landlord **records** on a ring,
sized by buildings controlled (empty alias records are small and dashed). Gold
lines are the graph's own ``CONNECTED_BY_NAME`` links; a record with no gold line
was pulled in by exact-name resolution — which is the point the reconciliation
makes visible.
"""

from __future__ import annotations

import html
import math
from typing import Any

_NAVY = "#0a1629"
_NAVY2 = "#12243f"
_GOLD = "#d4a017"


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _svg(cluster: dict[str, Any]) -> str:
    records = list(cluster.get("records", []))
    edges = list(cluster.get("name_edges", []))
    w, h = 820, 520
    cx, cy = w / 2, 250.0
    ring = 165.0
    n = max(len(records), 1)
    max_b = max([r.get("buildings", 0) for r in records] + [1])

    pos: dict[str, tuple[float, float]] = {}
    membership, nodes = [], []
    for i, rec in enumerate(records):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        x, y = cx + ring * math.cos(ang), cy + ring * math.sin(ang)
        pos[rec.get("actor_id")] = (x, y)
        b = int(rec.get("buildings", 0) or 0)
        r = 15 + 26 * math.sqrt(b / max_b) if b else 12
        fill = _NAVY2 if b else "#22344b"
        dash = "" if b else 'stroke-dasharray="3 3" '
        membership.append(
            f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{x:.0f}" y2="{y:.0f}" '
            f'stroke="#cdd6e2" stroke-width="1.2"/>')
        short = _esc(str(rec.get("actor_id", "")).replace("ACT-LL-", "#"))
        nodes.append(
            f'<g opacity="{1 if b else 0.6}">'
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="{fill}" '
            f'stroke="{_GOLD}" stroke-width="{2 if b else 1}" {dash}/>'
            f'<text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" fill="#fff" '
            f'font-size="{13 if b else 11}" font-weight="700">{b}</text>'
            f'<text x="{x:.0f}" y="{y + r + 14:.0f}" text-anchor="middle" fill="#2b3a4f" '
            f'font-size="10" font-weight="600">{short}</text></g>')

    name_lines = []
    for e in edges:
        s, t = pos.get(e.get("source")), pos.get(e.get("target"))
        if s and t:
            name_lines.append(
                f'<line x1="{s[0]:.0f}" y1="{s[1]:.0f}" x2="{t[0]:.0f}" y2="{t[1]:.0f}" '
                f'stroke="{_GOLD}" stroke-width="2.4"/>')

    operator = (
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="34" fill="{_NAVY}" stroke="{_GOLD}" stroke-width="3"/>'
        f'<text x="{cx:.0f}" y="{cy - 3:.0f}" text-anchor="middle" fill="{_GOLD}" '
        f'font-size="10" font-weight="800" letter-spacing="1.5">OPERATOR</text>'
        f'<text x="{cx:.0f}" y="{cy + 12:.0f}" text-anchor="middle" fill="#fff" '
        f'font-size="11" font-weight="700">{int(cluster.get("buildings", 0))} bldgs</text>'
        f'<text x="{cx:.0f}" y="{cy + 62:.0f}" text-anchor="middle" fill="{_NAVY}" '
        f'font-size="15" font-weight="800">{_esc(cluster.get("name"))}</text>')

    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'
        f'{"".join(membership)}{"".join(name_lines)}{operator}{"".join(nodes)}</svg>')


def to_html(cluster: dict[str, Any], *, branded: bool = True) -> str:
    """A self-contained HTML page with the cluster network diagram + a summary."""
    records = cluster.get("records", [])
    events = cluster.get("events", []) or []
    ev = " · ".join(f"{_esc(e['event_type'])} {int(e['events']):,}" for e in events[:5])
    stat = (
        f'<b>{int(cluster.get("buildings", 0))}</b> buildings &nbsp;·&nbsp; '
        f'<b>{int(cluster.get("residential_units", 0)):,}</b> residential units &nbsp;·&nbsp; '
        f'<b>{int(cluster.get("rent_stabilized_units", 0)):,}</b> rent-stabilized &nbsp;·&nbsp; '
        f'<b>{len(records)}</b> records unified')
    header = (
        '<div class="mast"><div class="eyebrow">Resolved operator · identity network</div>'
        f'<h1>{_esc(cluster.get("name"))}</h1></div>' if branded else "")
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Resolved operator — identity network</title><style>"
        "*{box-sizing:border-box}body{margin:0;background:#eef1f5;color:#1b2430;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        ".wrap{max-width:900px;margin:0 auto;padding:14px 16px 26px}"
        f".mast{{background:linear-gradient(180deg,{_NAVY},{_NAVY2});border-left:6px solid {_GOLD};"
        "border-radius:12px 12px 0 0;padding:16px 24px;color:#fff}"
        f".mast .eyebrow{{font-size:.6rem;letter-spacing:.24em;text-transform:uppercase;color:{_GOLD};font-weight:700}}"
        ".mast h1{margin:.2rem 0 0;font-size:1.5rem;font-weight:800}"
        ".card{background:#fff;border:1px solid #e3e7ee;border-radius:0 0 12px 12px;padding:8px 10px 4px}"
        ".stat{font-size:.9rem;color:#3a4658;padding:10px 14px}"
        ".stat b{color:#0a1629}"
        ".events{font-size:.78rem;color:#5c6b80;padding:0 14px 8px}"
        f".legend{{font-size:.72rem;color:#5c6b80;padding:8px 14px;border-top:1px solid #eef1f5}}"
        f".legend .k{{display:inline-block;width:10px;height:10px;border-radius:50%;background:{_NAVY2};"
        f"border:2px solid {_GOLD};vertical-align:middle;margin:0 4px}}"
        f".legend .g{{display:inline-block;width:16px;height:0;border-top:3px solid {_GOLD};vertical-align:middle;margin:0 4px}}"
        "</style></head><body><div class=\"wrap\">"
        f"{header}<div class=\"card\">{_svg(cluster)}</div>"
        f'<div class="stat">{stat}</div>'
        + (f'<div class="events">Portfolio event fingerprint — {ev}</div>' if ev else "")
        + '<div class="legend"><span class="k"></span> landlord record (sized by buildings; '
        'dashed = empty alias) &nbsp;&nbsp; <span class="g"></span> shared name-link '
        '(graph-verified); records with no gold line were unified by exact name.</div>'
        "</div></body></html>")
