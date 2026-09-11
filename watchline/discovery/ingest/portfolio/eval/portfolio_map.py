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

# Keyless raster basemaps, selectable with --basemap. Each is a MapLibre style fragment
# (sources + layers) injected verbatim. NOTE: OSM's CDN 403s tile requests that carry no Referer,
# so `osm` (the most detailed) can fail to load when the HTML is opened from disk (file://) in some
# browsers; `esri`/`esri-street` serve without a Referer requirement and are the safe fallbacks.
BASEMAPS: dict[str, dict] = {
    "osm": {  # most detailed; needs a browser that sends a Referer (works in Chrome from file://)
        "sources": {"osm": {"type": "raster", "tileSize": 256, "maxzoom": 19,
            "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            "attribution": "© OpenStreetMap contributors"}},
        "layers": [{"id": "osm", "type": "raster", "source": "osm"}],
        "note": "Base map © OpenStreetMap contributors.",
    },
    "esri": {  # clean light-gray canvas (base + labels); keyless, no Referer requirement
        "sources": {
            "esribase": {"type": "raster", "tileSize": 256, "maxzoom": 16,
                "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
                "attribution": "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors"},
            "esriref": {"type": "raster", "tileSize": 256, "maxzoom": 16,
                "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"]},
        },
        "layers": [{"id": "esribase", "type": "raster", "source": "esribase"},
                   {"id": "esriref", "type": "raster", "source": "esriref"}],
        "note": "Base map tiles © Esri.",
    },
    "esri-street": {  # detailed streets like OSM, but keyless and no Referer requirement
        "sources": {"esristreet": {"type": "raster", "tileSize": 256, "maxzoom": 19,
            "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"],
            "attribution": "Tiles © Esri — Esri, DeLorme, NAVTEQ"}},
        "layers": [{"id": "esristreet", "type": "raster", "source": "esristreet"}],
        "note": "Base map tiles © Esri.",
    },
}
DEFAULT_BASEMAP = "osm"

_Q_BUILDINGS = (
    "MATCH (p:Portfolio {portfolio_id:$pid})<-[:IN_PORTFOLIO]-(b:Building) "
    "WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL "
    "RETURN b.bbl AS bbl, b.address AS address, b.latitude AS lat, b.longitude AS lon, "
    "b.building_class AS bldgclass, b.residential_units AS units, b.year_built AS year, "
    "b.dof_ownername AS owner "
    "ORDER BY b.bbl"
)


def building_points(driver, portfolio_id: str) -> list[dict]:
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        return [dict(r) for r in s.run(_Q_BUILDINGS, pid=portfolio_id)]


# --- inverse mode: start from a WoW portfolio, split by WatchlineNYC owner identity ---

_Q_POINTS_BY_BBL = (
    "UNWIND $bbls AS bbl MATCH (b:Building {bbl:bbl}) "
    "WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL "
    "RETURN b.bbl AS bbl, b.address AS address, b.latitude AS lat, b.longitude AS lon, "
    "b.building_class AS bldgclass, b.residential_units AS units, b.year_built AS year, "
    "b.dof_ownername AS owner ORDER BY b.bbl"
)


def points_for_bbls(driver, bbls: list[str]) -> list[dict]:
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        return [dict(r) for r in s.run(_Q_POINTS_BY_BBL, bbls=[str(b).strip() for b in bbls])]


def wow_portfolio_bbls(pgc, orig_id: int | str) -> list[str]:
    cur = pgc.cursor()
    cur.execute("SELECT bbls FROM wow.wow_portfolios WHERE orig_id = %s", (int(orig_id),))
    row = cur.fetchone()
    return [str(b).strip() for b in (row[0] or [])] if row else []


# For each BBL, the WatchlineNYC owner unit: its OwnerGroup, or the singleton landlord (its own
# owner). A BBL touched by several landlords takes the dominant one (grouped first, then larger).
_Q_OWNERGROUP_SPLIT = (
    "UNWIND $bbls AS bbl MATCH (l:Landlord) WHERE bbl IN l.bbls "
    "OPTIONAL MATCH (l)-[:IN_OWNER_GROUP]->(og:OwnerGroup) "
    "RETURN bbl AS bbl, (og IS NOT NULL) AS grouped, "
    "  coalesce(og.owner_group_id, 'ACT:'+l.actor_id) AS gid, "
    "  coalesce(og.name, l.name) AS name, coalesce(og.building_count, size(l.bbls)) AS gsize"
)


