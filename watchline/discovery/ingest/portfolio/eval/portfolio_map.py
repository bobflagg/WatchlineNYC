"""eval/portfolio_map.py — render a WoW-vs-WatchlineNYC comparison map for one portfolio.

Read-only. Given a WatchlineNYC portfolio_id, pulls every member building's coordinates from the
discovery graph and the Who-Owns-What portfolio assignment for those same BBLs from the justfix
`wow` schema, then emits ONE self-contained HTML file: a MapLibre GL JS map with a toggle between

  * "WatchlineNYC"    — all buildings one color (our answer: one portfolio)
  * "Who Owns What"   — buildings colored by their WoW portfolio (WoW's answer: often several)

Buildings that WoW splits off from the majority (the "strays") are emphasized, and the legend
surfaces the WoW landlord name + business-address variants — which is where data-entry noise
(e.g. a mistyped address) fractures WoW's registration-contact graph.

This is a PRESENTATION / EVAL artifact and deliberately shows both systems' answers side by side.
It must NOT live in the blind reviewer tool (owner-review), whose contract forbids revealing any
system decision. Open the emitted file in a browser (external map tiles load from CARTO/OSM); it is
not meant to be published as a sandboxed Artifact, which blocks external tiles.

Uses MapLibre GL JS (BSD, open-source, no token) — NOT the proprietary Mapbox GL JS.

    uv run python -m watchline.discovery.ingest.portfolio.eval.portfolio_map \
        --portfolio PF-20260901T165123Z-77675 --out eval_out/maps/escobar.html

Needs .env (NEO4J_* and PG*), same as the other eval scripts.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE, pg_conn

# Categorical palette. Index 0 is the "majority / WatchlineNYC" blue; the rest mark WoW strays.
PALETTE = ["#2563eb", "#dc2626", "#d97706", "#059669", "#7c3aed", "#0891b2", "#db2777", "#65a30d"]
NO_PF_COLOR = "#9ca3af"  # a building WoW never placed in any portfolio

_Q_BUILDINGS = (
    "MATCH (p:Portfolio {portfolio_id:$pid})<-[:IN_PORTFOLIO]-(b:Building) "
    "WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL "
    "RETURN b.bbl AS bbl, b.address AS address, b.latitude AS lat, b.longitude AS lon "
    "ORDER BY b.bbl"
)


def building_points(driver, portfolio_id: str) -> list[dict]:
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        return [dict(r) for r in s.run(_Q_BUILDINGS, pid=portfolio_id)]


def wow_split(pgc, bbls: list[str]) -> tuple[dict[str, str], dict[str, dict]]:
    """Return (bbl -> wow orig_id) and (orig_id -> {count, names, bizaddrs}) restricted to `bbls`."""
    want = {str(b).strip() for b in bbls}
    cur = pgc.cursor()
    cur.execute("SELECT orig_id, bbls FROM wow.wow_portfolios WHERE bbls && %s::text[]", (list(want),))
    bbl2pf: dict[str, str] = {}
    for orig_id, pbbls in cur.fetchall():
        for b in (pbbls or []):
            b = str(b).strip()
            if b in want:
                bbl2pf[b] = str(orig_id)

    # Landlord name + business-address variants per portfolio (surfaces the fracturing typo).
    labels: dict[str, dict] = defaultdict(lambda: {"count": 0, "names": Counter(), "bizaddrs": Counter()})
    cur.execute(
        "SELECT bbl, upper(name), upper(bizaddr) FROM wow.wow_landlords WHERE bbl = ANY(%s::text[])",
        (list(want),),
    )
    seen_bbl_pf: set[tuple[str, str]] = set()
    for bbl, name, bizaddr in cur.fetchall():
        pf = bbl2pf.get(str(bbl).strip())
        if not pf:
            continue
        lab = labels[pf]
        if name:
            lab["names"][name] += 1
        if bizaddr:
            lab["bizaddrs"][bizaddr] += 1
        if (str(bbl), pf) not in seen_bbl_pf:
            seen_bbl_pf.add((str(bbl), pf))
            lab["count"] += 1
    return bbl2pf, labels


def _assign_colors(bbl2pf: dict[str, str], points: list[dict]) -> dict[str, str]:
    """Map each WoW orig_id to a color: the portfolio holding the most of OUR buildings gets the
    majority blue; the rest cycle through the accent colors so strays stand out."""
    counts = Counter(bbl2pf[p["bbl"]] for p in points if p["bbl"] in bbl2pf)
    ordered = [pf for pf, _ in counts.most_common()]
    return {pf: PALETTE[i % len(PALETTE)] for i, pf in enumerate(ordered)}


def build_geojson(points: list[dict], bbl2pf: dict[str, str], pf_color: dict[str, str],
                  majority_pf: str | None) -> dict:
    feats = []
    for p in points:
        pf = bbl2pf.get(p["bbl"])
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "bbl": p["bbl"],
                "address": p["address"] or p["bbl"],
                "wow_pf": pf or "—",
                "wow_color": pf_color.get(pf, NO_PF_COLOR) if pf else NO_PF_COLOR,
                "stray": bool(majority_pf) and pf != majority_pf,  # WoW split it off (or never placed it)
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def _legend_html(pf_color: dict[str, str], labels: dict[str, dict], majority_pf: str | None,
                 wl_color: str, n: int) -> tuple[str, str]:
    """Return (watchline_legend_html, wow_legend_html)."""
    wl = (f'<div class="row"><span class="dot" style="background:{wl_color}"></span>'
          f'One portfolio · {n} buildings</div>')
    rows = []
    for pf, color in pf_color.items():
        lab = labels.get(pf, {})
        name = (lab.get("names").most_common(1)[0][0] if lab.get("names") else "")
        addrs = [a for a, _ in lab.get("bizaddrs", Counter()).most_common(4)]
        tag = " · split-off" if (majority_pf and pf != majority_pf) else ""
        addr_html = "<br>".join(f'<span class="addr">{a}</span>' for a in addrs)
        rows.append(
            f'<div class="row"><span class="dot" style="background:{color}"></span>'
            f'WoW #{pf} · {lab.get("count", 0)} bldgs{tag}<br>'
            f'<span class="nm">{name}</span><br>{addr_html}</div>')
    return wl, "\n".join(rows)


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  :root{--ink:#1a2129;--soft:#5b6570;--line:#d9ddd6;--panel:#fff;}
  html,body{margin:0;height:100%;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);}
  #map{position:absolute;inset:0;}
  .card{position:absolute;top:12px;left:12px;z-index:2;background:var(--panel);border:1px solid var(--line);
        border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.12);max-width:320px;overflow:hidden;}
  .card h1{font-size:.95rem;margin:0;padding:11px 14px;border-bottom:1px solid var(--line);}
  .card h1 small{display:block;color:var(--soft);font-weight:400;font-size:.72rem;margin-top:2px;}
  .toggle{display:flex;padding:10px 14px 6px;gap:8px;}
  .toggle button{flex:1;font:inherit;font-size:.8rem;padding:7px 4px;border:1px solid var(--line);
        background:#f6f7f4;color:var(--ink);border-radius:6px;cursor:pointer;}
  .toggle button.on{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600;}
  .legend{padding:4px 14px 12px;max-height:46vh;overflow-y:auto;}
  .legend .row{font-size:.78rem;margin:8px 0;padding-left:20px;position:relative;color:var(--ink);}
  .legend .dot{position:absolute;left:0;top:2px;width:12px;height:12px;border-radius:50%;
        border:1px solid rgba(0,0,0,.35);}
  .legend .nm{color:var(--ink);font-weight:600;}
  .legend .addr{color:var(--soft);font-family:ui-monospace,monospace;font-size:.72rem;}
  .note{padding:0 14px 12px;font-size:.72rem;color:var(--soft);}
  .maplibregl-popup-content{font:13px/1.4 -apple-system,sans-serif;}
  .maplibregl-popup-content b{font-size:.82rem;}
  .pp{color:#5b6570;font-family:ui-monospace,monospace;font-size:.72rem;}
</style></head>
<body>
<div id="map"></div>
<div class="card">
  <h1>__HEADING__<small>__SUBHEAD__</small></h1>
  <div class="toggle">
    <button id="b-wl" class="on" onclick="setView('wl')">WatchlineNYC</button>
    <button id="b-wow" onclick="setView('wow')">Who Owns What</button>
  </div>
  <div class="legend" id="legend"></div>
  <div class="note">Coordinates: NYC DOF/PLUTO via the discovery graph. WoW assignment: justfix
    <code>wow.wow_portfolios</code>. Base map © OpenStreetMap contributors.</div>
</div>
<script>
const DATA = __GEOJSON__;
const WL_COLOR = "__WL_COLOR__";
const LEGEND = {wl: `__WL_LEGEND__`, wow: `__WOW_LEGEND__`};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {osm: {type:"raster",
      tiles:["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize:256, maxzoom:19, attribution:"© OpenStreetMap contributors"}},
    layers: [{id:"osm",type:"raster",source:"osm"}]
  },
  center:[-73.9,40.84], zoom:11
});
map.addControl(new maplibregl.NavigationControl({showCompass:false}), "top-right");

function setView(v){
  document.getElementById("b-wl").classList.toggle("on", v==="wl");
  document.getElementById("b-wow").classList.toggle("on", v==="wow");
  document.getElementById("legend").innerHTML = LEGEND[v];
  const color = v==="wl" ? WL_COLOR : ["get","wow_color"];
  const radius = v==="wow"
    ? ["interpolate",["linear"],["zoom"], 10,["case",["get","stray"],7,5], 15,["case",["get","stray"],13,9]]
    : ["interpolate",["linear"],["zoom"], 10,5, 15,9];
  const stroke = v==="wow" ? ["case",["get","stray"],2.2,1] : 1;
  map.setPaintProperty("pts","circle-color",color);
  map.setPaintProperty("pts","circle-radius",radius);
  map.setPaintProperty("pts","circle-stroke-width",stroke);
}

map.on("load", ()=>{
  map.addSource("pts",{type:"geojson",data:DATA});
  map.addLayer({id:"pts",type:"circle",source:"pts",
    paint:{"circle-color":WL_COLOR,"circle-radius":6,
           "circle-stroke-width":1,"circle-stroke-color":"#fff","circle-opacity":.92}});
  // fit to all buildings
  const b = new maplibregl.LngLatBounds();
  DATA.features.forEach(f=>b.extend(f.geometry.coordinates));
  if(!b.isEmpty()) map.fitBounds(b,{padding:70,maxZoom:15});
  document.getElementById("legend").innerHTML = LEGEND.wl;

  const pop = new maplibregl.Popup({closeButton:false,closeOnClick:true});
  map.on("click","pts",e=>{
    const p = e.features[0].properties;
    pop.setLngLat(e.lngLat).setHTML(
      `<b>${p.address}</b><br><span class="pp">BBL ${p.bbl}</span><br>`+
      `WoW portfolio: ${p.wow_pf}${p.stray==="true"||p.stray===true?" · split-off":""}`
    ).addTo(map);
  });
  map.on("mouseenter","pts",()=>map.getCanvas().style.cursor="pointer");
  map.on("mouseleave","pts",()=>map.getCanvas().style.cursor="");
});
</script>
</body></html>
"""


