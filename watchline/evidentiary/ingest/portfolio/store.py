"""
Watchline portfolio pipeline -- store stage.

Consumes the portfolio generator from algorithms.py and writes the results
into the Watchline five-layer ontology in Neo4j.

Complete rewrite of the JustFix WoW store.py. The original wrote Portfolio
nodes with BELONGS_TO edges. This version writes:

  Layer 3 (Identity):
    - IdentityObservation nodes (one per unique landlord name/address in the community)
    - IdentityAssertion nodes (one per community, linking observations to an Actor)
    - OwnershipNetwork Actor nodes (canonical, stable across runs)

  Layer 4 (Interpretation):
    - ProbableBeneficialControl Claims (Rule PBC-001)
    - BeneficialControl Relationship nodes (one per building in the network)

  Layer 2 (Evidence):
    - Evidence nodes linking Claims to IdentityAssertions
    - Source references via ORIGINATES_IN edges on IdentityObservations

  Versioned update protocol:
    - Stable communities: update IdentityAssertion, re-evaluate Claim
    - Merges: create MERGED_INTO edge, supersede old Claim
    - Splits: create SPLIT_INTO edges, supersede old Claims
    - Superseded nodes are never deleted

Rule references:
    PBC-001  (RUL-00002): Probable Beneficial Control -- generates Claims
    RMT-003  (RUL-00005): WCC Portfolio Detection -- Rule; APPLIES_METHOD -> MTH-001
    RMT-004  (RUL-00006): Louvain Community Splitting -- Rule; APPLIES_METHOD -> MTH-002

Note (2026-07-20): RUL-00005/RUL-00006 are Rules, not ResolutionMethods -- the
comment above previously conflated the two, which is exactly the bug this
change fixes. Each Rule now points to its own ResolutionMethod node
(MTH-001 / MTH-002) via APPLIES_METHOD. IdentityAssertion nodes reference the
Rule that produced them via a PRODUCED_BY edge (the same edge Claim and
Relationship already use for this purpose), not via a resolution_method_id
property. See notes/RESOLUTIONMETHOD-amendment.md.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from neo4j import Session

from .load import HPD_REGISTRATION_SOURCE

BATCH_SIZE = 200  # smaller than load.py -- inner UNWINDs multiply row count

# Rule IDs that must already exist in the graph (loaded separately)
RULE_ID_PBC001 = "RUL-00002"
RULE_ID_RMT003 = "RUL-00005"
RULE_ID_RMT004 = "RUL-00006"

# Anchor matching threshold: Jaccard similarity >= this to consider
# a new community the same as an existing OwnershipNetwork Actor
JACCARD_THRESHOLD = 0.5

# PBC-001 threshold: minimum conditions for generating a Claim
PBC_MIN_BBLS = 2


# ---------------------------------------------------------------------------
# Confidence derivation (RMT-004)
# Maps split_info from algorithms.py to High/Medium/Low per the thresholds
# defined in the RMT-004 rule record.
# ---------------------------------------------------------------------------

def _derive_confidence(
    split_info: Dict,
    edge_count: int,
    avg_weight: float,
    has_bridge: bool,
) -> str:
    """
    Derive IdentityAssertion confidence from community cohesion metrics.
    Thresholds defined in Rule RMT-004 v1.0.

    High:   > 10 edges, avg weight > 2.5, no bridge
    Medium: 3-10 edges, OR avg weight 1.5-2.5, OR one bridge
    Low:    < 3 edges, OR avg weight < 1.5, OR Louvain failed to split
    """
    termination_reason = split_info.get("termination_reason", "")

    # Community retained after failed Louvain split -> Low regardless of size
    if termination_reason == "no_meaningful_split":
        return "Low"

    if edge_count > 10 and avg_weight > 2.5 and not has_bridge:
        return "High"
    if edge_count < 3 or avg_weight < 1.5:
        return "Low"
    return "Medium"


# ---------------------------------------------------------------------------
# Anchor node matching (versioned update protocol)
# ---------------------------------------------------------------------------

def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def preload_actor_registry(session: Session) -> Dict[str, set]:
    """
    Load all existing OwnershipNetwork Actors and their BBL sets into memory
    once before the community loop. Returns {canonical_id: bbl_set}.

    This replaces the per-community find_matching_actor() query, which
    caused O(n^2) database round-trips and made the pipeline unacceptably
    slow at NYC scale.

    On the first run this returns an empty dict immediately.
    On subsequent runs the dict is used for in-memory Jaccard matching.
    """
    result = session.run(
        """
        MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
        WHERE NOT EXISTS { (a)-[:MERGED_INTO]->() }
        RETURN a.canonical_id AS canonical_id,
               a.bbl_set      AS bbl_set
        """
    )
    registry = {}
    for record in result:
        registry[record["canonical_id"]] = set(record["bbl_set"] or [])
    print(f"  Loaded {len(registry):,} existing OwnershipNetwork Actors into registry.")
    return registry


def find_matching_actor(
    registry: Dict[str, set],
    bbl_set: set,
) -> Optional[str]:
    """
    Find the existing OwnershipNetwork Actor whose BBL set has the highest
    Jaccard similarity to bbl_set, above JACCARD_THRESHOLD.

    Operates entirely in Python memory against the preloaded registry.
    Returns canonical_id of the best match, or None if no match clears
    the threshold.
    """
    if not registry:
        return None

    best_id = None
    best_score = JACCARD_THRESHOLD - 0.001

    for canonical_id, existing_bbls in registry.items():
        score = _jaccard(bbl_set, existing_bbls)
        if score > best_score:
            best_score = score
            best_id = canonical_id

    return best_id


# ---------------------------------------------------------------------------
# IdentityObservation nodes
# ---------------------------------------------------------------------------

def _upsert_identity_observations(
    session: Session,
    landlord_infos: List[Dict],
    run_id: str,
) -> List[str]:
    """
    Create or match IdentityObservation nodes for each landlord in the community.
    Returns list of iobs_ids in the same order as landlord_infos.

    Uses a single UNWIND query per community rather than one query per
    landlord — reduces Neo4j round-trips from O(landlords) to O(1) per
    community, which is the dominant source of slowness at NYC scale.

    IdentityObservations are keyed on (raw_name, source_id, context) so the
    same HPD contact appearing in multiple runs does not create duplicate nodes.
    """
    now        = datetime.now(timezone.utc).isoformat()
    source_id  = HPD_REGISTRATION_SOURCE["source_id"]

    # Assign candidate iobs_ids up front; MERGE will keep the first-written
    # value if the node already exists (CASE WHEN IS NULL pattern).
    rows = [
        {
            "iobs_id":  f"IOBS-{uuid.uuid4()}",
            "raw_name": info["name"] or "",
            "context":  f"HPD registration contact; BBLs: {','.join(info['bbls'][:5])}",
        }
        for info in landlord_infos
    ]

    result = session.run(
        """
        UNWIND $rows AS row
        MERGE (io:IdentityObservation:WatchlineNode {
            raw_name:  row.raw_name,
            source_id: $source_id,
            context:   row.context
        })
        SET io.iobs_id        = CASE WHEN io.iobs_id IS NULL
                                     THEN row.iobs_id ELSE io.iobs_id END,
            io.ingested_at    = CASE WHEN io.ingested_at IS NULL
                                     THEN datetime($now) ELSE io.ingested_at END,
            io.observation_id = CASE WHEN io.observation_id IS NULL
                                     THEN row.iobs_id ELSE io.observation_id END
        WITH io
        MATCH (s:Source {source_id: $source_id})
        MERGE (io)-[:ORIGINATES_IN]->(s)
        RETURN io.iobs_id AS iobs_id
        """,
        rows=rows,
        source_id=source_id,
        now=now,
    )

    return [record["iobs_id"] for record in result]


# ---------------------------------------------------------------------------
# OwnershipNetwork Actor creation/matching
# ---------------------------------------------------------------------------

def _create_actor(
    session: Session,
    display_name: str,
    bbl_set: set,
    confidence: str,
    run_id: str,
) -> str:
    """Create a new OwnershipNetwork Actor. Returns canonical_id."""
    now = datetime.now(timezone.utc).isoformat()
    canonical_id = f"ACT-{uuid.uuid4()}"
    session.run(
        """
        CREATE (a:Actor:WatchlineNode {
            canonical_id:          $canonical_id,
            actor_type:            'OwnershipNetwork',
            display_name:          $display_name,
            resolution_confidence: $confidence,
            bbl_set:               $bbl_set,
            run_id:                $run_id,
            created_at:            datetime($now),
            updated_at:            datetime($now)
        })
        """,
        canonical_id=canonical_id,
        display_name=display_name,
        confidence=confidence,
        bbl_set=list(bbl_set),
        run_id=run_id,
        now=now,
    )
    return canonical_id


def _update_actor(
    session: Session,
    canonical_id: str,
    display_name: str,
    bbl_set: set,
    confidence: str,
    run_id: str,
) -> None:
    """Update an existing OwnershipNetwork Actor's BBL set and confidence."""
    now = datetime.now(timezone.utc).isoformat()
    session.run(
        """
        MATCH (a:Actor {canonical_id: $canonical_id})
        SET a.bbl_set               = $bbl_set,
            a.display_name          = $display_name,
            a.resolution_confidence = $confidence,
            a.run_id                = $run_id,
            a.updated_at            = datetime($now)
        """,
        canonical_id=canonical_id,
        display_name=display_name,
        confidence=confidence,
        bbl_set=list(bbl_set),
        run_id=run_id,
        now=now,
    )


