"""CONNECTED_BY_SPLINK edges from the DOF-registered owner entity (the same-LLC signal).

A deterministic ownership signal the head-officer nexus structurally misses. WoW's
``landlords_with_connections`` links landlords by the registered **head officer** (a
person); it never links on the property's **DOF owner-of-record**. So two buildings owned
by the *same registered entity* — e.g. BEACH 99TH LLC on two lots — land in different
portfolios whenever their head officers differ. This module reads
``pluto_latest.ownername`` (the DOF owner) and, for every entity owning >=2 buildings,
emits a weight-100 clique between those buildings' landlord nodes so WCC+Louvain merge them.

**Same legal entity name == same owner, definitionally** — so this is precision-1 by
construction for a genuine owner entity, with no probabilistic model and no ACRIS pipeline.
Two guards drop the only things that break that identity:

  * generic / placeholder owner strings (blank, "UNAVAILABLE OWNER", "SEE …"), and
  * institutional owners (HDFC, NYCHA, City, authorities) that are not private single-owner
    entities — the same exclusions the ownership analysis used.

A degree cap (``DEFAULT_MAX_DEGREE``) additionally skips any name on an implausibly large
number of lots — a placeholder or a title-holding nominee used across unrelated owners —
mirroring the aggregator-address mask on the linkage side.

Measured (2026-08, wow DB): **447 owner entities span >=2 portfolios over 1,307 buildings** —
a cheap, deterministic ownership signal, larger and cleaner than the ACRIS deed signal's
*current* incremental coverage. See the ownership-layer decision memo (specs/).

Neo4j-free: returns ``(src_nodeid, dst_nodeid, weight)`` over lwc nodeids so ``pipeline.py``
loads it exactly like the model and curated edges (with ``method=LLC_METHOD``).
"""
from __future__ import annotations

import re

import pandas as pd

from watchline.discovery.ingest.portfolio.splink_bridge import SPLINK_WEIGHT, STAR_ABOVE
from watchline.discovery.ingest.portfolio.curated_owners import _clique_rows

# Provenance stamped on these edges, distinct from model ("splink-fellegi-sunter") and
# curated ("curated-same-owner") edges.
LLC_METHOD = "registered-llc"

# An owner name on more lots than this is treated as a placeholder / title-holding nominee /
# institutional blob and skipped. Genuine private owners sit far below; the largest real
# single-entity holdings that exceed it are better handled by name matching on the linkage
# side, not a giant clique here.
DEFAULT_MAX_DEGREE = 100

# A name must look like a business entity (owner-of-record LLCs/corps), not a bare person —
# matching bare personal names risks fusing two different people who share a name. Matched as
# WHOLE WORDS (\y word boundaries) so "LP"/"INC" don't match HELP/PRINCE etc.
_ENTITY_MARKERS = (r"LLC", r"L\.L\.C", r"CORP", r"INC", r"REALTY", r"ASSOCIATES",
                   r"PROPERTIES", r"HOLDINGS?", r"PARTNERS", r"VENTURES", r"MANAGEMENT",
                   r"EQUITIES", r"LP", r"LLP")

# Not private single-owner entities — institutional / governmental. (Placeholder strings like
# "UNAVAILABLE OWNER" carry no entity marker, so the marker filter already drops them.) HDFCs
# are excluded explicitly because "…FUND CORPORATION" would otherwise pass the CORP marker.
_EXCLUDE = ("HDFC", "HOUSING DEVELOPMENT FUND", "NYCHA", "HOUSING AUTHORITY",
            "CITY OF NEW YORK", "DEPARTMENT OF")

_MARKER_RE = r"\y(" + "|".join(_ENTITY_MARKERS) + r")\y"
_norm = lambda s: re.sub(r"\s+", " ", s).strip().upper() if isinstance(s, str) else s


def _owner_sql(max_degree: int) -> str:
    excludes = " OR ".join(f"upper(ownername) LIKE '%{e}%'" for e in _EXCLUDE)
    return (
        "SELECT upper(btrim(ownername)) AS llc, array_agg(DISTINCT btrim(bbl)) AS bbls "
        "FROM pluto_latest "
        "WHERE ownername IS NOT NULL AND length(btrim(ownername)) > 3 "
        f"  AND upper(ownername) ~ '{_MARKER_RE}' AND NOT ({excludes}) "
        "GROUP BY 1 "
        f"HAVING count(DISTINCT btrim(bbl)) >= 2 AND count(DISTINCT btrim(bbl)) <= {int(max_degree)}"
    )


def _groups_from(owners: pd.DataFrame, lwc: pd.DataFrame) -> dict[str, set[int]]:
    """Pure mapper (DB-free, testable): each owner entity -> the set of lwc nodeids covering
    its buildings, keeping only entities that reach >=2 distinct nodes. ``owners`` has columns
    ``llc``, ``bbls``; ``lwc`` has ``nodeid``, ``bbls``."""
    bbl2nodes: dict[str, set[int]] = {}
    for nodeid, bbls in zip(lwc["nodeid"], lwc["bbls"]):
        for b in (bbls if bbls is not None else []):
            bbl2nodes.setdefault(b, set()).add(int(nodeid))

    groups: dict[str, set[int]] = {}
    for llc, bbls in zip(owners["llc"], owners["bbls"]):
        ids: set[int] = set()
        for b in (bbls if bbls is not None else []):
            ids |= bbl2nodes.get(b, set())
        if len(ids) >= 2:
            groups[llc] = ids
    return groups


def llc_node_groups(conn, *, max_degree: int = DEFAULT_MAX_DEGREE) -> dict[str, set[int]]:
    """Map each qualifying DOF owner entity to the set of ``landlords_with_connections``
    nodeids covering its buildings. A building with no lwc node (no HPD registration) is
    simply absent — the edge only helps buildings that are landlords."""
    owners = pd.read_sql(_owner_sql(max_degree), conn)
    lwc = pd.read_sql(
        "SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    return _groups_from(owners, lwc)


def llc_edges(conn, *, weight: float = SPLINK_WEIGHT, star_above: int = STAR_ABOVE,
              max_degree: int = DEFAULT_MAX_DEGREE) -> pd.DataFrame:
    """Same-owner-entity cliques as ``[src, dst, weight]`` over lwc nodeids — same clique/star
    shape as ``splink_bridge.splink_edges``. Empty frame when nothing qualifies."""
    rows: list[tuple[int, int]] = []
    for ids in llc_node_groups(conn, max_degree=max_degree).values():
        rows.extend(_clique_rows(ids, star_above))
    edges = pd.DataFrame(rows, columns=["src", "dst"]).drop_duplicates()
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    g = llc_node_groups(conn)
    E = llc_edges(conn)
    conn.close()
    n_nodes = len(pd.unique(E[["src", "dst"]].values.ravel())) if len(E) else 0
    print(f"owner entities linking >=2 landlord nodes: {len(g):,}")
    print(f"CONNECTED_BY_SPLINK (registered-llc) edges: {len(E):,} over {n_nodes:,} nodes")
