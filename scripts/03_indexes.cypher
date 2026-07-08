// =============================================================================
// Watchline NYC -- Index Setup Script
// File: scripts/03_indexes.cypher
//
// Purpose: Create all non-constraint indexes required for query performance.
//          Constraint-based indexes (on key properties) are created
//          automatically by watchline_schema.cypher and do not appear here.
//
// Run order in a full KG rebuild:
//   01_schema.cypher     -- GRAPH TYPE enforcement + key constraints
//   02_seed_rules.cypher -- Rule nodes
//   03_indexes.cypher    -- THIS FILE: performance indexes
//   [ingest pipelines]
//
// These indexes are safe to run on a populated database -- all use
// IF NOT EXISTS so re-running is harmless. They are also safe to run
// before data is loaded; Neo4j will populate them as data arrives.
//
// After running, monitor build progress with:
//   SHOW INDEXES
//   YIELD name, state, populationPercent
//   WHERE state <> 'ONLINE'
//   RETURN name, state, populationPercent
//   ORDER BY name
//
// All indexes should reach ONLINE before running ingestion pipelines
// in production. For development, pipelines can run while indexes build.
//
// Version: 1.1 -- July 2026 (added composite indexes for ManagedBy/ManagingAgent)
// =============================================================================


// ---------------------------------------------------------------------------
// EVENT INDEXES
// Event is the largest label (15M+ nodes). All filtering properties need
// indexes. The composite index on (violation_class, status) is used by
// PHC-001 evaluation: finding open Class C violations efficiently.
// ---------------------------------------------------------------------------

CREATE INDEX event_source_name IF NOT EXISTS
FOR (e:Event) ON (e.source_name);

CREATE INDEX event_status IF NOT EXISTS
FOR (e:Event) ON (e.status);

CREATE INDEX event_violation_class IF NOT EXISTS
FOR (e:Event) ON (e.violation_class);

CREATE INDEX event_interpretive_status IF NOT EXISTS
FOR (e:Event) ON (e.interpretive_status);

// Composite index for PHC-001: open Class C violations
CREATE INDEX event_class_status IF NOT EXISTS
FOR (e:Event) ON (e.violation_class, e.status);

// Already created during ECB investigation -- included here for completeness
CREATE INDEX event_source_record_id IF NOT EXISTS
FOR (e:Event) ON (e.source_record_id);


// ---------------------------------------------------------------------------
// BUILDING INDEXES
// Buildings are the primary entry point for most investigative queries.
// ---------------------------------------------------------------------------

CREATE INDEX building_borough IF NOT EXISTS
FOR (b:Building) ON (b.borough);

CREATE INDEX building_address IF NOT EXISTS
FOR (b:Building) ON (b.address);


// ---------------------------------------------------------------------------
// ACTOR INDEXES
// Used for ownership network queries and display name lookups.
// ---------------------------------------------------------------------------

CREATE INDEX actor_actor_type IF NOT EXISTS
FOR (a:Actor) ON (a.actor_type);

CREATE INDEX actor_display_name IF NOT EXISTS
FOR (a:Actor) ON (a.display_name);

CREATE INDEX actor_resolution_confidence IF NOT EXISTS
FOR (a:Actor) ON (a.resolution_confidence);

// Composite index for ManagingAgent name resolution.
// Pattern: MATCH (a:Actor {actor_type: 'ManagingAgent', display_name: $name})
CREATE INDEX actor_type_display_name IF NOT EXISTS
FOR (a:Actor) ON (a.actor_type, a.display_name);


// ---------------------------------------------------------------------------
// CLAIM INDEXES
// Used by the AI agent to retrieve claims by type and status.
// ---------------------------------------------------------------------------

CREATE INDEX claim_interpretive_concept IF NOT EXISTS
FOR (c:Claim) ON (c.interpretive_concept);

CREATE INDEX claim_subject_type IF NOT EXISTS
FOR (c:Claim) ON (c.subject_type);