# ---------------------------------------------------------------------------
# IdentityAssertion nodes
# ---------------------------------------------------------------------------

def _create_identity_assertion(
    session: Session,
    canonical_id: str,
    iobs_ids: List[str],
    confidence: str,
    split_info: Dict,
    run_id: str,
    rule_id: str,
) -> str:
    """
    Create an IdentityAssertion linking IdentityObservations to an
    OwnershipNetwork Actor.

    Also supersedes any active IdentityAssertion for this Actor from a
    previous run.

    rule_id identifies the Rule (RUL-00005/RMT-003 or RUL-00006/RMT-004) that
    produced this assertion. A PRODUCED_BY edge to that Rule is created --
    the same pattern Claim and Relationship nodes already use -- instead of
    the old resolution_method_id string property, which aliased a Rule.rule_id
    without a real edge and left ResolutionMethod permanently empty. See
    notes/RESOLUTIONMETHOD-amendment.md.
    """
    now = datetime.now(timezone.utc).isoformat()
    iassertion_id = f"IAS-{uuid.uuid4()}"

    rationale = (
        f"Community of {split_info['original_wcc_size']} BBLs identified by "
        f"WCC (RMT-003). "
    )
    if split_info["was_split"]:
        rationale += (
            f"Split {split_info['depth']} time(s) by Louvain (RMT-004). "
            f"Termination: {split_info['termination_reason']}. "
        )
    if split_info.get("modularity_gain") is not None:
        rationale += f"Modularity: {split_info['modularity_gain']:.4f}."

    # Supersede previous active assertion for this Actor
    session.run(
        """
        MATCH (a:Actor {canonical_id: $canonical_id})
        MATCH (old_ia:IdentityAssertion)-[:RESOLVES_TO]->(a)
        WHERE old_ia.superseded_by IS NULL
        SET old_ia.superseded_by = $iassertion_id
        """,
        canonical_id=canonical_id,
        iassertion_id=iassertion_id,
    )

    # Create new IdentityAssertion, linked to the Actor and to the Rule that
    # produced it (PRODUCED_BY -- replaces the old resolution_method_id
    # property; see notes/RESOLUTIONMETHOD-amendment.md).
    session.run(
        """
        CREATE (ia:IdentityAssertion:WatchlineNode:AuditableRecord {
            iassertion_id:        $iassertion_id,
            interpretive_status:  'Inferred',
            confidence:           $confidence,
            rationale:            $rationale,
            run_id:               $run_id,
            created_at:           datetime($now),
            created_by:           'portfolio_pipeline'
        })
        WITH ia
        MATCH (a:Actor {canonical_id: $canonical_id})
        CREATE (ia)-[:RESOLVES_TO]->(a)
        WITH ia
        MATCH (r:Rule {rule_id: $rule_id})
        CREATE (ia)-[:PRODUCED_BY]->(r)
        """,
        iassertion_id=iassertion_id,
        rule_id=rule_id,
        confidence=confidence,
        rationale=rationale,
        run_id=run_id,
        now=now,
        canonical_id=canonical_id,
    )

    # Link IdentityObservations to the assertion
    if iobs_ids:
        session.run(
            """
            UNWIND $iobs_ids AS iobs_id
            MATCH (io:IdentityObservation {iobs_id: iobs_id})
            MATCH (ia:IdentityAssertion {iassertion_id: $iassertion_id})
            MERGE (ia)-[:ASSERTS_IDENTITY_OF]->(io)
            """,
            iobs_ids=iobs_ids,
            iassertion_id=iassertion_id,
        )

    return iassertion_id


