"""owner_groups.py — the OWNERSHIP layer: (:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup).

The owner-IDENTITY partition — who is the *apparent same owner* across differently-named LLCs,
distinct from the address-nexus `Portfolio` (which conflates a manager's many owners) and the
`MANAGED_BY` management layer.

The OwnerGroup partition **is** the connected components of the owner-identity edges that the
earlier steps already materialized: ``CONNECTED_BY_SPLINK`` (model Fellegi-Sunter + curated
overrides + registered-LLC, from ``--step splink``) and ``CONNECTED_BY_DEED`` (ACRIS multi-parcel
co-ownership, from ``--step deed`` — the name-free veil-pierce that merges an owner's differently-
named LLCs). So this step just reads those edges and runs a plain union-find over them — it does
NOT re-run the ~1-min Splink resolution. That makes it a fast, **Neo4j-only** pass (no Postgres,
no Splink/pandas dependency). It therefore REQUIRES ``--step splink`` to have run first (deed is
optional); with no such edges present it refuses rather than writing an empty layer.

No name/address glue -> no management-nexus conflation. The identity-component check confirmed
0 of ~6,300 owner components exceed MAX_SIZE=300, so this needs no Louvain. Singletons are absent
by construction (a landlord with no splink edge is its own owner). This is INFERRED ownership,
never a legal determination (Type II).

A group can span multiple SURNAMES: the registered-LLC signal (entity resolution) merges the
co-officers of one owner LLC, which is accepted as entity-level ownership ("same owner LLC", not
"same person"). The anchor name reflects this — a multi-surname group whose buildings are
dominated (>=60%) by one real LLC/corp takes that entity as its name (the person anchor would name
only one of several co-officers); person-identity groups keep the top member's name. See the
anchor passes below. Declare :OwnerGroup / IN_OWNER_GROUP before loading.
"""
from __future__ import annotations

from collections import defaultdict

# Provenance on the derived OwnerGroup nodes / IN_OWNER_GROUP edges (the signals feeding
# CONNECTED_BY_SPLINK: Fellegi-Sunter model + corp feedback + curated overrides + registered-LLC).
OWNER_GROUP_METHOD = "splink-identity+curated+llc"


def _union_groups(pairs, *, min_size: int = 2) -> dict[int, str]:
    """Union-find over ``pairs`` (iterable of (a, b) nodeids to merge). Returns
    ``{nodeid: 'OG-<root>'}`` for nodes whose component has >= ``min_size`` members. Root is the
    MIN nodeid in the component, so ids are deterministic given the same edge set."""
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


# Every owner-identity edge as an unordered nodeid pair: CONNECTED_BY_SPLINK (model + curated +
# registered-LLC) and CONNECTED_BY_DEED (ACRIS multi-parcel co-ownership — the name-free veil-pierce).
_EDGES = """
MATCH (a:Landlord)-[:CONNECTED_BY_SPLINK|CONNECTED_BY_DEED]-(b:Landlord)
WHERE a.nodeid < b.nodeid
RETURN DISTINCT a.nodeid AS a, b.nodeid AS b
"""


def owner_groups(driver, *, database: str) -> list[dict]:
    """``[{nodeid, owner_group_id}]`` — multi-node owner-identity groups = connected components of
    the materialized CONNECTED_BY_SPLINK edges. Empty if the splink step has not run."""
    with driver.session(database=database) as s:
        pairs = [(r["a"], r["b"]) for r in s.run(_EDGES)]
    groups = _union_groups(pairs, min_size=2)
    return [{"nodeid": nid, "owner_group_id": gid} for nid, gid in sorted(groups.items())]


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
# Anchor name in two passes. (1) Default = the member with the most buildings — right for a
# person-identity group (one person and their aliases/typos; the person is the recognizable
# accountability label even when they own via a shell LLC). (2) Override with the group's
# dominant DOF owner ENTITY ONLY for a MULTI-SURNAME group (the entity-linked case: co-officers
# of one LLC merged by the registered-LLC signal), where the person anchor names just one of
# several — and only when one real LLC/corp covers a strong majority (>=60%) of the group's
# buildings. Placeholders ("UNAVAILABLE OWNER") and HDFC/institutional owners are never anchors.
_ANCHOR_PERSON = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH og, l ORDER BY size(l.bbls) DESC
WITH og, head(collect(l.name)) AS anchor SET og.name = anchor
"""
_ANCHOR_ENTITY = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
WITH og, count(DISTINCT toUpper(split(l.name, ' ')[-1])) AS surnames
WHERE surnames >= 2
MATCH (l2:Landlord)-[:IN_OWNER_GROUP]->(og)
UNWIND l2.bbls AS bbl
MATCH (b:Building {bbl: bbl})
WITH og, toUpper(trim(b.dof_ownername)) AS o, bbl
WHERE o IS NOT NULL
  AND o =~ '(?i).*\\\\b(LLC|L\\\\.L\\\\.C|CORP|INC|REALTY|ASSOCIATES|PROPERTIES|HOLDINGS?|PARTNERS|VENTURES|EQUITIES|LP|LLP)\\\\b.*'
  AND NOT o CONTAINS 'UNAVAILABLE'
  AND NOT o CONTAINS 'HDFC'
  AND NOT o CONTAINS 'HOUSING DEVELOPMENT FUND'
WITH og, o, count(DISTINCT bbl) AS n
ORDER BY n DESC
WITH og, collect({o: o, n: n})[0] AS top
WHERE top IS NOT NULL AND top.n * 5 >= og.building_count * 3
SET og.name = top.o
"""


def load_owner_groups(driver, *, database: str, batch_size: int = 5000) -> int:
    """Rebuild the ownership layer from the materialized CONNECTED_BY_SPLINK edges: drop existing
    :OwnerGroup/IN_OWNER_GROUP, then write fresh and set member_count / building_count / anchor
    name. Refuses if no splink edges are present (run --step splink first)."""
    rows = owner_groups(driver, database=database)
    if not rows:
        raise RuntimeError(
            "no CONNECTED_BY_SPLINK edges found — run `--step splink` before `--step ownergroup`")
    with driver.session(database=database) as s:
        for stmt in _CLEANUP:
            s.run(stmt)
        for i in range(0, len(rows), batch_size):
            s.run(_LOAD, batch=rows[i:i + batch_size], method=OWNER_GROUP_METHOD)
        for stmt in (_MEMBER_COUNT, _BUILDING_COUNT, _ANCHOR_PERSON, _ANCHOR_ENTITY):
            s.run(stmt)
    return len(rows)


if __name__ == "__main__":  # read-only summary
    from collections import Counter
    from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE
    driver = neo4j_driver()
    rows = owner_groups(driver, database=NEO4J_DISCOVERY_DATABASE)
    driver.close()
    sizes = Counter(r["owner_group_id"] for r in rows)
    top = sorted(sizes.values(), reverse=True)
    print(f"multi-node owner groups: {len(sizes):,}  covering {len(rows):,} landlord nodes")
    if top:
        print(f"  members per group: median {sorted(sizes.values())[len(sizes)//2]}, max {top[0]}")
        print(f"  largest groups (landlord nodes): {top[:10]}")
