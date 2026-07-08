"""
Targeted re-cluster of a falsified OwnershipNetwork Actor.

Usage:
    uv run python -m watchline.ingest.portfolio.recluster_actor \\
        --actor ACT-43ba2f28-537c-4e12-b53c-2c265a0df02f \\
        --exclude-address "575 FIFTH AVENUE"

What it does:
    1. Pulls all Landlord-layer edges for the affected network from the graph
       stored on the IdentityAssertion's linked IdentityObservations.
       (The Landlord nodes themselves are gone after pipeline cleanup, so we
       reconstruct the adjacency from the stored edge metadata on the
       IdentityAssertion and the Actor's bbl_set + bizaddr on hpd_contacts.)
    2. Rebuilds the adjacency graph in Python (networkx), then drops every
       CONNECTED_BY_ADDRESS edge whose shared address matches the exclusion.
    3. Runs WCC on the residual graph.
    4. For each surviving component with >= 2 BBLs:
         - Derives confidence from the surviving edge mix.
         - Matches against the existing actor registry (Jaccard >= 0.5).
         - Writes a new OwnershipNetwork Actor (or updates an existing one)
           using the same store.py helpers used by the main pipeline.
         - Writes a new IdentityAssertion and Evidence node.
         - Emits a PBC-001 Claim if the threshold is met.
         - Creates a SPLIT_INTO edge from the original (now-superseded) Actor.
    5. Marks the original Actor as superseded with a SPLIT_INTO edge to each
       surviving child.

Assumptions:
    - The graph still has the OwnershipNetwork Actor node with its bbl_set.
    - The active IdentityAssertion for this Actor is still present and carries
      the address/name edge counts in its Evidence node summary text.
    - hpd_contacts (in Postgres) is available for address reconstruction.
    - The main pipeline's Landlord nodes have already been cleared (normal
      post-pipeline state); this script works from hpd_contacts directly.

This script does NOT re-run the full WCC / Louvain GDS projection. It is a
surgical, one-off correction that operates only on the BBLs of one Actor.

Run with --dry-run to see what communities would be written without touching
the graph.
"""

import argparse
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import networkx as nx

from .config import NEO4J_DATABASE, neo4j_driver, pg_conn
from .store import (
    JACCARD_THRESHOLD,
    PBC_MIN_BBLS,
    RULE_ID_PBC001,
    RULE_ID_RMT003,
    _create_actor,
    _create_beneficial_control_relationships,
    _create_evidence,
    _create_identity_assertion,
    _create_or_update_claim,
    _derive_confidence,
    _jaccard,
    _update_actor,
    _upsert_identity_observations,
    find_matching_actor,
    preload_actor_registry,
)


# ---------------------------------------------------------------------------
# Step 1 -- Pull the affected Actor from Neo4j
# ---------------------------------------------------------------------------

def fetch_actor(session, actor_canonical_id: str) -> Dict:
    """
    Return the OwnershipNetwork Actor node and its active IdentityAssertion.
    Raises ValueError if the actor is not found or already fully superseded.
    """
    result = session.run(
        """
        MATCH (a:Actor {canonical_id: $cid, actor_type: 'OwnershipNetwork'})
        OPTIONAL MATCH (ia:IdentityAssertion)-[:RESOLVES_TO]->(a)
        WHERE ia.superseded_by IS NULL
        OPTIONAL MATCH (ia)-[:AGGREGATES|SUPPORTED_BY*0..2]-(ev:Evidence)
        RETURN
            a.canonical_id          AS canonical_id,
            a.display_name          AS display_name,
            a.bbl_set               AS bbl_set,
            a.resolution_confidence AS confidence,
            ia.iassertion_id        AS iassertion_id,
            ev.evidence_id          AS evidence_id,
            ev.summary              AS evidence_summary
        """,
        cid=actor_canonical_id,
    ).single()

    if result is None:
        raise ValueError(f"Actor {actor_canonical_id} not found in graph.")

    return dict(result)