# ---------------------------------------------------------------------------
# Evidence nodes
# ---------------------------------------------------------------------------

def _create_evidence(
    session: Session,
    iassertion_id: str,
    bbl_count: int,
    addr_edge_count: int,
    name_edge_count: int,
) -> str:
    """Create an Evidence node aggregating the IdentityAssertion for a Claim."""
    now = datetime.now(timezone.utc).isoformat()
    evidence_id = f"EVI-{uuid.uuid4()}"
    session.run(
        """
        CREATE (ev:Evidence:WatchlineNode {
            evidence_id: $evidence_id,
            summary:     $summary,
            created_at:  datetime($now)
        })
        WITH ev
        MATCH (ia:IdentityAssertion {iassertion_id: $iassertion_id})
        CREATE (ev)-[:AGGREGATES]->(ia)
        """,
        evidence_id=evidence_id,
        summary=(
            f"IdentityAssertion {iassertion_id} grouping {bbl_count} BBLs "
            f"via {addr_edge_count} address-based and {name_edge_count} "
            f"name-based HPD registration connections."
        ),
        iassertion_id=iassertion_id,
        now=now,
    )
    return evidence_id


# ---------------------------------------------------------------------------
# PBC-001 Claim generation
# ---------------------------------------------------------------------------

def _meets_pbc_threshold(
    bbl_set: set,
    addr_edge_count: int,
    name_edge_count: int,
    confidence: str,
) -> bool:
    """
    Evaluate Rule PBC-001 threshold:
      - Confidence Medium or above
      - At least PBC_MIN_BBLS distinct BBLs
      - At least one address-based edge OR at least two name-based edges
    """
    if confidence == "Low":
        return False
    if len(bbl_set) < PBC_MIN_BBLS:
        return False
    if addr_edge_count < 1 and name_edge_count < 2:
        return False
    return True


