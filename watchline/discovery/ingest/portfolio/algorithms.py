"""
watchline/discovery/ingest/portfolio/algorithms.py

GDS clustering for discovery-KG portfolio detection.

Run GDS Weakly Connected Components to find initial ownership portfolios,
then recursively apply GDS Louvain to split any component whose BBL count
exceeds MAX_SIZE.

All graph work stays in the GDS in-memory projection — no Neo4j writes
during the algorithm. Subgraph projections are filtered from parent graphs
using mutated properties (wccId -> louvainId at each recursion level).

Yields (portfolio_id, frozenset_of_neo4j_node_ids) for each final portfolio.

Adapted from the earlier portfolio pipeline's algorithms.py. Projects the
`LandlordActor` secondary label, not `Actor` -- since acris_deeds, `Actor`
also contains ~7.7M ACRIS-origin actors with no CONNECTED_BY_* edges (see
notes/acris-identity.md); projecting those would flood WCC with singleton
components and exceed available JVM heap just materializing them. See
project_graph()'s docstring for the full story.

Targets GDS 2026.x, where Louvain's `resolution` parameter was removed
(Louvain uses default granularity) — do NOT reintroduce it.
"""

import os
from typing import Dict, FrozenSet, Iterator, List, Set, Tuple

from graphdatascience import GraphDataScience
from neo4j import Session

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

GRAPH_NAME = "landlord-graph"
MAX_SIZE = 300  # max buildings (BBLs) per portfolio before Louvain splitting


# ---------------------------------------------------------------------------
# GDS connection
# ---------------------------------------------------------------------------

def make_gds() -> GraphDataScience:
    return GraphDataScience(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        database=NEO4J_DATABASE,
    )


# ---------------------------------------------------------------------------
# Graph lifecycle
# ---------------------------------------------------------------------------

def cleanup_projections(gds: GraphDataScience) -> None:
    """Drop any portfolio-related GDS projections left from a previous run."""
    df = gds.graph.list()
    if df.empty:
        return
    for name in df["graphName"].tolist():
        if name == GRAPH_NAME or name.startswith("portfolio-"):
            gds.graph.drop(name, failIfMissing=False)


def project_graph(gds: GraphDataScience):
    """
    Project LandlordActor nodes + both connection edge types as an
    undirected weighted graph.

    Projects the `LandlordActor` secondary label, NOT `Actor`. Since
    acris_deeds, `Actor` also includes ~7.7M ACRIS-origin actors (see
    notes/acris-identity.md) that have no CONNECTED_BY_* edges -- an
    initial attempt to project all of `Actor` and filter afterward
    (gds.graph.filter) still had to materialize every ACRIS actor into the
    native projection first, which alone exceeded available JVM heap
    (~1.8 GiB required vs ~1 GiB free) before any filtering could happen.
    Projecting a narrower label instead avoids ever reading the ACRIS actors
    off the node store, matching pre-acris_deeds memory/perf. `LandlordActor`
    is set alongside `Actor` at actor-creation time in hpd_registrations and
    portfolio's own load_actors -- both MERGE clauses were updated to add it.
    """
    G, _ = gds.graph.project(
        GRAPH_NAME,
        "LandlordActor",
        {
            "CONNECTED_BY_NAME": {"orientation": "UNDIRECTED", "properties": "weight"},
            "CONNECTED_BY_ADDRESS": {"orientation": "UNDIRECTED", "properties": "weight"},
        },
    )
    return G


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bbl_counts(session: Session) -> Dict[int, int]:
    """
    Map each landlord Actor's internal node id -> number of BBLs it is
    associated with. Scoped to :LandlordActor (see project_graph) --
    ACRIS-origin actors never set bbls and are never present in the
    projected graph this feeds, so including them here would just be
    wasted work over millions of irrelevant nodes.
    """
    result = session.run(
        "MATCH (a:LandlordActor) RETURN id(a) AS nodeId, size(a.bbls) AS bblCount"
    )
    return {r["nodeId"]: r["bblCount"] for r in result}


def _portfolio_size(node_ids: Set[int], bbl_counts: Dict[int, int]) -> int:
    return sum(bbl_counts.get(nid, 0) for nid in node_ids)