CREATE INDEX claim_interpretive_status IF NOT EXISTS
FOR (c:Claim) ON (c.interpretive_status);

// Composite index for PHC and PBC lookups by subject.
// Critical for PortfolioCondition and WorstFirst: these queries
// look up Claims by (interpretive_concept, subject_id) for every
// building in every portfolio. Without this index, each lookup
// scans all 41K PHC Claims.
CREATE INDEX claim_concept_subject IF NOT EXISTS
FOR (c:Claim) ON (c.interpretive_concept, c.subject_id);


// ---------------------------------------------------------------------------
// RELATIONSHIP INDEXES
// Used for BeneficialControl and ProbableAffiliation traversals.
// ---------------------------------------------------------------------------

CREATE INDEX relationship_relationship_type IF NOT EXISTS
FOR (r:Relationship) ON (r.relationship_type);

CREATE INDEX relationship_interpretive_status IF NOT EXISTS
FOR (r:Relationship) ON (r.interpretive_status);

// Composite index for ManagedBy traversals: find all buildings for a given
// managing agent. Pattern: WHERE r.relationship_type = 'ManagedBy'
//                            AND r.object_id = $canonical_id
CREATE INDEX relationship_type_object IF NOT EXISTS
FOR (r:Relationship) ON (r.relationship_type, r.object_id);


// ---------------------------------------------------------------------------
// IDENTITY LAYER INDEXES
// Used during portfolio pipeline re-runs and entity resolution queries.
// ---------------------------------------------------------------------------

CREATE INDEX identity_observation_raw_name IF NOT EXISTS
FOR (io:IdentityObservation) ON (io.raw_name);

CREATE INDEX identity_assertion_confidence IF NOT EXISTS
FOR (ia:IdentityAssertion) ON (ia.confidence);

CREATE INDEX identity_assertion_run_id IF NOT EXISTS
FOR (ia:IdentityAssertion) ON (ia.run_id);


// ---------------------------------------------------------------------------
// OBSERVATION INDEXES
// Used for evidence chain traversal and audit queries.
// ---------------------------------------------------------------------------

CREATE INDEX observation_source_id IF NOT EXISTS
FOR (o:Observation) ON (o.source_id);

// Composite index for Evidence → Observation linking in PHC-001 and other
// evaluation pipelines. LINK_EVIDENCE_CYPHER matches on source_record_id
// + source_id; without this index it scans all 15M+ Observation nodes.
CREATE INDEX observation_source_record_id IF NOT EXISTS
FOR (o:Observation) ON (o.source_record_id);

CREATE INDEX observation_source_record_source IF NOT EXISTS
FOR (o:Observation) ON (o.source_record_id, o.source_id);


// =============================================================================
// VERIFICATION
// After all indexes reach ONLINE state, run these queries to confirm
// the most common investigative patterns are fast:
//
// -- Should return in < 100ms with indexes
// MATCH (e:Event {source_name: 'HPD', status: 'Open', violation_class: 'C'})
// RETURN count(e);
//
// -- Should return in < 100ms with indexes
// MATCH (a:Actor {actor_type: 'OwnershipNetwork'})
// RETURN count(a);
//
// -- Should return in < 500ms with indexes
// MATCH (bld:Building {borough: 'Bronx'})-[:HAS_EVENT]->(e:Event)
// WHERE e.violation_class = 'C' AND e.status = 'Open'
// RETURN count(e);
//
// -- Should return in < 100ms once agents pipeline has run (ManagingAgent path)
// MATCH (a:Actor {actor_type: 'ManagingAgent'})
// RETURN count(a);
//
// -- Should return in < 500ms with composite index (ManagedBy traversal)
// MATCH (r:Relationship {relationship_type: 'ManagedBy'})
// MATCH (r)-[:INVOLVES_BUILDING]->(b:Building)
// RETURN count(b);
// =============================================================================