PBC_EXPLANATION_TEMPLATE = (
    "These {bbl_count} properties appear to be under the probable beneficial "
    "control of a single ownership network, which Watchline identifies as "
    "{display_name} (ID: {canonical_id}). This conclusion is based on "
    "{addr_edge_count} shared business address connection(s) and "
    "{name_edge_count} shared name connection(s) found in HPD registration "
    "data. The ownership network was identified using Watchline Rules "
    "RMT-001 through RMT-004, and this conclusion was generated by Rule "
    "PBC-001 v1.0. The confidence of this grouping is {confidence}.\n\n"
    "IMPORTANT: This is an inference based on patterns in HPD registration "
    "data, not a legal determination of ownership or control. The term "
    "'ownership network' refers to a cluster of registrations identified by "
    "a computational algorithm, not a legally recognized entity. This "
    "conclusion should be treated as an investigative starting point "
    "requiring further verification, not as established fact."
)


def _create_or_update_claim(
    session: Session,
    canonical_id: str,
    display_name: str,
    bbl_set: set,
    confidence: str,
    evidence_id: str,
    addr_edge_count: int,
    name_edge_count: int,
    run_id: str,
) -> Optional[str]:
    """
    Create a PBC-001 Claim for this OwnershipNetwork Actor.

    Supersedes any active Claim from a previous run.
    Returns claim_id, or None if PBC-001 threshold is not met.
    """
    if not _meets_pbc_threshold(bbl_set, addr_edge_count, name_edge_count, confidence):
        return None

    now = datetime.now(timezone.utc).isoformat()
    claim_id = f"CLM-{uuid.uuid4()}"
    bbl_count = len(bbl_set)

    claim_text = PBC_EXPLANATION_TEMPLATE.format(
        bbl_count=bbl_count,
        display_name=display_name,
        canonical_id=canonical_id,
        addr_edge_count=addr_edge_count,
        name_edge_count=name_edge_count,
        confidence=confidence,
    )

    # Supersede previous active Claim for this Actor
    session.run(
        """
        MATCH (a:Actor {canonical_id: $canonical_id})
        MATCH (a)-[:SUBJECT_OF]->(old_c:Claim)
        WHERE old_c.superseded_by IS NULL
          AND old_c.interpretive_concept = 'ProbableBeneficialControl'
        SET old_c.superseded_by = $claim_id,
            old_c.valid_to      = date($today)
        """,
        canonical_id=canonical_id,
        claim_id=claim_id,
        today=datetime.now(timezone.utc).date().isoformat(),
    )

    # Create new Claim
    session.run(
        """
        MATCH (a:Actor {canonical_id: $canonical_id})
        MATCH (r:Rule {rule_id: $rule_id})
        MATCH (ev:Evidence {evidence_id: $evidence_id})
        CREATE (c:Claim:WatchlineNode {
            claim_id:              $claim_id,
            claim_text:            $claim_text,
            interpretive_status:   'Inferred',
            interpretive_concept:  'ProbableBeneficialControl',
            subject_type:          'OwnershipNetwork',
            subject_id:            $canonical_id,
            valid_from:            date($today),
            valid_to:              null,
            run_id:                $run_id,
            created_at:            datetime($now)
        })
        CREATE (a)-[:SUBJECT_OF]->(c)
        CREATE (c)-[:SUPPORTED_BY]->(ev)
        CREATE (c)-[:PRODUCED_BY]->(r)
        """,
        claim_id=claim_id,
        claim_text=claim_text,
        canonical_id=canonical_id,
        rule_id=RULE_ID_PBC001,
        evidence_id=evidence_id,
        today=datetime.now(timezone.utc).date().isoformat(),
        run_id=run_id,
        now=now,
    )

    return claim_id