def ownergroup_split(driver, bbls: list[str]) -> tuple[dict[str, str], dict[str, dict]]:
    """Return (bbl -> owner-unit id) and (id -> {count, name, singleton}) over `bbls`."""
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        rows = [dict(r) for r in s.run(_Q_OWNERGROUP_SPLIT, bbls=[str(b).strip() for b in bbls])]
    cand: dict[str, list] = defaultdict(list)
    for r in rows:
        cand[r["bbl"]].append((bool(r["grouped"]), r["gsize"] or 0, r["gid"], r["name"]))
    bbl2grp: dict[str, str] = {}
    labels: dict[str, dict] = defaultdict(lambda: {"count": 0, "name": "", "singleton": False})
    for bbl, opts in cand.items():
        grouped, _sz, gid, name = sorted(opts, key=lambda t: (t[0], t[1]), reverse=True)[0]
        bbl2grp[bbl] = gid
        lab = labels[gid]
        lab["count"] += 1
        lab["name"], lab["singleton"] = name, (not grouped)
    return bbl2grp, labels


def _ownergroup_legend(grp_color: dict[str, str], labels: dict[str, dict], n: int) -> tuple[str, str]:
    """Return (one_view_legend, split_view_legend) for the inverse map.

    one = the WoW side (a single portfolio); split = the WatchlineNYC owner units."""
    one = (f'<div class="row"><span class="dot" style="background:{PALETTE[0]}"></span>'
           f'One portfolio · {n} buildings</div>')
    rows = []
    for gid, color in grp_color.items():
        lab = labels.get(gid, {})
        tag = ' · <span style="color:#b23a2e">singleton (unmerged)</span>' if lab.get("singleton") else ""
        rows.append(f'<div class="row"><span class="dot" style="background:{color}"></span>'
                    f'<span class="nm">{lab.get("name","?")}</span> · {lab.get("count",0)} bldgs{tag}</div>')
    return one, "\n".join(rows)


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


_HPD_SQL = """
    SELECT g.bbl, c.type,
           coalesce(c.corporationname, trim(concat_ws(' ', c.firstname, c.lastname))) AS name,
           trim(concat_ws(' ', c.businesshousenumber, c.businessstreetname, c.businessapartment)) AS street,
           c.businesscity, c.businessstate, c.businesszip
    FROM hpd_contacts c
    JOIN hpd_registrations_grouped_by_bbl_with_contacts g ON g.registrationid = c.registrationid
    WHERE g.bbl = ANY(%s::text[]) AND c.type IN ('HeadOfficer','Officer','IndividualOwner','CorporateOwner')
"""
_HPD_PRIORITY = {"HeadOfficer": 0, "Officer": 1, "IndividualOwner": 2, "CorporateOwner": 3}


def hpd_officers(pgc, bbls: list[str]) -> dict[str, dict]:
    """bbl -> {officer, bizaddr} from HPD registration contacts, preferring the HeadOfficer."""
    want = [str(b).strip() for b in bbls]
    cur = pgc.cursor()
    cur.execute(_HPD_SQL, (want,))
    best: dict[str, tuple[int, str, str]] = {}  # bbl -> (priority, officer, bizaddr)
    for bbl, typ, name, street, city, state, zip_ in cur.fetchall():
        bbl = str(bbl).strip()
        if not name:
            continue
        locality = " ".join(x for x in (city, state, zip_) if x)
        bizaddr = ", ".join(x for x in ((street or "").strip(), locality) if x) or "—"
        pr = _HPD_PRIORITY.get(typ, 9)
        if bbl not in best or pr < best[bbl][0]:
            best[bbl] = (pr, name, bizaddr)
    return {b: {"officer": v[1], "bizaddr": v[2]} for b, v in best.items()}


def _assign_colors(bbl2pf: dict[str, str], points: list[dict]) -> dict[str, str]:
    """Map each WoW orig_id to a color: the portfolio holding the most of OUR buildings gets the
    majority blue; the rest cycle through the accent colors so strays stand out."""
    counts = Counter(bbl2pf[p["bbl"]] for p in points if p["bbl"] in bbl2pf)
    ordered = [pf for pf, _ in counts.most_common()]
    return {pf: PALETTE[i % len(PALETTE)] for i, pf in enumerate(ordered)}


