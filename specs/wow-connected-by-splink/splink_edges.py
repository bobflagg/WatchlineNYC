"""portfoliograph/splink_edges.py  (proposed addition to JustFixNYC/who-owns-what)

Splink same-owner edges for the portfolio graph — the CONNECTED_BY_SPLINK contribution.

WoW already links landlord nodes by matching *names* and *business addresses*, then
clusters with WCC + recursive Louvain. Its blind spot: it can't bridge an owner's own
fragments when a business-address typo or a second office defeats the address match
(Steven Croman shows as ~6 portfolios instead of 1). This module resolves HPD owner
contacts into probabilistic entities (precision-first record linkage) and adds ONE more
edge type — ``type="splink"`` — between the nodes that resolve to the same owner. WCC and
Louvain are unchanged; they just cluster a graph that now has a third, high-confidence
edge.

Because edges only ADD, connected components can only merge, never split: an existing
address-nexus portfolio (a shell operation sharing one managing office) is preserved,
while an owner's scattered offices collapse into one.

Resolution engine: ``nyc-landlord-resolution`` (``pip install``) — an extracted,
gold-set-validated Splink model (name-anchored blocking + first-name & common-name
vetoes), so it never fuses namesakes. It exposes one function used here:

    nlr.owner_index(conn) -> dict[(NAME, bbl), owner_id]
        Resolve HPD owner contacts and return, for every (normalized owner name, bbl),
        the id of the owner entity it belongs to. Runs the full population once (~1 min).
"""
from collections import Counter, defaultdict

import networkx as nx
from nlr import normalize_name, owner_index

# Two tuning levers, both safe (edges only ever ADD, never remove):
#   * SPLINK_WEIGHT — outweighs name (~1.5) / address (~1.0) links so Louvain keeps a
#     resolved owner's nodes together if it splits an oversized (> MAX_SIZE) component.
#   * the resolution's recall lives in the ENGINE (owner_index's training slice; see the
#     PR notes). Both affect *how much* consolidation, never whether namesakes get fused.
SPLINK_WEIGHT = 10.0


def add_to_graph(g: nx.Graph, contacts, conn, weight: float = SPLINK_WEIGHT) -> int:
    """Add ``type="splink"`` edges between graph nodes that resolve to the same owner.

    ``contacts`` are the ``ConnectedLandlordRow`` rows already loaded into ``g`` (node id
    == ``contact.nodeid``). We resolve owners from ``hpd_contacts`` and map each graph
    node to an owner by an exact ``(owner name, bbl)`` join — both sides carry it, from
    the same HPD registration — then add a clique per owner. Returns edges added.
    """
    owners = owner_index(conn)                       # {(NAME, bbl): owner_id}

    # Map each node to an owner via the plurality owner across its bbls.
    node_owner = {}
    for c in contacts:
        votes = Counter(owners.get((normalize_name(c.name), bbl)) for bbl in c.bbls)
        votes.pop(None, None)
        if votes:
            node_owner[c.nodeid] = votes.most_common(1)[0][0]

    by_owner = defaultdict(list)
    for nodeid, owner in node_owner.items():
        by_owner[owner].append(nodeid)

    added = 0
    for nodeids in by_owner.values():
        for i in range(len(nodeids)):
            for j in range(i + 1, len(nodeids)):
                if not g.has_edge(nodeids[i], nodeids[j]):
                    g.add_edge(nodeids[i], nodeids[j], type="splink", weight=weight)
                    added += 1
    return added