# ---------------------------------------------------------------------------
# BeneficialControl Relationship nodes (one per building)
# ---------------------------------------------------------------------------

def _create_beneficial_control_relationships(
    session: Session,
    canonical_id: str,
    bbl_set: set,
    claim_id: str,
    evidence_id: str,
    run_id: str,
) -> None:
    """
    Create BeneficialControl Relationship nodes linking each building in
    bbl_set to the OwnershipNetwork Actor. Supersedes relationships from
    previous runs for buildings that remain in this network.
    """
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    # Supersede old BeneficialControl relationships for this actor
    session.run(
        """
        MATCH (a:Actor {canonical_id: $canonical_id})
        MATCH (r:Relationship {
            relationship_type: 'BeneficialControl',
            object_id: $canonical_id
        })
        WHERE r.effective_to IS NULL
        SET r.effective_to = date($today)
        """,
        canonical_id=canonical_id,
        today=today,
    )

    # Create new relationships in batches
    bbl_list = list(bbl_set)
    rel_rule = session.run(
        "MATCH (r:Rule {rule_id: $rule_id}) RETURN r.rule_id AS rid",
        rule_id=RULE_ID_PBC001,
    ).single()

    for i in range(0, len(bbl_list), BATCH_SIZE):
        batch_bbls = bbl_list[i:i + BATCH_SIZE]
        session.run(
            """
            UNWIND $bbls AS bbl
            MATCH (b:Building {bbl: bbl})
            MATCH (a:Actor {canonical_id: $canonical_id})
            MATCH (r:Rule {rule_id: $rule_id})
            MATCH (ev:Evidence {evidence_id: $evidence_id})
            MERGE (rel:Relationship:WatchlineNode {
                relationship_id: $rel_prefix + bbl
            })
            SET rel.relationship_type   = 'BeneficialControl',
                rel.subject_id          = bbl,
                rel.object_id           = $canonical_id,
                rel.interpretive_status = 'Inferred',
                rel.basis               = 'HPD registration portfolio detection (PBC-001)',
                rel.effective_from      = date($today),
                rel.effective_to        = null,
                rel.run_id              = $run_id,
                rel.created_at          = CASE WHEN rel.created_at IS NULL
                                               THEN datetime($now) ELSE rel.created_at END
            MERGE (rel)-[:INVOLVES_ACTOR]->(a)
            MERGE (rel)-[:PRODUCED_BY]->(r)
            MERGE (rel)-[:SUPPORTED_BY]->(ev)
            """,
            bbls=batch_bbls,
            canonical_id=canonical_id,
            rule_id=RULE_ID_PBC001,
            evidence_id=evidence_id,
            rel_prefix=f"REL-PBC-{canonical_id[:8]}-",
            today=today,
            run_id=run_id,
            now=now,
        )


# ---------------------------------------------------------------------------
# RELATED_TO (ProbableAffiliation) between split siblings
# ---------------------------------------------------------------------------