def render_html(portfolio_id: str, geojson: dict, wl_legend: str, wow_legend: str,
                wl_color: str, n_wow_pfs: int, n: int) -> str:
    sub = (f"{n} buildings · WatchlineNYC = 1 portfolio · "
           f"Who Owns What = {n_wow_pfs} portfolio{'s' if n_wow_pfs != 1 else ''}")
    return (_TEMPLATE
            .replace("__TITLE__", f"Portfolio map · {portfolio_id}")
            .replace("__HEADING__", "One owner, two answers")
            .replace("__SUBHEAD__", sub)
            .replace("__GEOJSON__", json.dumps(geojson))
            .replace("__WL_COLOR__", wl_color)
            .replace("__WL_LEGEND__", wl_legend)
            .replace("__WOW_LEGEND__", wow_legend))


def generate(portfolio_id: str, out: Path) -> dict:
    driver = neo4j_driver()
    try:
        points = building_points(driver, portfolio_id)
    finally:
        driver.close()
    if not points:
        raise SystemExit(f"No geocoded buildings found for portfolio {portfolio_id}")

    pgc = pg_conn()
    try:
        bbl2pf, labels = wow_split(pgc, [p["bbl"] for p in points])
    finally:
        pgc.close()

    pf_color = _assign_colors(bbl2pf, points)
    counts = Counter(bbl2pf[p["bbl"]] for p in points if p["bbl"] in bbl2pf)
    majority_pf = counts.most_common(1)[0][0] if counts else None
    geojson = build_geojson(points, bbl2pf, pf_color, majority_pf)
    wl_legend, wow_legend = _legend_html(pf_color, labels, majority_pf, PALETTE[0], len(points))
    html = render_html(portfolio_id, geojson, wl_legend, wow_legend, PALETTE[0], len(pf_color), len(points))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return {"buildings": len(points), "wow_portfolios": len(pf_color),
            "unplaced": sum(1 for p in points if p["bbl"] not in bbl2pf), "out": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a WoW-vs-WatchlineNYC portfolio comparison map.")
    ap.add_argument("--portfolio", required=True, help="WatchlineNYC portfolio_id")
    ap.add_argument("--out", type=Path, default=None, help="output .html (default eval_out/maps/<pid>.html)")
    args = ap.parse_args()
    out = args.out or Path("eval_out/maps") / f"{args.portfolio}.html"
    info = generate(args.portfolio, out)
    print(f"wrote {info['out']}  ({info['buildings']} buildings, "
          f"{info['wow_portfolios']} WoW portfolio(s), {info['unplaced']} not in any WoW portfolio)")


if __name__ == "__main__":
    main()