# ---------------------------------------------------------------------------
# Step 2 -- Reconstruct the adjacency graph from Postgres hpd_contacts
# ---------------------------------------------------------------------------

def _normalize_address(housenumber: str, streetname: str) -> str:
    """Canonical form used for address matching: 'HOUSENUMBER STREETNAME'."""
    return f"{(housenumber or '').strip().upper()} {(streetname or '').strip().upper()}"



# Contact types that carry ownership signal and are used for name-based edges.
# Operational staff types (Agent, Officer, SiteManager) are excluded because
# management companies register their own employees on client buildings —
# exactly the same false-hub problem as the shared address, expressed as names.
NAME_EDGE_CONTACT_TYPES = frozenset({
    "IndividualOwner",
    "CorporateOwner",
    "JointOwner",
    "Shareholder",
    "HeadOfficer",   # registered as the owner's principal — ownership signal
})

# Contact types used for address-based edges (all types, since even an Agent
# address can be informative when it's not a high-volume management hub).
# The hub-address exclusion handles the management-company case.
ADDRESS_EDGE_CONTACT_TYPES = frozenset({
    "IndividualOwner",
    "CorporateOwner",
    "JointOwner",
    "Shareholder",
    "HeadOfficer",
    "Agent",
    "Officer",
    "SiteManager",
    "Lessee",
})


