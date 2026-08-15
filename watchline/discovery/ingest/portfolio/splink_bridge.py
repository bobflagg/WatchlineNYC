"""CONNECTED_BY_SPLINK — feed Splink's owner resolution into WoW's portfolio graph.

Mechanism B (see CLAUDE.md "Splink as a de-dup edge"). Splink resolves raw HPD owner
contacts into precision-first entities; this emits a high-weight edge between every pair
of ``landlords_with_connections`` nodes that resolve to the *same* owner. The pipeline's
WCC+Louvain then merges the fragments WoW's name/address matching split — Croman's typo'd
offices collapse from 6 portfolios into 1 — WITHOUT changing anything WoW already links:
edges only ADD, so connected components can only *merge*, never split. An existing
portfolio (e.g. an agent-linked shell operation) is therefore safe by construction.

This module is Neo4j-free: it runs off Postgres + Splink and returns
``(src_nodeid, dst_nodeid, weight)`` so ``pipeline.py`` can MATCH the ``Actor`` nodes by
``ACT-LL-<nodeid>`` and MERGE the relationships (mirroring the name/address edge load).

Node mapping is EXACT, not fuzzy. A Splink contact and an lwc node both carry the same
``(owner name, bbl)`` from the same HPD registration, so an explode-and-join on
``(name, bbl)`` maps each lwc node to its Splink entity — 99.9% of lwc nodes covered in
the production run, with zero edges linking different surnames (the name-anchored
resolution + first-name/common-name vetoes guarantee that).

Runs against whatever ``PGDATABASE`` points at; in production that is the ``wow`` DB, so
Splink reads ``wow.hpd_contacts`` and the join reads ``wow.landlords_with_connections``.
"""
from __future__ import annotations

import re
from itertools import combinations

import pandas as pd

from watchline.discovery.ingest.portfolio import splink_source as ss
from watchline.discovery.ingest.portfolio.eval.build_gold import (
    TARGET_WHERE, NBR_WHERE, OFFICE_WHERE)

# Splink edges outweigh name (~1.5) / address (~1.0) links, so when a merged component
# exceeds MAX_SIZE and Louvain splits it, a resolved owner's nodes stay together.
SPLINK_WEIGHT = 10.0

# Above this many nodes an entity is wired as a star (hub -> members) instead of a full
# clique, to bound edge count; the vetoes keep real entities well under this.
STAR_ABOVE = 150

# Deterministic dense training slice (targets + aggregator neighbours + a hash sample)
# so the resolution reproduces run-to-run apart from EM stochasticity.
_DET_SAMPLE = ("abs(hashtext(coalesce(c.firstname,'')||coalesce(c.lastname,'')"
               "||coalesce(c.businesshousenumber,''))) % 1000 < 12")
_norm = lambda s: re.sub(r"\s+", " ", s).strip().upper() if isinstance(s, str) else s


def _resolve(conn, threshold: float):
    """Full-population Splink resolution -> (records, clusters). Name-anchored blocking
    plus the first-name and common-name vetoes (see splink_source.cluster_gated)."""
    full = ss.extract(conn, "TRUE")
    full = full[full.contact_kind == "person"].drop_duplicates("unique_id").reset_index(drop=True)
    train = pd.concat([ss.extract(conn, TARGET_WHERE), ss.extract(conn, NBR_WHERE),
                       ss.extract(conn, OFFICE_WHERE), ss.extract(conn, _DET_SAMPLE)],
                      ignore_index=True)
    train = train[train.contact_kind == "person"].drop_duplicates("unique_id").reset_index(drop=True)
    degs = ss.address_degrees(conn)
    nf = ss.name_freq(conn)
    linker, preds = ss.fit_predict_full(train, full, addr_degrees=degs)
    clusters = ss.cluster_gated(preds, full, threshold, name_freq=nf)
    return full, clusters


def node_clusters(conn, *, threshold: float = 0.95) -> pd.DataFrame:
    """Map each ``landlords_with_connections`` node to its Splink entity.

    Returns ``[nodeid, cluster_id]``. A node whose buildings straddle two entities
    (rare) takes the plurality entity of its bbls."""
    full, clusters = _resolve(conn, threshold)

    sp = clusters[["unique_id", "cluster_id"]].merge(
        full[["unique_id", "name_full", "bbls"]], on="unique_id")
    sp = sp.explode("bbls").rename(columns={"bbls": "bbl", "name_full": "name"})
    sp["name"] = sp["name"].map(_norm)
    sp = sp[["name", "bbl", "cluster_id"]].dropna()

    lwc = pd.read_sql(
        "SELECT nodeid, name, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    ln = lwc.explode("bbls").rename(columns={"bbls": "bbl"})[["nodeid", "name", "bbl"]].copy()
    ln["name"] = ln["name"].map(_norm)

    j = ln.merge(sp, on=["name", "bbl"], how="inner")
    nc = (j.groupby("nodeid")["cluster_id"]
            .agg(lambda s: s.mode().iloc[0]).rename("cluster_id").reset_index())
    return nc


def splink_edges(conn, *, threshold: float = 0.95, weight: float = SPLINK_WEIGHT,
                 star_above: int = STAR_ABOVE) -> pd.DataFrame:
    """CONNECTED_BY_SPLINK edges as ``[src, dst, weight]`` over lwc nodeids.

    One clique per resolved entity of >=2 nodes (so the group stays dense under Louvain);
    entities larger than ``star_above`` fall back to a hub-and-spoke star to bound edges.
    """
    nc = node_clusters(conn, threshold=threshold)
    rows: list[tuple[int, int]] = []
    for _, g in nc.groupby("cluster_id"):
        ids = sorted(g["nodeid"].tolist())
        if len(ids) < 2:
            continue
        if len(ids) <= star_above:
            rows.extend(combinations(ids, 2))
        else:
            rows.extend((ids[0], d) for d in ids[1:])
    edges = pd.DataFrame(rows, columns=["src", "dst"])
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # quick read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    E = splink_edges(conn)
    conn.close()
    n = pd.unique(E[["src", "dst"]].values.ravel())
    print(f"CONNECTED_BY_SPLINK: {len(E):,} edges over {len(n):,} nodes")