def write_probable_affiliations(
    session: Session,
    orig_id_to_actors: Dict[int, List[str]],
) -> None:
    """
    For all OwnershipNetwork Actors that share an orig_id (i.e. were split
    from the same WCC component), create ProbableAffiliation Relationship
    nodes between each pair.
    """
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    for orig_id, actor_ids in orig_id_to_actors.items():
        if len(actor_ids) < 2:
            continue
        for i, id_a in enumerate(actor_ids):
            for id_b in actor_ids[i + 1:]:
                rel_id = f"REL-AFF-{uuid.uuid4()}"
                session.run(
                    """
                    MATCH (a:Actor {canonical_id: $id_a})
                    MATCH (b:Actor {canonical_id: $id_b})
                    MERGE (rel:Relationship:WatchlineNode {
                        subject_id: $id_a,
                        object_id:  $id_b,
                        relationship_type: 'ProbableAffiliation'
                    })
                    SET rel.relationship_id     = CASE WHEN rel.relationship_id IS NULL
                                                       THEN $rel_id ELSE rel.relationship_id END,
                        rel.interpretive_status = CASE WHEN rel.interpretive_status IS NULL
                                                       THEN 'Inferred' ELSE rel.interpretive_status END,
                        rel.basis               = CASE WHEN rel.basis IS NULL
                                                       THEN $basis ELSE rel.basis END,
                        rel.effective_from      = CASE WHEN rel.effective_from IS NULL
                                                       THEN date($today) ELSE rel.effective_from END,
                        rel.created_at          = CASE WHEN rel.created_at IS NULL
                                                       THEN datetime($now) ELSE rel.created_at END
                    WITH rel, a, b
                    MERGE (rel)-[:INVOLVES_ACTOR]->(a)
                    MERGE (rel)-[:INVOLVES_ACTOR]->(b)
                    """,
                    id_a=id_a,
                    id_b=id_b,
                    rel_id=rel_id,
                    basis=(
                        f"Both networks were split from the same WCC component "
                        f"(orig_id={orig_id}) and may represent a looser "
                        f"affiliation."
                    ),
                    today=today,
                    now=now,
                )


# ---------------------------------------------------------------------------
# Node info preload (unchanged from original)
# ---------------------------------------------------------------------------

def preload_node_info(session: Session) -> Dict[int, Dict]:
    """Load every Landlord's bbls and name keyed by Neo4j internal node ID."""
    result = session.run(
        "MATCH (l:Landlord) RETURN id(l) AS nodeId, l.bbls AS bbls, l.name AS name"
    )
    return {
        r["nodeId"]: {
            "bbls": list(r["bbls"] or []),
            "name": r["name"] or "",
        }
        for r in result
    }


def preload_edge_counts(session: Session) -> Dict[int, Dict]:
    """
    Load edge type counts per Landlord node for RMT-004 confidence derivation
    and PBC-001 threshold evaluation.

    Returns {nodeId: {"name_edges": int, "addr_edges": int, "avg_weight": float}}
    """
    result = session.run(
        """
        MATCH (l:Landlord)
        OPTIONAL MATCH (l)-[rn:CONNECTED_BY_NAME]-()
        OPTIONAL MATCH (l)-[ra:CONNECTED_BY_ADDRESS]-()
        WITH l,
             count(DISTINCT rn) AS name_edges,
             count(DISTINCT ra) AS addr_edges,
             avg(coalesce(rn.weight, ra.weight)) AS avg_weight
        RETURN id(l) AS nodeId, name_edges, addr_edges, avg_weight
        """
    )
    return {
        r["nodeId"]: {
            "name_edges": r["name_edges"] or 0,
            "addr_edges": r["addr_edges"] or 0,
            "avg_weight": float(r["avg_weight"] or 0.0),
        }
        for r in result
    }


# ---------------------------------------------------------------------------
# BeneficialControl reconciliation (Option A)
#
# Called after Building nodes exist in the graph (i.e. after HPD violation
# ingestion or any other pipeline that creates Building nodes).
#
# The portfolio pipeline already stores BBL sets on every OwnershipNetwork
# Actor and generates Claims. This step creates the BeneficialControl
# Relationship nodes that join the two layers -- but only once Building
# nodes actually exist to join against.
#
# Safe to re-run: uses MERGE on relationship_id to avoid duplicates.
# Also idempotent on re-runs: only creates relationships for BBLs where
# a Building node exists; skips BBLs with no Building node silently.
# ---------------------------------------------------------------------------

RECONCILE_BATCH_SIZE = 500


