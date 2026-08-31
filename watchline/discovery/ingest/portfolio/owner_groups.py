"""owner_groups.py — the OWNERSHIP layer: (:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup).

The owner-IDENTITY partition — who is the *apparent same owner* across differently-named LLCs,
distinct from the address-nexus `Portfolio` (which conflates a manager's many owners) and the
`MANAGED_BY` management layer. Built from the SAME identity signals that feed CONNECTED_BY_SPLINK,
unioned:

  * ``splink_bridge.node_clusters`` — Fellegi-Sunter model + corp-co-owner feedback (the resolver),
  * ``curated_owners.curated_edges`` — hand-verified same-owner overrides (Croman's ROCKSOLID remnant),
  * ``llc_edges.llc_edges``          — same registered DOF entity (deterministic).

NO name/address glue -> no management-nexus conflation. The identity-component check confirmed
0 of ~6,300 owner components exceed MAX_SIZE=300, so this needs no Louvain: it is a plain
union-find over the identity edges (singletons excluded — a lone landlord *is* its own owner).

This is INFERRED ownership, never a legal determination (Type II) — the same caveat class as
`Portfolio`/`APPARENT_CONTROL`. Neo4j-free grouping; ``load_owner_groups`` does the KG write.
Declare :OwnerGroup / IN_OWNER_GROUP in the graph type before loading.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from watchline.discovery.ingest.portfolio import splink_bridge, curated_owners, llc_edges

# Provenance on the derived OwnerGroup nodes / IN_OWNER_GROUP edges.
OWNER_GROUP_METHOD = "splink-identity+curated+llc"


def _union_groups(pairs, *, min_size: int = 2) -> dict[int, str]:
    """Union-find over ``pairs`` (iterable of (a, b) nodeids to merge). Returns
    ``{nodeid: 'OG-<root>'}`` for nodes whose component has >= ``min_size`` members. Root is the
    MIN nodeid in the component, so ids are deterministic given the same clustering."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:          # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)    # attach larger id under smaller

    nodes: set[int] = set()
    for a, b in pairs:
        nodes.add(a); nodes.add(b); union(a, b)

    comp: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        comp[find(n)].append(n)

    out: dict[int, str] = {}
    for root, members in comp.items():
        if len(members) >= min_size:
            gid = f"OG-{root}"
            for m in members:
                out[m] = gid
    return out


def owner_groups(conn, *, min_size: int = 2) -> pd.DataFrame:
    """``[nodeid, owner_group_id]`` — multi-node owner-identity groups (node_clusters unioned with
    the curated and registered-LLC merges). Singletons are omitted: a landlord with no same-owner
    peer is its own owner and needs no group node."""
    nc = splink_bridge.node_clusters(conn)                     # [nodeid, cluster_id]
    pairs: list[tuple[int, int]] = []
    for _, grp in nc.groupby("cluster_id"):
        ids = grp["nodeid"].astype(int).tolist()
        pairs.extend((ids[0], x) for x in ids[1:])            # star per resolved cluster
    for edges in (curated_owners.curated_edges(conn), llc_edges.llc_edges(conn)):
        pairs.extend((int(s), int(d)) for s, d, *_ in edges.itertuples(index=False))

    groups = _union_groups(pairs, min_size=min_size)
    return pd.DataFrame(sorted(groups.items()), columns=["nodeid", "owner_group_id"])


# --- KG write (declare :OwnerGroup / IN_OWNER_GROUP in the graph type before running) ----------
_CLEANUP = [
    "MATCH ()-[r:IN_OWNER_GROUP]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS",
    "MATCH (o:OwnerGroup) CALL (o) { DETACH DELETE o } IN TRANSACTIONS OF 5000 ROWS",
]
_LOAD = """
UNWIND $batch AS row
MERGE (og:OwnerGroup:WatchlineNode {owner_group_id: row.owner_group_id})
  ON CREATE SET og.method = $method, og.generated_at = datetime()
WITH og, row
// Match on :Actor — actor_id IS KEY on :Actor (indexed); the node also carries :Landlord,
// so the edge still satisfies the (:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup) type. Matching
// on :Landlord instead triggers a full label scan per row (no index on that label).
MATCH (l:Actor {actor_id: 'ACT-LL-' + toString(row.nodeid)})
MERGE (l)-[:IN_OWNER_GROUP]->(og)
"""
# member_count, building_count (union of members' bbls), and name (anchor = member with most bbls).
_MEMBER_COUNT = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH og, count(DISTINCT l) AS mc SET og.member_count = mc
"""
_BUILDING_COUNT = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
UNWIND l.bbls AS bbl
WITH og, count(DISTINCT bbl) AS bc SET og.building_count = bc
"""
_ANCHOR_NAME = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH og, l ORDER BY size(l.bbls) DESC
WITH og, head(collect(l.name)) AS anchor SET og.name = anchor
"""


def load_owner_groups(driver, conn, *, database: str, batch_size: int = 5000) -> int:
    """Rebuild the ownership layer: drop existing :OwnerGroup/IN_OWNER_GROUP, then write fresh
    from :func:`owner_groups`, and set member_count / building_count / anchor name."""
    df = owner_groups(conn)
    rows = df.to_dict("records")
    with driver.session(database=database) as s:
        for stmt in _CLEANUP:
            s.run(stmt)
        for i in range(0, len(rows), batch_size):
            s.run(_LOAD, batch=rows[i:i + batch_size], method=OWNER_GROUP_METHOD)
        for stmt in (_MEMBER_COUNT, _BUILDING_COUNT, _ANCHOR_NAME):
            s.run(stmt)
    return len(rows)


if __name__ == "__main__":  # read-only summary (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    df = owner_groups(conn)
    conn.close()
    sizes = df.groupby("owner_group_id").size()
    print(f"multi-node owner groups: {len(sizes):,}  covering {len(df):,} landlord nodes")
    print(f"  members per group: median {int(sizes.median())}, max {int(sizes.max())}")
    print(f"  largest groups (landlord nodes): {sorted(sizes.tolist(), reverse=True)[:10]}")
