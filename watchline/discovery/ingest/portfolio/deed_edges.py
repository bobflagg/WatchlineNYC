"""CONNECTED_BY_DEED — the ACRIS multi-parcel-deed co-ownership edge (name-free veil-pierce).

Buildings conveyed on ONE ACRIS deed share a grantee, so they have the same owner — regardless of
what their individual LLCs are named. This is the ONLY signal that pierces the sophisticated shell
game (one owner, many differently-named single-purpose LLCs): name-anchored Splink and the exact
registered-LLC edge both keep those LLCs apart, but a shared deed proves them one owner. Validated
on PF-...739 (Williamsburg): it merged a 22-building bundle spanning 17 different LLC names, and the
"175 REALTY ASSOCIATES I/II/IV" numbered shells — links nothing else in the KG could make.

A SPECIALIST signal, by design: most buildings are bought individually (own deed), so it is sparse
(only the co-conveyed portfolios link). It feeds the OWNERSHIP layer only (owner_groups reads
CONNECTED_BY_SPLINK|CONNECTED_BY_DEED), never the address-nexus Portfolio — deeds are ownership
evidence, not an operational nexus.

STALENESS GUARD — use each building's LATEST deed, not any deed. Two buildings are grouped only when
their *most recent* conveyance is the SAME multi-parcel deed: if a building was co-bought long ago
but never re-sold, that old deed is still its latest, so the co-ownership stands (captures PF-...739's
older bundles); if it was re-sold since, it has a newer latest deed and drops out (no stale merge).
This replaces a date cutoff, which would wrongly drop old-but-held bundles and keep recent-but-sold ones.

DEED-HUB CAP — a landlord on more than DEED_HUB_CAP distinct multi-parcel deeds is a serial co-investor
whose transitive links would over-merge unrelated parties (Aaron Feldman doing separate JVs with many
partners = the deed analogue of the aggregator megaoffice). Such hub nodes are dropped from the cliques
(precision-safe: drops edges, never adds a wrong one).

Scope: doctype ILIKE '%DEED%' (the 8 conveyance subtypes), 2..MAX_PARCELS lots (mega-deeds are
bulk/institutional transfers), institutional grantees (HDFC/NYCHA/City) excluded. One clique per deed
over the co-conveyed buildings' landlord nodes (star above STAR_ABOVE to bound edges).

Node mapping is the same explode-join on ``bbl`` that splink_bridge/llc_edges use. Neo4j-free;
returns ``(src_nodeid, dst_nodeid, weight)`` so pipeline.py loads it as CONNECTED_BY_DEED.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from watchline.discovery.ingest.portfolio.splink_bridge import SPLINK_WEIGHT, STAR_ABOVE
from watchline.discovery.ingest.portfolio.curated_owners import _clique_rows

DEED_METHOD = "acris-deed"

# A deed conveying more lots than this is a bulk / institutional transfer, not private co-ownership.
MIN_PARCELS, MAX_PARCELS = 2, 25
# A landlord on more distinct multi-parcel deeds than this is a serial co-investor hub -> masked.
DEED_HUB_CAP = 20
# Institutional grantees whose "co-ownership" is not a private owner.
_INST = ("HDFC", "HOUSING DEVELOPMENT FUND", "HOUSING AUTHORITY", "NYCHA", "CITY OF NEW YORK")


def _deed_sql(max_parcels: int) -> str:
    inst = " OR ".join(f"upper(p.name) LIKE '%{i}%'" for i in _INST)
    return f"""
        WITH latest AS (                        -- each building's most recent deed (staleness guard)
            SELECT DISTINCT ON (btrim(l.bbl)) btrim(l.bbl) AS bbl, m.documentid AS doc
            FROM real_property_master m
            JOIN real_property_legals l ON l.documentid = m.documentid
            WHERE m.doctype ILIKE '%%DEED%%'
              AND COALESCE(m.docdate, m.recordedfiled) <= CURRENT_DATE
            ORDER BY btrim(l.bbl), COALESCE(m.docdate, m.recordedfiled) DESC NULLS LAST
        )
        SELECT lt.doc AS doc, array_agg(DISTINCT lt.bbl) AS bbls
        FROM latest lt
        WHERE NOT EXISTS (
            SELECT 1 FROM real_property_parties p
            WHERE p.documentid = lt.doc AND p.partytype = 2 AND ({inst}))
        GROUP BY lt.doc
        HAVING count(DISTINCT lt.bbl) >= {MIN_PARCELS}
           AND count(DISTINCT lt.bbl) <= {int(max_parcels)}
    """


def _groups_from(deeds: pd.DataFrame, lwc: pd.DataFrame) -> dict[str, set[int]]:
    """Pure mapper (DB-free, testable): each deed -> the set of lwc nodeids covering its co-conveyed
    buildings, keeping only deeds that reach >=2 distinct nodes. ``deeds`` has columns ``doc``,
    ``bbls``; ``lwc`` has ``nodeid``, ``bbls``."""
    bbl2nodes: dict[str, set[int]] = defaultdict(set)
    for nodeid, bbls in zip(lwc["nodeid"], lwc["bbls"]):
        for b in (bbls if bbls is not None else []):
            bbl2nodes[b].add(int(nodeid))

    groups: dict[str, set[int]] = {}
    for doc, bbls in zip(deeds["doc"], deeds["bbls"]):
        ids: set[int] = set()
        for b in (bbls if bbls is not None else []):
            ids |= bbl2nodes.get(b, set())
        if len(ids) >= 2:
            groups[str(doc)] = ids
    return groups


def deed_node_groups(conn, *, max_parcels: int = MAX_PARCELS) -> dict[str, set[int]]:
    """Map each qualifying multi-parcel deed to the ``landlords_with_connections`` nodeids of its
    co-conveyed buildings (each building via its LATEST deed — see the staleness guard)."""
    deeds = pd.read_sql(_deed_sql(max_parcels), conn)
    lwc = pd.read_sql(
        "SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    return _groups_from(deeds, lwc)


def _hub_nodes(groups: dict[str, set[int]], hub_cap: int) -> set[int]:
    """Nodeids appearing in more than ``hub_cap`` distinct multi-parcel deeds — serial co-investor
    hubs whose transitive links would over-merge unrelated parties."""
    deed_count = Counter(n for ids in groups.values() for n in ids)
    return {n for n, c in deed_count.items() if c > hub_cap}


def deed_edges(conn, *, weight: float = SPLINK_WEIGHT, star_above: int = STAR_ABOVE,
               max_parcels: int = MAX_PARCELS, hub_cap: int = DEED_HUB_CAP) -> pd.DataFrame:
    """Co-conveyance cliques as ``[src, dst, weight]`` over lwc nodeids — one per multi-parcel deed
    (star above ``star_above``), with hub nodes dropped. Empty frame when nothing qualifies."""
    groups = deed_node_groups(conn, max_parcels=max_parcels)
    hubs = _hub_nodes(groups, hub_cap)
    rows: list[tuple[int, int]] = []
    for ids in groups.values():
        rows.extend(_clique_rows(ids - hubs, star_above))
    edges = pd.DataFrame(rows, columns=["src", "dst"]).drop_duplicates()
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    g = deed_node_groups(conn)
    hubs = _hub_nodes(g, DEED_HUB_CAP)
    E = deed_edges(conn)
    conn.close()
    n = len(pd.unique(E[["src", "dst"]].values.ravel())) if len(E) else 0
    print(f"multi-parcel deeds linking >=2 landlord nodes: {len(g):,}")
    print(f"deed-hub nodes masked (in > {DEED_HUB_CAP} deeds): {len(hubs):,}")
    print(f"CONNECTED_BY_DEED edges: {len(E):,} over {n:,} nodes")