def reconcile_beneficial_control(session: Session) -> None:
    """
    Create BeneficialControl Relationship nodes linking Building nodes to
    OwnershipNetwork Actors, for all active PBC-001 Claims.

    Run this after Building nodes have been ingested into the graph.
    Safe to re-run: existing relationships are preserved via MERGE.
    """
    print("Reconciling BeneficialControl relationships ...")

    # Count Buildings already in graph
    building_count = session.run(
        "MATCH (b:Building) RETURN count(b) AS n"
    ).single()["n"]
    print(f"  {building_count:,} Building nodes found in graph.")

    if building_count == 0:
        print("  No Building nodes found -- skipping reconciliation.")
        print("  Re-run after building ingestion pipeline has completed.")
        return

    # Load all active PBC-001 Claims and their Actor/Evidence/Rule context
    print("  Loading active PBC-001 Claims ...")
    claims = session.run(
        """
        MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
        MATCH (a)-[:SUBJECT_OF]->(c:Claim {
            interpretive_concept: 'ProbableBeneficialControl'
        })
        WHERE c.superseded_by IS NULL
        MATCH (c)-[:SUPPORTED_BY]->(ev:Evidence)
        MATCH (r:Rule {rule_id: $rule_id})
        RETURN
            a.canonical_id AS canonical_id,
            a.bbl_set      AS bbl_set,
            c.claim_id     AS claim_id,
            ev.evidence_id AS evidence_id,
            r.rule_id      AS rule_id
        """,
        rule_id=RULE_ID_PBC001,
    ).data()

    print(f"  {len(claims):,} active Claims to reconcile.")

    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    total_created = 0
    total_skipped = 0

    for claim in claims:
        canonical_id = claim["canonical_id"]
        bbl_list = list(claim["bbl_set"] or [])
        evidence_id = claim["evidence_id"]
        rule_id = claim["rule_id"]

        if not bbl_list:
            continue

        # Process in batches
        for i in range(0, len(bbl_list), RECONCILE_BATCH_SIZE):
            batch_bbls = bbl_list[i:i + RECONCILE_BATCH_SIZE]

            summary = session.run(
                """
                UNWIND $bbls AS bbl
                MATCH (b:Building {bbl: bbl})
                MATCH (a:Actor {canonical_id: $canonical_id})
                MATCH (r:Rule {rule_id: $rule_id})
                MATCH (ev:Evidence {evidence_id: $evidence_id})
                MERGE (rel:Relationship:WatchlineNode {
                    relationship_id: 'REL-PBC-' + $canonical_id_short + '-' + bbl
                })
                SET rel.relationship_type   = CASE WHEN rel.relationship_type IS NULL
                                                   THEN 'BeneficialControl'
                                                   ELSE rel.relationship_type END,
                    rel.subject_id          = CASE WHEN rel.subject_id IS NULL
                                                   THEN bbl ELSE rel.subject_id END,
                    rel.object_id           = CASE WHEN rel.object_id IS NULL
                                                   THEN $canonical_id ELSE rel.object_id END,
                    rel.interpretive_status = CASE WHEN rel.interpretive_status IS NULL
                                                   THEN 'Inferred'
                                                   ELSE rel.interpretive_status END,
                    rel.basis               = CASE WHEN rel.basis IS NULL
                                                   THEN 'HPD registration portfolio detection (PBC-001)'
                                                   ELSE rel.basis END,
                    rel.effective_from      = CASE WHEN rel.effective_from IS NULL
                                                   THEN date($today) ELSE rel.effective_from END,
                    rel.created_at          = CASE WHEN rel.created_at IS NULL
                                                   THEN datetime($now) ELSE rel.created_at END
                WITH rel, a, r, ev, b
                MERGE (rel)-[:INVOLVES_ACTOR]->(a)
                MERGE (rel)-[:INVOLVES_BUILDING]->(b)
                MERGE (rel)-[:PRODUCED_BY]->(r)
                MERGE (rel)-[:SUPPORTED_BY]->(ev)
                RETURN count(rel) AS created
                """,
                bbls=batch_bbls,
                canonical_id=canonical_id,
                canonical_id_short=canonical_id[:8],
                rule_id=rule_id,
                evidence_id=evidence_id,
                today=today,
                now=now,
            ).single()

            total_created += summary["created"] if summary else 0

    print(f"  {total_created:,} BeneficialControl Relationship nodes created.")
    print(f"  {total_skipped:,} BBLs skipped (no matching Building node).")
    print("  Reconciliation complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    session: Session,
    portfolios: Iterable[Tuple[int, FrozenSet[int], Dict]],
) -> None:
    run_id = f"WCC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    print(f"Step 8 -- Storing portfolios as Watchline ontology nodes (run_id={run_id})")

    print("  Preloading Landlord node info ...")
    node_info = preload_node_info(session)
    edge_counts = preload_edge_counts(session)

    print("  Preloading existing OwnershipNetwork Actor registry ...")
    actor_registry = preload_actor_registry(session)

    orig_id_to_actors: Dict[int, List[str]] = {}
    total_networks = 0
    total_skipped = 0
    total_claims = 0

    for orig_id, node_ids, split_info in portfolios:

        # Aggregate community data
        all_bbls: set = set()
        landlord_infos: List[Dict] = []
        total_name_edges = 0
        total_addr_edges = 0
        total_weight = 0.0

        for nid in node_ids:
            info = node_info.get(nid, {})
            bbls = info.get("bbls", [])
            all_bbls.update(bbls)
            landlord_infos.append({
                "name": info.get("name", ""),
                "bbls": bbls,
            })
            ec = edge_counts.get(nid, {})
            total_name_edges += ec.get("name_edges", 0)
            total_addr_edges += ec.get("addr_edges", 0)
            total_weight += ec.get("avg_weight", 0.0)

        if not all_bbls:
            continue

        # Skip isolated single-node communities with no connections.
        if len(node_ids) == 1 and total_name_edges == 0 and total_addr_edges == 0:
            total_skipped += 1
            continue

        avg_weight = total_weight / len(node_ids) if node_ids else 0.0
        has_bridge = (total_name_edges + total_addr_edges) / max(len(node_ids), 1) < 1.5

        confidence = _derive_confidence(
            split_info,
            edge_count=total_name_edges + total_addr_edges,
            avg_weight=avg_weight,
            has_bridge=has_bridge,
        )

        # Edge counts are summed per node, so each edge is counted twice
        # (once per endpoint). Divide by 2 to get the actual edge count
        # for use in claim text and PBC-001 threshold evaluation.
        actual_name_edges = total_name_edges // 2
        actual_addr_edges = total_addr_edges // 2

        # Display name: the most frequent non-empty landlord name
        display_name = max(
            (li["name"] for li in landlord_infos if li["name"]),
            key=lambda n: sum(1 for li in landlord_infos if li["name"] == n),
            default="Unknown",
        )

        # Versioned update: match against in-memory registry (no DB query)
        canonical_id = find_matching_actor(actor_registry, all_bbls)
        if canonical_id:
            _update_actor(session, canonical_id, display_name, all_bbls, confidence, run_id)
            actor_registry[canonical_id] = all_bbls  # update registry with new BBL set
        else:
            canonical_id = _create_actor(session, display_name, all_bbls, confidence, run_id)
            actor_registry[canonical_id] = all_bbls  # add new actor to registry

        orig_id_to_actors.setdefault(orig_id, []).append(canonical_id)

        # Write IdentityObservations
        iobs_ids = _upsert_identity_observations(session, landlord_infos, run_id)

        # Determine which Rule (and, transitively via APPLIES_METHOD, which
        # ResolutionMethod) produced this assertion.
        rule_id = RULE_ID_RMT004 if split_info["was_split"] else RULE_ID_RMT003

        # Write IdentityAssertion
        iassertion_id = _create_identity_assertion(
            session, canonical_id, iobs_ids, confidence,
            split_info, run_id, rule_id,
        )

        # Write Evidence
        evidence_id = _create_evidence(
            session, iassertion_id, len(all_bbls),
            actual_addr_edges, actual_name_edges,
        )

        # Write PBC-001 Claim if threshold met
        claim_id = _create_or_update_claim(
            session, canonical_id, display_name, all_bbls,
            confidence, evidence_id,
            actual_addr_edges, actual_name_edges, run_id,
        )

        # Write BeneficialControl Relationships if Claim was generated
        if claim_id:
            _create_beneficial_control_relationships(
                session, canonical_id, all_bbls, claim_id, evidence_id, run_id,
            )
            total_claims += 1

        total_networks += 1
        if total_networks % 500 == 0:
            print(f"    {total_networks:,} networks written ...")

    print(f"  {total_networks:,} OwnershipNetwork Actors written.")
    print(f"  {total_skipped:,} isolated single-node communities skipped.")
    print(f"  {total_claims:,} PBC-001 Claims generated.")

    print("Step 9 -- Writing ProbableAffiliation relationships ...")
    write_probable_affiliations(session, orig_id_to_actors)
    print("  Done.")

    print("Step 10 -- Clearing intermediate Landlord nodes ...")
    session.run("MATCH (n:Landlord) DETACH DELETE n")
    print("  Done.")
