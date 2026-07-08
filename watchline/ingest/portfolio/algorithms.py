"""
Run GDS Weakly Connected Components to find initial ownership portfolios,
then recursively apply GDS Louvain to split any component whose BBL count
exceeds MAX_SIZE.

All graph work stays in the GDS in-memory projection -- no Neo4j writes
during the algorithm. Subgraph projections are filtered from parent graphs
using mutated properties (wccId -> louvainId at each recursion level).

Yields (orig_id, frozenset_of_neo4j_node_ids, split_info) for each final
portfolio, where split_info carries metadata needed for RMT-004 confidence
derivation and the versioned update protocol.

Watchline adaptation of the JustFix WoW algorithms.py:
  - Added split_info dict to every yield, carrying:
      was_split: bool
      depth: int (number of Louvain passes applied)
      modularity_gain: float or None (None if WCC component was small enough)
      original_wcc_size: int (BBL count before any splitting)
    This data is consumed by store.py for RMT-004 confidence derivation.
  - The modularity gain termination condition is now explicit and recorded.
  - GRAPH_NAME and MAX_SIZE unchanged from original.
"""

import os
from typing import Dict, FrozenSet, Iterator, List, Optional, Set, Tuple

from graphdatascience import GraphDataScience
from neo4j import Session

from watchline.ingest.portfolio.config import NEO4J_DATABASE

GRAPH_NAME = "landlord-graph"
MAX_SIZE = 300


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
    """Project Landlord nodes + both relationship types as an undirected weighted graph."""
    G, _ = gds.graph.project(
        GRAPH_NAME,
        "Landlord",
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
    result = session.run(
        "MATCH (l:Landlord) RETURN id(l) AS nodeId, size(l.bbls) AS bblCount"
    )
    return {r["nodeId"]: r["bblCount"] for r in result}


def _portfolio_size(node_ids: Set[int], bbl_counts: Dict[int, int]) -> int:
    return sum(bbl_counts.get(nid, 0) for nid in node_ids)


def _stream_property(gds: GraphDataScience, G, prop: str) -> Dict[int, int]:
    """Stream a single node property from an in-memory graph."""
    df = gds.graph.streamNodeProperties(G, [prop], separate_property_columns=True)
    return dict(zip(df["nodeId"].astype(int), df[prop].astype(int)))


def _get_modularity(gds: GraphDataScience, G, community_prop: str) -> Optional[float]:
    """
    Compute the modularity of a community assignment on G.
    Returns None if the GDS version does not support modularity computation.
    Used for RMT-004 confidence derivation and termination logging.
    """
    try:
        result = gds.louvain.stats(G, nodeLabels=["*"],
                                   communityProperty=community_prop,
                                   relationshipWeightProperty="weight")
        return float(result.get("modularity", None))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WCC
# ---------------------------------------------------------------------------

def _run_wcc(gds: GraphDataScience, G) -> Dict[int, Set[int]]:
    """
    Mutate wccId onto G, then stream the property to get component groups.
    Returns {wcc_id: set_of_node_ids}.
    """
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
    parent: object,
    filter_prop: str,
    filter_val: int,
    node_ids: Set[int],
    orig_id: int,
    original_wcc_size: int,
    bbl_counts: Dict[int, int],
    counter: List[int],
    depth: int = 0,
    accumulated_modularity: Optional[float] = None,
) -> Iterator[Tuple[int, FrozenSet[int], Dict]]:
    """
    Recursively split node_ids using Louvain if portfolio_size > MAX_SIZE.

    Yields (orig_id, frozenset_of_nodeIds, split_info) where split_info is:
        {
            "was_split": bool,
            "depth": int,
            "modularity_gain": float or None,
            "original_wcc_size": int,
            "termination_reason": str,
        }

    termination_reason values:
        "below_threshold"  -- component was small enough, no split needed
        "louvain_split"    -- successfully split by Louvain
        "no_meaningful_split" -- Louvain failed to reduce max community size
    """
    size = _portfolio_size(node_ids, bbl_counts)

    if size <= MAX_SIZE:
        yield (
            orig_id,
            frozenset(node_ids),
            {
                "was_split": depth > 0,
                "depth": depth,
                "modularity_gain": accumulated_modularity,
                "original_wcc_size": original_wcc_size,
                "termination_reason": "below_threshold",
            },
        )
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
        result = gds.louvain.mutate(
            subgraph,
            mutateProperty=mutate_prop,
            relationshipWeightProperty="weight",
        )

        # Capture modularity from the Louvain result if available
        modularity = None
        if hasattr(result, "modularity"):
            modularity = float(result.modularity)
        elif isinstance(result, dict):
            modularity = result.get("modularity")

        node_to_comm = _stream_property(gds, subgraph, mutate_prop)

        communities: Dict[int, Set[int]] = {}
        for node_id, comm_id in node_to_comm.items():
            communities.setdefault(comm_id, set()).add(node_id)

        comm_sizes = [_portfolio_size(ids, bbl_counts) for ids in communities.values()]

        # Louvain produced no meaningful split
        if len(communities) == 1 or max(comm_sizes) == size:
            yield (
                orig_id,
                frozenset(node_ids),
                {
                    "was_split": depth > 0,
                    "depth": depth,
                    "modularity_gain": modularity,
                    "original_wcc_size": original_wcc_size,
                    "termination_reason": "no_meaningful_split",
                },
            )
            return

        for comm_id, comm_node_ids in communities.items():
            yield from _split(
                gds, subgraph, mutate_prop, comm_id,
                comm_node_ids, orig_id, original_wcc_size, bbl_counts,
                counter, depth + 1,
                accumulated_modularity=modularity,
            )

    finally:
        subgraph.drop()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def iter_portfolios(
    gds: GraphDataScience, G, session: Session
) -> Iterator[Tuple[int, FrozenSet[int], Dict]]:
    """Yield (orig_id, frozenset_of_nodeIds, split_info) for every final portfolio."""

    print("  Fetching BBL counts ...")
    bbl_counts = _get_bbl_counts(session)

    print("  Running WCC ...")
    components = _run_wcc(gds, G)
    print(f"  {len(components):,} connected components found.")

    print("  Splitting large components ...")
    counter = [0]
    for orig_id, (comp_id, node_ids) in enumerate(components.items(), 1):
        original_wcc_size = _portfolio_size(node_ids, bbl_counts)
        yield from _split(
            gds, G, "wccId", comp_id, node_ids, orig_id,
            original_wcc_size, bbl_counts, counter,
        )


def run(gds: GraphDataScience, session: Session):
    """
    Project the landlord graph, clean up any prior projections, and
    return an iterator over final portfolios.
    """
    print("Step 5 -- Projecting GDS graph")
    cleanup_projections(gds)
    G = project_graph(gds)
    print(f"  {G.node_count():,} nodes, {G.relationship_count():,} relationships.")

    print("Steps 6 & 7 -- WCC + Louvain splitting")
    return G, iter_portfolios(gds, G, session)
