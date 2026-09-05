"""Hermetic tests for the pure map-rendering helpers (no DB, no network)."""
from __future__ import annotations

import json
from collections import Counter

import pytest

pytest.importorskip("psycopg2")  # portfolio_map imports the pg connection helper at module load
from watchline.discovery.ingest.portfolio.eval import portfolio_map as M

# A tiny stand-in for the Escobar shape: a majority WoW portfolio plus a split-off "stray".
_POINTS = [
    {"bbl": "b1", "address": "1 A ST", "lat": 40.85, "lon": -73.90},
    {"bbl": "b2", "address": "2 A ST", "lat": 40.86, "lon": -73.91},
    {"bbl": "b3", "address": "3 A ST", "lat": 40.87, "lon": -73.92},  # the stray
    {"bbl": "b4", "address": "4 A ST", "lat": 40.88, "lon": -73.93},  # never placed by WoW
]
_BBL2PF = {"b1": "700", "b2": "700", "b3": "701"}  # b4 absent -> unplaced


def test_assign_colors_majority_gets_blue():
    colors = M._assign_colors(_BBL2PF, _POINTS)
    assert colors["700"] == M.PALETTE[0]      # majority (2 bldgs) -> index-0 blue
    assert colors["701"] != M.PALETTE[0]      # stray -> a distinct accent
    assert set(colors) == {"700", "701"}      # only portfolios that hold our buildings


def test_build_geojson_marks_strays_and_unplaced():
    colors = M._assign_colors(_BBL2PF, _POINTS)
    gj = M.build_geojson(_POINTS, _BBL2PF, colors, majority_pf="700")
    props = {f["properties"]["bbl"]: f["properties"] for f in gj["features"]}

    assert gj["type"] == "FeatureCollection" and len(gj["features"]) == 4
    # coordinates are [lon, lat] for GeoJSON
    assert props["b1"]["stray"] is False
    assert props["b3"]["stray"] is True                      # different WoW portfolio
    assert props["b4"]["stray"] is True and props["b4"]["wow_pf"] == "—"
    assert props["b4"]["wow_color"] == M.NO_PF_COLOR         # unplaced -> grey
    f1 = next(f for f in gj["features"] if f["properties"]["bbl"] == "b1")
    assert f1["geometry"]["coordinates"] == [-73.90, 40.85]


def test_legend_surfaces_bizaddr_variants():
    colors = M._assign_colors(_BBL2PF, _POINTS)
    labels = {
        "700": {"count": 2, "names": Counter({"RAMON ESCOBAR": 2}),
                "bizaddrs": Counter({"2432 GRAND CONCOURSE 504": 2})},
        "701": {"count": 1, "names": Counter({"RAMON ESCOBAR": 1}),
                "bizaddrs": Counter({"2432 GRAND COURSE 504": 1})},  # the fracturing typo
    }
    wl, wow = M._legend_html(colors, labels, majority_pf="700", wl_color=M.PALETTE[0], n=4)
    assert "One portfolio · 4 buildings" in wl
    assert "GRAND COURSE 504" in wow          # typo variant is shown to the audience
    assert "split-off" in wow                 # the stray portfolio is flagged


def test_render_html_is_self_contained_and_embeds_data():
    colors = M._assign_colors(_BBL2PF, _POINTS)
    gj = M.build_geojson(_POINTS, _BBL2PF, colors, majority_pf="700")
    html = M.render_html("PF-TEST", gj, "WL", "WOW", M.PALETTE[0], n_wow_pfs=2, n=4)
    assert "__GEOJSON__" not in html and "__WL_LEGEND__" not in html   # every token substituted
    assert json.dumps(gj) in html                                     # data baked into the file
    assert "maplibre-gl" in html and "mapbox-gl" not in html          # open-source lib, not proprietary
    assert "__BM_SOURCES__" not in html and "__BM_NOTE__" not in html  # basemap tokens substituted


def test_basemap_selection_swaps_tile_host():
    colors = M._assign_colors(_BBL2PF, _POINTS)
    gj = M.build_geojson(_POINTS, _BBL2PF, colors, majority_pf="700")
    kw = dict(wl_legend="WL", wow_legend="WOW", wl_color=M.PALETTE[0], n_wow_pfs=2, n=4)
    osm = M.render_html("PF", gj, **kw, basemap="osm")
    esri = M.render_html("PF", gj, **kw, basemap="esri")
    assert "tile.openstreetmap.org" in osm and "arcgisonline" not in osm
    assert "server.arcgisonline.com" in esri and "openstreetmap.org/{z}" not in esri
    assert M.DEFAULT_BASEMAP == "osm" and set(M.BASEMAPS) >= {"osm", "esri", "esri-street"}