def _stream_property(gds: GraphDataScience, G, prop: str) -> Dict[int, int]:
    """Stream a single node property from an in-memory graph. Returns {nodeId: value}."""
    df = gds.graph.streamNodeProperties(G, [prop], separate_property_columns=True)
    return dict(zip(df["nodeId"].astype(int), df[prop].astype(int)))


# ---------------------------------------------------------------------------
# WCC
# ---------------------------------------------------------------------------

def _run_wcc(gds: GraphDataScience, G) -> Dict[int, Set[int]]:
    """Mutate wccId onto G, then stream to group nodes into components."""
    gds.wcc.mutate(G, mutateProperty="wccId")
    node_to_comp = _stream_property(gds, G, "wccId")

    components: Dict[int, Set[int]] = {}
    for node_id, comp_id in node_to_comp.items():
        components.setdefault(comp_id, set()).add(node_id)
    return components


# ---------------------------------------------------------------------------
# Recursive Louvain splitting
# ---------------------------------------------------------------------------

def _split(
    gds: GraphDataScience,
    parent: object,           # GDS Graph object to filter from
    filter_prop: str,         # property name used to identify this node group
    filter_val: int,          # the value that selects this group
    node_ids: Set[int],
    bbl_counts: Dict[int, int],
    counter: List[int],
    depth: int = 0,
) -> Iterator[Tuple[int, FrozenSet[int]]]:
    """
    Recursively split node_ids using Louvain if portfolio_size > MAX_SIZE.

    Each recursion level uses a depth-indexed mutate property (louvainId_0,
    louvainId_1, ...) so child subgraphs — which inherit parent properties —
    never collide with a property that already exists in the in-memory graph.

    `counter` is also the source of each final portfolio's id: it must be
    bumped at every yield (not just every subgraph filter) so that two
    sibling communities produced by splitting the same parent component never
    yield the same id — reusing the parent's id there previously caused
    portfolio_id collisions whenever Louvain split a component into more than
    one final portfolio.
    """
    size = _portfolio_size(node_ids, bbl_counts)

    if size <= MAX_SIZE:
        counter[0] += 1
        yield (counter[0], frozenset(node_ids))
        return

    subgraph_name = f"portfolio-{counter[0]}"
    counter[0] += 1
    mutate_prop = f"louvainId_{depth}"

    subgraph, _ = gds.graph.filter(
        subgraph_name,
        parent,
        f"n.{filter_prop} = {filter_val}",
        "*",
    )

    try:
        gds.louvain.mutate(
            subgraph,
            mutateProperty=mutate_prop,
            relationshipWeightProperty="weight",
        )

        node_to_comm = _stream_property(gds, subgraph, mutate_prop)

        communities: Dict[int, Set[int]] = {}
        for node_id, comm_id in node_to_comm.items():
            communities.setdefault(comm_id, set()).add(node_id)

        comm_sizes = [_portfolio_size(ids, bbl_counts) for ids in communities.values()]

        # If Louvain produced no meaningful split, yield the group as-is
        if len(communities) == 1 or max(comm_sizes) == size:
            counter[0] += 1
            yield (counter[0], frozenset(node_ids))
            return

        for comm_id, comm_node_ids in communities.items():
            yield from _split(
                gds, subgraph, mutate_prop, comm_id,
                comm_node_ids, bbl_counts, counter, depth + 1,
            )

    finally:
        subgraph.drop()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def iter_portfolios(
    gds: GraphDataScience, G, session: Session
) -> Iterator[Tuple[int, FrozenSet[int]]]:
    """Yield (portfolio_id, frozenset_of_nodeIds) for every final portfolio."""

    print("  Fetching BBL counts ...")
    bbl_counts = _get_bbl_counts(session)

    print("  Running WCC ...")
    components = _run_wcc(gds, G)
    print(f"  {len(components):,} connected components found.")

    print("  Splitting oversized components with Louvain ...")
    counter = [0]
    for comp_id, node_ids in components.items():
        yield from _split(gds, G, "wccId", comp_id, node_ids, bbl_counts, counter)


def run(gds: GraphDataScience, session: Session):
    """
    Clean up prior projections, project the actor graph, and return
    (G, iterator over final portfolios). Caller is responsible for
    dropping G when done.
    """
    print("  Projecting GDS graph ...")
    cleanup_projections(gds)
    G = project_graph(gds)
    print(f"  {G.node_count():,} nodes, {G.relationship_count():,} relationships.")
    return G, iter_portfolios(gds, G, session)