def build_geojson(points: list[dict], bbl2pf: dict[str, str], pf_color: dict[str, str],
                  majority_pf: str | None, hpd: dict[str, dict] | None = None,
                  pf_label: dict[str, str] | None = None) -> dict:
    """`pf_label` optionally maps a group key to a friendlier tooltip label (e.g. an owner-group
    id -> the owner name); default shows the key itself. The property stays named ``wow_pf`` so the
    template is shared, but it means "the splitting system's group" in either direction."""
    hpd = hpd or {}
    feats = []
    for p in points:
        pf = bbl2pf.get(p["bbl"])
        h = hpd.get(p["bbl"], {})
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "bbl": p["bbl"],
                "address": p["address"] or p["bbl"],
                "bldgclass": p.get("bldgclass") or "?",
                "units": p.get("units") if p.get("units") is not None else "?",
                "year": p.get("year") or "?",
                "owner": p.get("owner") or "—",
                "officer": h.get("officer") or "—",
                "bizaddr": h.get("bizaddr") or "—",
                "wow_pf": ((pf_label or {}).get(pf, pf) if pf else None) or "—",
                "wow_color": pf_color.get(pf, NO_PF_COLOR) if pf else NO_PF_COLOR,
                "stray": bool(majority_pf) and pf != majority_pf,  # the split system carved it off
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
  .maplibregl-popup-content{font:13px/1.4 -apple-system,sans-serif;padding:9px 12px;border-radius:7px;
        box-shadow:0 2px 10px rgba(0,0,0,.18);}
  .maplibregl-popup-content b{font-size:.85rem;}
  .pp{color:#5b6570;font-family:ui-monospace,monospace;font-size:.72rem;}
  .tip .mrow{margin-top:4px;font-size:.78rem;color:var(--ink);}
  .tip .tag{background:var(--flag,#b23a2e);color:#fff;font-size:.66rem;padding:1px 5px;border-radius:3px;}
</style></head>
<body>
<div id="map"></div>
<div class="card">
  <h1>__HEADING__<small>__SUBHEAD__</small></h1>
  <div class="toggle">
    <button id="b-wl" class="on" onclick="setView('wl')">__BTN_ONE__</button>
    <button id="b-wow" onclick="setView('wow')">__BTN_SPLIT__</button>
  </div>
  <div class="legend" id="legend"></div>
  <div class="note">Coordinates: NYC DOF/PLUTO via the discovery graph. __SPLIT_NOTE__ __BM_NOTE__</div>
</div>
<script>
const DATA = __GEOJSON__;
const WL_COLOR = "__WL_COLOR__";
const LEGEND = {wl: `__WL_LEGEND__`, wow: `__WOW_LEGEND__`};
const DEFAULT_VIEW = "__DEFAULT_VIEW__";   // which view opens first: "wl" (single) or "wow" (split)

const map = new maplibregl.Map({
  container: "map",
  style: {version: 8, sources: __BM_SOURCES__, layers: __BM_LAYERS__},
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
  setView(DEFAULT_VIEW);   // paints + legend + button state for the opening view

  // Hover tooltip with building details.
  const tip = new maplibregl.Popup({closeButton:false, closeOnClick:false, offset:12,
                                    className:"tip", maxWidth:"280px"});
  map.on("mousemove","pts",e=>{
    map.getCanvas().style.cursor="pointer";
    const p = e.features[0].properties;
    const stray = (p.stray===true||p.stray==="true") ? ' <span class="tag">split-off</span>' : '';
    tip.setLngLat(e.lngLat).setHTML(
      `<b>${p.address}</b><br><span class="pp">BBL ${p.bbl}</span>`+
      `<div class="mrow">class ${p.bldgclass} · ${p.units} res units · built ${p.year}</div>`+
      `<div class="mrow">PLUTO owner: ${p.owner}</div>`+
      `<div class="mrow">HPD head officer: ${p.officer}</div>`+
      `<div class="mrow">Business addr: <span class="pp">${p.bizaddr}</span></div>`+
      `<div class="mrow">__SPLIT_TIP_LABEL__: ${p.wow_pf}${stray}</div>`
    ).addTo(map);
  });
  map.on("mouseleave","pts",()=>{map.getCanvas().style.cursor=""; tip.remove();});
  window._mapReady = true;   // hook for headless PNG export
});
// resolves once the map has finished rendering (tiles + paint settled)
window.mapIdle = () => new Promise(res => map.once("idle", res));
</script>
</body></html>
"""


def render_html(portfolio_id: str, geojson: dict, wl_legend: str, wow_legend: str,
                wl_color: str, n_wow_pfs: int, n: int, basemap: str = DEFAULT_BASEMAP, *,
                heading: str = "One owner, two answers", subhead: str | None = None,
                btn_one: str = "WatchlineNYC", btn_split: str = "Who Owns What",
                split_tip_label: str = "WoW portfolio", default_view: str = "wl",
                split_note: str = "WoW assignment: justfix <code>wow.wow_portfolios</code>.") -> str:
    """Render the shared map template. Defaults reproduce the merge view (one WatchlineNYC portfolio
    vs WoW's split). The keyword args flip the framing for the inverse view (one WoW portfolio vs
    WatchlineNYC's owner-identity split) without touching the merge path.

    Internal view keys are fixed: ``wl`` = the single-color ("one group") view, ``wow`` = the
    multi-color ("split") view. ``btn_one``/``btn_split`` are their button labels, and
    ``default_view`` picks which opens first."""
    bm = BASEMAPS[basemap]
    if subhead is None:
        subhead = (f"{n} buildings · WatchlineNYC = 1 portfolio · "
                   f"Who Owns What = {n_wow_pfs} portfolio{'s' if n_wow_pfs != 1 else ''}")
    return (_TEMPLATE
            .replace("__TITLE__", f"Portfolio map · {portfolio_id}")
            .replace("__HEADING__", heading)
            .replace("__SUBHEAD__", subhead)
            .replace("__GEOJSON__", json.dumps(geojson))
            .replace("__WL_COLOR__", wl_color)
            .replace("__WL_LEGEND__", wl_legend)
            .replace("__WOW_LEGEND__", wow_legend)
            .replace("__BTN_ONE__", btn_one)
            .replace("__BTN_SPLIT__", btn_split)
            .replace("__SPLIT_TIP_LABEL__", split_tip_label)
            .replace("__DEFAULT_VIEW__", default_view)
            .replace("__SPLIT_NOTE__", split_note)
            .replace("__BM_SOURCES__", json.dumps(bm["sources"]))
            .replace("__BM_LAYERS__", json.dumps(bm["layers"]))
            .replace("__BM_NOTE__", bm["note"]))


def generate(portfolio_id: str, out: Path, basemap: str = DEFAULT_BASEMAP) -> dict:
    driver = neo4j_driver()
    try:
        points = building_points(driver, portfolio_id)
    finally:
        driver.close()
    if not points:
        raise SystemExit(f"No geocoded buildings found for portfolio {portfolio_id}")

    pgc = pg_conn()
    try:
        bbls = [p["bbl"] for p in points]
        bbl2pf, labels = wow_split(pgc, bbls)
        hpd = hpd_officers(pgc, bbls)
    finally:
        pgc.close()

    pf_color = _assign_colors(bbl2pf, points)
    counts = Counter(bbl2pf[p["bbl"]] for p in points if p["bbl"] in bbl2pf)
    majority_pf = counts.most_common(1)[0][0] if counts else None
    geojson = build_geojson(points, bbl2pf, pf_color, majority_pf, hpd=hpd)
    wl_legend, wow_legend = _legend_html(pf_color, labels, majority_pf, PALETTE[0], len(points))
    html = render_html(portfolio_id, geojson, wl_legend, wow_legend, PALETTE[0],
                       len(pf_color), len(points), basemap=basemap)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return {"buildings": len(points), "wow_portfolios": len(pf_color),
            "unplaced": sum(1 for p in points if p["bbl"] not in bbl2pf), "out": str(out)}


def generate_wow_split(wow_orig_id: int | str, out: Path, basemap: str = DEFAULT_BASEMAP) -> dict:
    """Inverse of :func:`generate`: start from ONE WoW portfolio and show how WatchlineNYC's
    owner-identity layer splits it into distinct owners. The 'divergence runs both ways' view —
    for cases where WoW over-merges unrelated owners on a shared address (e.g. Abraham Miller /
    portfolio 183 / the 235 River Ave, Lakewood shared office)."""
    pgc = pg_conn()
    driver = neo4j_driver()
    try:
        bbls = wow_portfolio_bbls(pgc, wow_orig_id)
        if not bbls:
            raise SystemExit(f"No WoW portfolio with orig_id {wow_orig_id}")
        points = points_for_bbls(driver, bbls)
        if not points:
            raise SystemExit(f"No geocoded buildings for WoW portfolio {wow_orig_id}")
        pt_bbls = [p["bbl"] for p in points]
        bbl2grp, labels = ownergroup_split(driver, pt_bbls)
        hpd = hpd_officers(pgc, pt_bbls)
    finally:
        driver.close()
        pgc.close()

    grp_color = _assign_colors(bbl2grp, points)          # largest owner = blue, others cycle
    pf_label = {gid: lab["name"] for gid, lab in labels.items()}   # tooltip shows the owner name
    geojson = build_geojson(points, bbl2grp, grp_color, None, hpd=hpd, pf_label=pf_label)
    one_legend, split_legend = _ownergroup_legend(grp_color, labels, len(points))
    n_owners = len(grp_color)
    sub = (f"{len(points)} buildings · Who Owns What = 1 portfolio (#{wow_orig_id}) · "
           f"WatchlineNYC = {n_owners} owner{'s' if n_owners != 1 else ''}")
    html = render_html(
        f"wow-{wow_orig_id}", geojson, one_legend, split_legend, PALETTE[0], n_owners, len(points),
        basemap=basemap, heading="One portfolio, many owners", subhead=sub,
        btn_one="Who Owns What", btn_split="WatchlineNYC", split_tip_label="WatchlineNYC owner",
        default_view="wow",   # open on the reveal: WatchlineNYC's multi-owner split
        split_note="Owner identity: discovery graph <code>IN_OWNER_GROUP</code>.")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return {"buildings": len(points), "owner_groups": n_owners,
            "singletons": sum(1 for v in labels.values() if v["singleton"]), "out": str(out)}


def owner_group_bbls(driver, owner_group_id: str) -> list[str]:
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        r = s.run("MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:$g}) "
                  "UNWIND l.bbls AS bbl RETURN collect(DISTINCT bbl) AS bbls", g=owner_group_id).single()
    return [str(b).strip() for b in (r["bbls"] if r else [])]


def generate_owner_group(owner_group_id: str, out: Path, basemap: str = DEFAULT_BASEMAP) -> dict:
    """Forward map keyed on an OWNER GROUP (owner identity), not a Portfolio: one owner's buildings,
    colored by how Who Owns What splits them. Matches the demo's owner-identity number exactly
    (e.g. Croman's OG = 127 buildings, vs his nexus Portfolio's 135). WatchlineNYC = one owner."""
    driver = neo4j_driver()
    pgc = pg_conn()
    try:
        bbls = owner_group_bbls(driver, owner_group_id)
        if not bbls:
            raise SystemExit(f"No owner group with id {owner_group_id}")
        points = points_for_bbls(driver, bbls)
        if not points:
            raise SystemExit(f"No geocoded buildings for owner group {owner_group_id}")
        pt_bbls = [p["bbl"] for p in points]
        bbl2pf, labels = wow_split(pgc, pt_bbls)
        hpd = hpd_officers(pgc, pt_bbls)
    finally:
        driver.close()
        pgc.close()

    pf_color = _assign_colors(bbl2pf, points)
    counts = Counter(bbl2pf[p["bbl"]] for p in points if p["bbl"] in bbl2pf)
    majority_pf = counts.most_common(1)[0][0] if counts else None
    geojson = build_geojson(points, bbl2pf, pf_color, majority_pf, hpd=hpd)
    _, wow_legend = _legend_html(pf_color, labels, majority_pf, PALETTE[0], len(points))
    one_legend = (f'<div class="row"><span class="dot" style="background:{PALETTE[0]}"></span>'
                  f'One owner · {len(points)} buildings</div>')
    n_wow = len(pf_color)
    sub = (f"{len(points)} buildings · WatchlineNYC = 1 owner · "
           f"Who Owns What = {n_wow} portfolio{'s' if n_wow != 1 else ''}")
    html = render_html(
        owner_group_id, geojson, one_legend, wow_legend, PALETTE[0], n_wow, len(points),
        basemap=basemap, heading="One owner, scattered across the record", subhead=sub,
        btn_one="WatchlineNYC", btn_split="Who Owns What", split_tip_label="WoW portfolio",
        default_view="wl")   # open on the unified owner; toggle reveals WoW's fragments

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return {"buildings": len(points), "wow_portfolios": n_wow,
            "unplaced": sum(1 for p in points if p["bbl"] not in bbl2pf), "out": str(out)}


def render_png(html_path: Path, scale: int = 2, width: int = 1600, height: int = 1200, *,
               views: tuple[tuple[str, str], ...] = (("wl", "watchline"), ("wow", "wow"))) -> list[Path]:
    """Headless-render both views of an emitted map HTML to slide-ready PNGs (needs Playwright).

    Writes  <stem>-watchline.png  and  <stem>-wow.png  beside the HTML. The toggle chrome is hidden;
    the heading + legend remain (the legend carries the counts and the fracturing address variants).

    ``views`` maps each internal view key to its filename suffix. Default is the merge convention
    (``wl`` = WatchlineNYC's one portfolio, ``wow`` = WoW's split); the inverse map flips it so that
    ``-watchline`` still names WatchlineNYC's answer (the owner split) in either direction.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as e:
        raise SystemExit(
            "PNG export needs Playwright. Install it once:\n"
            "  uv run --with playwright python -m playwright install chromium\n"
            "then re-run with:  uv run --with playwright python -m "
            "watchline.discovery.ingest.portfolio.eval.portfolio_map ... --png") from e

    url = html_path.resolve().as_uri()
    outs: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        page.goto(url)
        page.wait_for_function("() => window._mapReady === true", timeout=30000)
        page.add_style_tag(content=".toggle{display:none!important}")
        for view, suffix in views:
            page.evaluate(f"() => setView('{view}')")
            page.evaluate("() => window.mapIdle()")   # await tiles + paint
            page.wait_for_timeout(600)                # small settle for raster tiles
            out = html_path.with_name(f"{html_path.stem}-{suffix}.png")
            page.screenshot(path=str(out))
            outs.append(out)
        browser.close()
    return outs


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a WoW-vs-WatchlineNYC portfolio comparison map.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--portfolio", help="WatchlineNYC portfolio_id (merge view: 1 WL portfolio vs WoW's split)")
    src.add_argument("--owner-group", dest="owner_group",
                     help="WatchlineNYC owner_group_id (merge view keyed on owner IDENTITY: 1 owner vs WoW's split)")
    src.add_argument("--wow-portfolio", dest="wow_portfolio",
                     help="WoW orig_id (inverse view: 1 WoW portfolio vs WatchlineNYC's owner split)")
    ap.add_argument("--out", type=Path, default=None, help="output .html (default eval_out/maps/<id>.html)")
    ap.add_argument("--basemap", choices=list(BASEMAPS), default=DEFAULT_BASEMAP,
                    help="base map tiles (default osm = most detailed; esri/esri-street load from "
                         "file:// without a Referer if osm shows 403)")
    ap.add_argument("--png", action="store_true", help="also export slide-ready PNGs of both views (Playwright)")
    ap.add_argument("--scale", type=int, default=2, help="PNG device-scale factor (default 2 = retina)")
    args = ap.parse_args()

    if args.wow_portfolio:
        out = args.out or Path("eval_out/maps") / f"wow-{args.wow_portfolio}.html"
        info = generate_wow_split(args.wow_portfolio, out, basemap=args.basemap)
        print(f"wrote {info['out']}  ({info['buildings']} buildings, "
              f"WatchlineNYC = {info['owner_groups']} owner(s), {info['singletons']} singleton(s))")
    elif args.owner_group:
        out = args.out or Path("eval_out/maps") / f"{args.owner_group}.html"
        info = generate_owner_group(args.owner_group, out, basemap=args.basemap)
        print(f"wrote {info['out']}  ({info['buildings']} buildings, WatchlineNYC = 1 owner, "
              f"{info['wow_portfolios']} WoW portfolio(s), {info['unplaced']} not in any WoW portfolio)")
    else:
        out = args.out or Path("eval_out/maps") / f"{args.portfolio}.html"
        info = generate(args.portfolio, out, basemap=args.basemap)
        print(f"wrote {info['out']}  ({info['buildings']} buildings, "
              f"{info['wow_portfolios']} WoW portfolio(s), {info['unplaced']} not in any WoW portfolio)")
    if args.png:
        # Inverse map flips which internal view is WatchlineNYC's, so flip the suffixes too:
        # -watchline always names WatchlineNYC's answer (the owner split), -wow names WoW's.
        views = (("wl", "wow"), ("wow", "watchline")) if args.wow_portfolio \
            else (("wl", "watchline"), ("wow", "wow"))
        for p in render_png(out, scale=args.scale, views=views):
            print(f"wrote {p}")


if __name__ == "__main__":
    main()