def build_adjacency_graph(
    bbl_set: Set[str],
    excluded_address: Optional[str],
) -> nx.Graph:
    """
    Reconstruct the name-based and address-based adjacency graph for the
    given BBL set by querying hpd_contacts directly.

    excluded_address: normalized canonical form ('575 FIFTH AVENUE') — any
    CONNECTED_BY_ADDRESS edge whose shared address matches this string is
    dropped before WCC.

    Name edges are built only from ownership-signal contact types
    (NAME_EDGE_CONTACT_TYPES). Operational staff contacts — Agent, Officer,
    SiteManager — are excluded from name matching because management companies
    register their own employees on client buildings, creating the same
    false-hub problem as a shared management address.

    Returns a networkx Graph where:
      - nodes are BBL strings
      - edges carry type ('name' or 'address') and weight
    """
    if not bbl_set:
        return nx.Graph()

    excluded_norm = excluded_address.strip().upper() if excluded_address else None

    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            # Pull all hpd_contacts rows for the affected BBLs.
            # We need: bbl, type, name (normalized), businesshousenumber,
            # businessstreetname, businesszip.
            cur.execute(
                """
                SELECT
                    r.bbl,
                    c.type,
                    upper(trim(coalesce(c.corporationname, c.firstname || ' ' || c.lastname, '')))
                        AS contact_name,
                    c.businesshousenumber,
                    upper(trim(coalesce(c.businessstreetname, ''))) AS businessstreetname,
                    upper(trim(coalesce(c.businessapartment, '')))  AS businessapartment,
                    c.businesszip
                FROM hpd_contacts c
                JOIN hpd_registrations r USING (registrationid)
                WHERE r.bbl = ANY(%s)
                  AND r.bbl IS NOT NULL
                  AND c.businesshousenumber IS NOT NULL
                  AND c.businessstreetname IS NOT NULL
                ORDER BY r.bbl
                """,
                (list(bbl_set),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    print(f"  {len(rows):,} hpd_contacts rows fetched for {len(bbl_set):,} BBLs.")

    # Index rows by BBL, split into name-eligible and address-eligible contacts
    bbl_to_name_contacts: Dict[str, List[Dict]] = defaultdict(list)
    bbl_to_addr_contacts: Dict[str, List[Dict]] = defaultdict(list)

    for bbl, contact_type, name, housenumber, streetname, apt, zipcode in rows:
        bbl_str = str(bbl)
        addr = _normalize_address(housenumber, streetname)
        entry = {
            "name": name or "",
            "address_norm": addr,
            "apt": (apt or "").strip().upper(),
            "zip": (zipcode or "").strip(),
        }
        if contact_type in NAME_EDGE_CONTACT_TYPES:
            bbl_to_name_contacts[bbl_str].append(entry)
        if contact_type in ADDRESS_EDGE_CONTACT_TYPES:
            bbl_to_addr_contacts[bbl_str].append(entry)

    # Use the union of BBLs that have at least one contact of either kind
    bbl_to_contacts = {
        bbl: {
            "name_contacts": bbl_to_name_contacts.get(bbl, []),
            "addr_contacts": bbl_to_addr_contacts.get(bbl, []),
        }
        for bbl in bbl_set
    }

    G = nx.Graph()
    for bbl in bbl_set:
        G.add_node(str(bbl))

    bbl_list = [b for b in bbl_to_contacts.keys() if b in bbl_set]
    n = len(bbl_list)

    name_edges_added = 0
    addr_edges_added = 0
    addr_edges_dropped = 0

    for i in range(n):
        bbl_a = bbl_list[i]
        name_contacts_a = bbl_to_contacts[bbl_a]["name_contacts"]
        addr_contacts_a = bbl_to_contacts[bbl_a]["addr_contacts"]

        for j in range(i + 1, n):
            bbl_b = bbl_list[j]
            name_contacts_b = bbl_to_contacts[bbl_b]["name_contacts"]
            addr_contacts_b = bbl_to_contacts[bbl_b]["addr_contacts"]

            # --- Name-based edges (RMT-001) ---
            # Only ownership-signal contact types (NAME_EDGE_CONTACT_TYPES).
            names_a = {c["name"] for c in name_contacts_a if c["name"]}
            names_b = {c["name"] for c in name_contacts_b if c["name"]}
            shared_names = names_a & names_b

            if shared_names:
                weight = 1.0 + len(shared_names) * 0.5  # mirrors RMT-001 weight scheme
                existing = G.get_edge_data(bbl_a, bbl_b)
                if existing and existing.get("type") == "name":
                    weight = max(weight, existing["weight"])
                if not existing or weight > existing.get("weight", 0):
                    G.add_edge(bbl_a, bbl_b, type="name", weight=weight,
                               shared=list(shared_names)[:3])
                    name_edges_added += 1

            # --- Address-based edges (RMT-002) ---
            # All contact types, but hub addresses are excluded.
            addrs_a = {
                (c["address_norm"], c["zip"])
                for c in addr_contacts_a
                if c["address_norm"]
            }
            addrs_b = {
                (c["address_norm"], c["zip"])
                for c in addr_contacts_b
                if c["address_norm"]
            }
            shared_addrs = addrs_a & addrs_b

            for addr_norm, zip_code in shared_addrs:
                # Drop edges through the excluded management company address
                if excluded_norm and excluded_norm in addr_norm:
                    addr_edges_dropped += 1
                    continue

                weight = 2.0  # base RMT-002 weight
                existing = G.get_edge_data(bbl_a, bbl_b)
                if existing and existing.get("type") == "address":
                    weight = max(weight, existing["weight"])
                if not existing or (existing.get("type") != "name" and
                                    weight > existing.get("weight", 0)):
                    G.add_edge(bbl_a, bbl_b, type="address", weight=weight,
                               shared_address=addr_norm)
                    addr_edges_added += 1

    print(f"  Graph built: {G.number_of_nodes():,} nodes, "
          f"{G.number_of_edges():,} edges "
          f"({name_edges_added:,} name, {addr_edges_added:,} address, "
          f"{addr_edges_dropped:,} address edges dropped via exclusion).")
    return G


# ---------------------------------------------------------------------------
# Step 3 -- WCC on residual graph
# ---------------------------------------------------------------------------

def run_wcc(G: nx.Graph) -> List[FrozenSet[str]]:
    """Return connected components as a list of frozensets of BBL strings."""
    components = [
        frozenset(c)
        for c in nx.connected_components(G)
        if len(c) >= 2  # singletons are never portfolios
    ]
    singletons = sum(1 for c in nx.connected_components(G) if len(c) == 1)
    print(f"  WCC: {len(components):,} multi-BBL components, "
          f"{singletons:,} singletons (discarded).")
    return components


# ---------------------------------------------------------------------------
# Step 4 -- Derive split_info for each surviving component
# ---------------------------------------------------------------------------

def _edge_counts_for_component(
    G: nx.Graph, bbl_set: FrozenSet[str]
) -> Tuple[int, int, float]:
    """Return (name_edge_count, addr_edge_count, avg_weight) for the subgraph."""
    name_edges = 0
    addr_edges = 0
    total_weight = 0.0
    edge_count = 0

    for u, v, data in G.subgraph(bbl_set).edges(data=True):
        if data.get("type") == "name":
            name_edges += 1
        else:
            addr_edges += 1
        total_weight += data.get("weight", 0.0)
        edge_count += 1

    avg_weight = total_weight / edge_count if edge_count else 0.0
    return name_edges, addr_edges, avg_weight


def _build_split_info(
    name_edges: int,
    addr_edges: int,
    original_wcc_size: int,
) -> Dict:
    """Build a split_info dict compatible with store._derive_confidence."""
    return {
        "was_split": True,   # this IS a split from the original component
        "depth": 1,
        "modularity_gain": None,
        "original_wcc_size": original_wcc_size,
        "termination_reason": "recluster_hub_removed",
    }


# ---------------------------------------------------------------------------
# Step 5 -- Supersede the original Actor
# ---------------------------------------------------------------------------

def supersede_actor(
    session,
    original_canonical_id: str,
    child_canonical_ids: List[str],
    run_id: str,
) -> None:
    """
    Mark the original Actor as superseded:
      - Set its resolution_confidence to 'Withdrawn'.
      - Supersede its active PBC-001 Claim.
      - Create SPLIT_INTO edges to each surviving child Actor.
    """
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    print(f"  Superseding original Actor {original_canonical_id} ...")

    # Withdraw confidence
    session.run(
        """
        MATCH (a:Actor {canonical_id: $cid})
        SET a.resolution_confidence = 'Withdrawn',
            a.superseded_at         = datetime($now),
            a.superseded_run_id     = $run_id
        """,
        cid=original_canonical_id,
        now=now,
        run_id=run_id,
    )

    # Supersede active PBC-001 Claim
    session.run(
        """
        MATCH (a:Actor {canonical_id: $cid})
        MATCH (a)-[:SUBJECT_OF]->(c:Claim {interpretive_concept: 'ProbableBeneficialControl'})
        WHERE c.superseded_by IS NULL
        SET c.superseded_by = 'RECLUSTER-' + $run_id,
            c.valid_to      = date($today)
        """,
        cid=original_canonical_id,
        run_id=run_id,
        today=today,
    )

    # Supersede active BeneficialControl Relationships
    session.run(
        """
        MATCH (r:Relationship {
            relationship_type: 'BeneficialControl',
            object_id: $cid
        })
        WHERE r.effective_to IS NULL
        SET r.effective_to = date($today)
        """,
        cid=original_canonical_id,
        today=today,
    )

    # Create SPLIT_INTO edges to each child
    for child_id in child_canonical_ids:
        session.run(
            """
            MATCH (parent:Actor {canonical_id: $parent_cid})
            MATCH (child:Actor  {canonical_id: $child_cid})
            MERGE (parent)-[:SPLIT_INTO]->(child)
            """,
            parent_cid=original_canonical_id,
            child_cid=child_id,
        )
    print(f"    SPLIT_INTO edges created to {len(child_canonical_ids)} child(ren).")


# ---------------------------------------------------------------------------
# Step 6 -- Write surviving components to the graph
# ---------------------------------------------------------------------------

def write_components(
    session,
    G: nx.Graph,
    components: List[FrozenSet[str]],
    original_canonical_id: str,
    original_bbl_count: int,
    actor_registry: Dict[str, set],
    run_id: str,
    dry_run: bool,
) -> List[str]:
    """
    Write each surviving WCC component as a new OwnershipNetwork Actor.
    Returns list of new canonical_ids.

    Skips the original Actor in the registry so it is never matched as a
    continuation (it is being superseded, not updated).
    """
    child_ids = []

    # Remove the original actor from the in-memory registry so it cannot be
    # matched as a continuation of itself.
    registry_copy = {
        cid: bbls
        for cid, bbls in actor_registry.items()
        if cid != original_canonical_id
    }

    for idx, bbl_component in enumerate(components, 1):
        name_edges, addr_edges, avg_weight = _edge_counts_for_component(G, bbl_component)
        split_info = _build_split_info(name_edges, addr_edges, original_bbl_count)

        has_bridge = (name_edges + addr_edges) / max(len(bbl_component), 1) < 1.5
        confidence = _derive_confidence(
            split_info,
            edge_count=name_edges + addr_edges,
            avg_weight=avg_weight,
            has_bridge=has_bridge,
        )

        # Pull display name from ownership-signal contacts only.
        # Querying all contact types here would surface management company
        # staff (Agent, Officer) as the most frequent name, since they
        # appear on every building in the portfolio. We want the owner.
        conn = pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        upper(trim(coalesce(
                            c.corporationname,
                            c.firstname || ' ' || c.lastname,
                            ''
                        ))) AS contact_name,
                        count(*) AS freq
                    FROM hpd_contacts c
                    JOIN hpd_registrations r USING (registrationid)
                    WHERE r.bbl = ANY(%s)
                      AND r.bbl IS NOT NULL
                      AND c.type IN (
                          'IndividualOwner', 'CorporateOwner',
                          'JointOwner', 'Shareholder', 'HeadOfficer'
                      )
                      AND trim(coalesce(
                              c.corporationname,
                              c.firstname || ' ' || c.lastname,
                              ''
                          )) != ''
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 1
                    """,
                    (list(bbl_component),),
                )
                row = cur.fetchone()
                display_name = row[0] if row and row[0] else "Unknown"
        finally:
            conn.close()

        print(f"\n  Component {idx}/{len(components)}: "
              f"{len(bbl_component):,} BBLs, {name_edges} name edges, "
              f"{addr_edges} addr edges, confidence={confidence}, "
              f"display_name='{display_name}'")

        if dry_run:
            print("    [dry-run] Would write Actor + Claim. Skipping.")
            continue

        # Match or create Actor
        bbl_set = set(bbl_component)
        canonical_id = find_matching_actor(registry_copy, bbl_set)
        if canonical_id:
            print(f"    Matched existing Actor {canonical_id}. Updating.")
            _update_actor(session, canonical_id, display_name, bbl_set, confidence, run_id)
            registry_copy[canonical_id] = bbl_set
        else:
            canonical_id = _create_actor(session, display_name, bbl_set, confidence, run_id)
            registry_copy[canonical_id] = bbl_set
            print(f"    Created new Actor {canonical_id}.")

        child_ids.append(canonical_id)

        # IdentityObservations -- one per BBL (minimal; full name/addr on contacts)
        landlord_infos = [{"name": display_name, "bbls": list(bbl_component)[:5]}]
        iobs_ids = _upsert_identity_observations(session, landlord_infos, run_id)

        # IdentityAssertion
        iassertion_id = _create_identity_assertion(
            session, canonical_id, iobs_ids, confidence,
            split_info, run_id,
            resolution_method_id=RULE_ID_RMT003,
        )

        # Evidence
        evidence_id = _create_evidence(
            session, iassertion_id, len(bbl_set), addr_edges, name_edges,
        )

        # PBC-001 Claim
        claim_id = _create_or_update_claim(
            session, canonical_id, display_name, bbl_set,
            confidence, evidence_id,
            addr_edges, name_edges, run_id,
        )

        if claim_id:
            _create_beneficial_control_relationships(
                session, canonical_id, bbl_set, claim_id, evidence_id, run_id,
            )
            print(f"    PBC-001 Claim {claim_id} written with "
                  f"{len(bbl_set):,} BeneficialControl relationships.")
        else:
            print(f"    PBC-001 threshold not met (confidence={confidence}, "
                  f"bbls={len(bbl_set)}, name_edges={name_edges}, "
                  f"addr_edges={addr_edges}). No Claim written.")

    return child_ids


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def recluster(
    actor_canonical_id: str,
    excluded_address: str,
    dry_run: bool = False,
) -> None:
    run_id = (
        f"RECLUSTER-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        f"-{uuid.uuid4().hex[:8]}"
    )
    print(f"=== Recluster run_id: {run_id} ===")
    print(f"  Actor:            {actor_canonical_id}")
    print(f"  Excluded address: {excluded_address}")
    print(f"  Dry run:          {dry_run}")
    print()

    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:

            # -- 1. Fetch the original Actor --
            print("Step 1 -- Fetching original Actor ...")
            actor = fetch_actor(session, actor_canonical_id)
            bbl_set = set(actor["bbl_set"] or [])
            print(f"  Found Actor '{actor['display_name']}' with "
                  f"{len(bbl_set):,} BBLs, "
                  f"confidence={actor['confidence']}.")

            if not bbl_set:
                print("  ERROR: Actor has no BBLs. Nothing to recluster.")
                return

            # -- 2. Build adjacency graph from Postgres --
            print("\nStep 2 -- Reconstructing adjacency from hpd_contacts ...")
            G = build_adjacency_graph(bbl_set, excluded_address)

            # -- 3. WCC on residual graph --
            print("\nStep 3 -- Running WCC on residual graph ...")
            components = run_wcc(G)

            if not components:
                print(
                    "  No multi-BBL components survive after removing the hub address.\n"
                    "  All BBLs are disconnected. The original Actor will be superseded\n"
                    "  with no successors (the grouping was entirely spurious)."
                )
                if not dry_run:
                    print("\nStep 4 -- Superseding original Actor (no successors) ...")
                    supersede_actor(session, actor_canonical_id, [], run_id)
                else:
                    print("[dry-run] Would supersede original Actor with no successors.")
                return

            print(f"\n  {len(components):,} surviving component(s) will be written.")

            # -- 4. Load actor registry for matching --
            print("\nStep 4 -- Loading actor registry ...")
            actor_registry = preload_actor_registry(session)

            # -- 5. Write surviving components --
            print("\nStep 5 -- Writing surviving components ...")
            child_ids = write_components(
                session, G, components,
                original_canonical_id=actor_canonical_id,
                original_bbl_count=len(bbl_set),
                actor_registry=actor_registry,
                run_id=run_id,
                dry_run=dry_run,
            )

            # -- 6. Supersede the original Actor --
            if not dry_run:
                print(f"\nStep 6 -- Superseding original Actor ...")
                supersede_actor(session, actor_canonical_id, child_ids, run_id)
            else:
                print(
                    f"\n[dry-run] Would supersede Actor {actor_canonical_id} "
                    f"with SPLIT_INTO edges to {len(child_ids)} child(ren)."
                )

    finally:
        driver.close()

    print(f"\n=== Recluster complete. run_id={run_id} ===")
    if dry_run:
        print("  No changes were written (dry-run mode).")
    else:
        print(f"  {len(components):,} new OwnershipNetwork Actor(s) written.")
        print(f"  Original Actor {actor_canonical_id} superseded.")


def main():
    parser = argparse.ArgumentParser(
        description="Re-cluster a falsified OwnershipNetwork Actor by removing a hub address."
    )
    parser.add_argument(
        "--actor",
        required=True,
        metavar="CANONICAL_ID",
        help="canonical_id of the OwnershipNetwork Actor to recluster "
             "(e.g. ACT-43ba2f28-537c-4e12-b53c-2c265a0df02f)",
    )
    parser.add_argument(
        "--exclude-address",
        required=True,
        metavar="ADDRESS",
        help="Normalized street address to exclude from edge construction "
             "(e.g. '575 FIFTH AVENUE'). Case-insensitive substring match "
             "against the reconstructed address string.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be written without modifying the graph.",
    )
    args = parser.parse_args()

    recluster(
        actor_canonical_id=args.actor,
        excluded_address=args.exclude_address,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
