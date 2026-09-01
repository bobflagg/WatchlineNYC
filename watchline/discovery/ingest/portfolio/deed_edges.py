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

Scope (mirrors the decision-memo tuning): doctype ILIKE '%DEED%' (the 8 conveyance subtypes),
recent deeds only (>= DEFAULT_MIN_DATE — 75% of multi-parcel deeds are pre-2005 and their ownership
has since turned over), 2..MAX_PARCELS lots (mega-deeds are bulk/institutional transfers, not
private co-ownership), and institutional grantees (HDFC/NYCHA/City) excluded. One clique per deed
over the co-conveyed buildings' landlord nodes (star above STAR_ABOVE to bound edges).

Node mapping is the same explode-join on ``bbl`` that splink_bridge/llc_edges use. Neo4j-free;
returns ``(src_nodeid, dst_nodeid, weight)`` so pipeline.py loads it as CONNECTED_BY_DEED.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from watchline.discovery.ingest.portfolio.splink_bridge import SPLINK_WEIGHT, STAR_ABOVE
from watchline.discovery.ingest.portfolio.curated_owners import _clique_rows

DEED_METHOD = "acris-deed"

# Recent deeds only — co-ownership from a 20-year-old deed has usually turned over.
DEFAULT_MIN_DATE = "2013-01-01"
# A deed conveying more lots than this is a bulk / institutional transfer, not private co-ownership.
MIN_PARCELS, MAX_PARCELS = 2, 25
# Institutional grantees whose "co-ownership" is not a private owner.
_INST = ("HDFC", "HOUSING DEVELOPMENT FUND", "HOUSING AUTHORITY", "NYCHA", "CITY OF NEW YORK")


def _deed_sql(min_date: str, max_parcels: int) -> str:
    inst = " OR ".join(f"upper(p.name) LIKE '%{i}%'" for i in _INST)
    return f"""
        WITH deeds AS (
            SELECT DISTINCT ON (documentid) documentid,
                   COALESCE(docdate, recordedfiled) AS ddate
            FROM real_property_master
            WHERE doctype ILIKE '%%DEED%%'
            ORDER BY documentid, modifieddate DESC
        )
        SELECT d.documentid AS doc, array_agg(DISTINCT btrim(l.bbl)) AS bbls
        FROM deeds d
        JOIN real_property_legals l ON l.documentid = d.documentid
        WHERE d.ddate >= '{min_date}'
          AND NOT EXISTS (
              SELECT 1 FROM real_property_parties p
              WHERE p.documentid = d.documentid AND p.partytype = 2 AND ({inst}))
        GROUP BY d.documentid
        HAVING count(DISTINCT btrim(l.bbl)) >= {MIN_PARCELS}
           AND count(DISTINCT btrim(l.bbl)) <= {int(max_parcels)}
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


def deed_node_groups(conn, *, min_date: str = DEFAULT_MIN_DATE,
                     max_parcels: int = MAX_PARCELS) -> dict[str, set[int]]:
    """Map each qualifying multi-parcel deed to the ``landlords_with_connections`` nodeids of its
    co-conveyed buildings."""
    deeds = pd.read_sql(_deed_sql(min_date, max_parcels), conn)
    lwc = pd.read_sql(
        "SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    return _groups_from(deeds, lwc)


def deed_edges(conn, *, weight: float = SPLINK_WEIGHT, star_above: int = STAR_ABOVE,
               min_date: str = DEFAULT_MIN_DATE, max_parcels: int = MAX_PARCELS) -> pd.DataFrame:
    """Co-conveyance cliques as ``[src, dst, weight]`` over lwc nodeids — one per multi-parcel deed
    (star above ``star_above``). Empty frame when nothing qualifies."""
    rows: list[tuple[int, int]] = []
    for ids in deed_node_groups(conn, min_date=min_date, max_parcels=max_parcels).values():
        rows.extend(_clique_rows(ids, star_above))
    edges = pd.DataFrame(rows, columns=["src", "dst"]).drop_duplicates()
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    g = deed_node_groups(conn)
    E = deed_edges(conn)
    conn.close()
    n = len(pd.unique(E[["src", "dst"]].values.ravel())) if len(E) else 0
    print(f"multi-parcel deeds linking >=2 landlord nodes: {len(g):,}")
    print(f"CONNECTED_BY_DEED edges: {len(E):,} over {n:,} nodes")
