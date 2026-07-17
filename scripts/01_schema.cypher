// =============================================================================
// Watchline NYC -- Initial GRAPH TYPE Declaration
// File: watchline_schema.cypher
//
// Version : 1.1
// Date    : 2026-06-26
// Author  : Watchline NYC project team
// Status  : Draft for early development and prototyping
//
// Changelog
//   1.1 (2026-06-26): Added OwnershipNetwork to Actor.actor_type;
//       added ProbableAffiliation to Relationship.relationship_type;
//       added MERGED_INTO and SPLIT_INTO edge types between Actor nodes;
//       updated Claim.subject_type to replace Portfolio with OwnershipNetwork.
//       Rationale: ingestion pipeline adaptation to five-layer ontology
//       requires canonical Actor approach for stable portfolio identity.
//
// Prerequisites
//   Neo4j 2026.02 or later (GRAPH TYPE is a Cypher 25 preview feature)
//   Enterprise Edition, Infinigraph Edition, or any Neo4j Aura tier
//   Run against a fresh or empty database only
//   Do not run in production -- preview feature, syntax may change before GA
//
// Governing documents (must be consistent with this file)
//   watchline_nyc_charter.md
//   watchline_ontology_conceptual.md
//   watchline_ontology_implementable.md
//   watchline_design_rationale.md
//
// Versioning convention
//   Before any ALTER or DROP command against a database with data,
//   run SHOW CURRENT GRAPH TYPE and commit the output to schema_changelog.md
//   with date, author, and rationale before making changes.
//
// What GRAPH TYPE enforces here
//   - Node property types and NOT NULL constraints
//   - Key and unique constraints on canonical identifier fields
//   - Label implications (WatchlineNode on all nodes; sublabel implications)
//   - Relationship source/target pairs
//
// What pipeline code must enforce (cardinality and conditional constraints)
//   1. Every Claim has at least one SUPPORTED_BY edge to Evidence
//   2. Every Claim with interpretive_status Inferred/Derived/Estimated
//      has a PRODUCED_BY edge to a Rule
//   3. Every Evidence has at least one DERIVED_FROM edge to Observation
//   4. Every Observation has an ORIGINATES_IN edge to Source
//   5. Every IdentityAssertion has at least two ASSERTS_IDENTITY_OF edges
//   6. Every Actor has at least one RESOLVED_FROM edge to IdentityObservation
//      Exception: OwnershipNetwork Actors are resolved from IdentityAssertions,
//      not directly from IdentityObservations. Pipeline must enforce that every
//      OwnershipNetwork Actor has at least one RESOLVES_TO edge inbound from
//      an IdentityAssertion.
//   7. No deprecated Rule has PRODUCED_BY edges from active Claims
//   8. Every Relationship with interpretive_status Inferred
//      has a PRODUCED_BY edge to a Rule
//   9. Every OwnershipNetwork Actor must have a run_id property matching the
//      pipeline run that created or last updated it (for versioned update audit)
//
// Controlled vocabulary fields (enforced by pipeline, not GRAPH TYPE)
//   Actor.actor_type             : NaturalPerson | LLC | Corporation |
//                                  Partnership | GovernmentAgency | Court |
//                                  OwnershipNetwork | Other
//                                  Note: OwnershipNetwork is a virtual actor type.
//                                  It does not correspond to a legally registered
//                                  entity but to a pattern of connections in HPD
//                                  registration data identified by the portfolio
//                                  detection algorithm. Claims about an
//                                  OwnershipNetwork must always disclose this.
//   Actor.resolution_confidence  : High | Medium | Low
//   Building.borough             : Manhattan | Brooklyn | Queens |
//                                  Bronx | Staten Island
//   Claim.interpretive_status    : Observed | Derived | Estimated |
//                                  Inferred | Stipulated | Disputed
//   Claim.subject_type           : Building | Actor | Relationship |
//                                  OwnershipNetwork
//   Event.event_type             : Violation | Complaint | Inspection | Permit |
//                                  DeedTransfer | CourtFiling | Hearing |
//                                  Judgment | LienFiling | RegistrationFiling
//   Event.status                 : Open | Closed | Dismissed | Pending |
//                                  Active | Expired | Unknown
//   IdentityAssertion.confidence : High | Medium | Low
//   IdentityAssertion.interpretive_status : Observed | Inferred | Estimated
//   Relationship.interpretive_status : Observed | Derived | Inferred |
//                                       Stipulated | Disputed
//   Relationship.relationship_type : Owner | ManagingAgent | BeneficialOwner |
//                                    BeneficialControl | Officer | RegisteredAgent |
//                                    MortgageHolder | LegalRepresentative |
//                                    ProbableControl | ProbableAffiliation
//                                    Note: ProbableAffiliation links two
//                                    OwnershipNetwork Actors that were split from
//                                    the same WCC component and may represent a
//                                    looser affiliation.
//   ResolutionMethod.expected_confidence : High | Medium | Low
//   Rule.output_interpretive_status : Observed | Derived | Estimated |
//                                     Inferred | Stipulated | Disputed
// =============================================================================

ALTER CURRENT GRAPH TYPE SET {

  // ===========================================================================
  // LAYER 1: DOMAIN
  // Things that exist in the world that Watchline reasons about.
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // Building
  // Primary asset node. Canonical key is BBL (Borough-Block-Lot).
  // All source identifiers must be normalized to BBL before node creation.
  // ---------------------------------------------------------------------------
  (b:Building => :WatchlineNode {
    bbl               :: STRING NOT NULL,  // 10-digit canonical identifier
    address           :: STRING NOT NULL,  // normalized street address
    borough           :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    bin               :: STRING,           // Building Identification Number (DOB)
    latitude          :: FLOAT,            // WGS84
    longitude         :: FLOAT,            // WGS84
    building_class    :: STRING,           // NYC building classification code
    year_built        :: INTEGER,
    residential_units :: INTEGER,          // per HPD registration
    // Rent stabilization enrichment (shared substrate, loaded by evidentiary-rentstab).
    // Live on Building nodes since the rentstab pipeline shipped but not previously
    // declared here -- this closes that schema-drift gap (see notes/evidentiary-ingestion-plan.md).
    rs_units_2018     :: INTEGER,
    rs_units_2019     :: INTEGER,
    rs_units_2020     :: INTEGER,
    rs_units_2021     :: INTEGER,
    rs_units_2022     :: INTEGER,
    rs_units_2023     :: INTEGER,
    rs_units_current  :: INTEGER,
    rs_units_change   :: INTEGER,
    rs_deregulating   :: BOOLEAN,
    rs_pdfsoa_2023    :: STRING,
    // DOF ownership/assessment/zoning enrichment (pluto_latest columns not
    // pulled in by the core buildings pipeline), loaded by evidentiary-pluto-dof.
    // dof_ prefix distinguishes DOF-sourced fields from PLUTO's own core
    // substrate columns above, mirroring discovery/schema/graph_type.cypher.
    dof_ownername     :: STRING,
    dof_ownertype     :: STRING,
    dof_assessland    :: INTEGER,
    dof_assesstot     :: INTEGER,
    dof_exempttot     :: INTEGER,
    dof_zonedist1     :: STRING,
    dof_landmark      :: STRING,
    dof_histdist      :: STRING,
    created_at        :: ZONED DATETIME NOT NULL,
    updated_at        :: ZONED DATETIME NOT NULL
  }) REQUIRE b.bbl IS KEY,

  // ---------------------------------------------------------------------------
  // Actor
  // Any person, organization, or agency appearing in relation to a Building
  // or Event. actor_type distinguishes NaturalPerson, LLC, Corporation, etc.
  // OwnershipNetwork is a virtual actor type representing a cluster of
  // landlord observations identified by the portfolio detection algorithm.
  // It does not correspond to a legally registered entity.
  // Actor nodes are created by the Identity layer, not directly from source
  // data. Source data first produces IdentityObservation nodes.
  // run_id: populated only on OwnershipNetwork actors; records the pipeline
  // run that created or last updated this actor for versioned audit.
  // ---------------------------------------------------------------------------
  (a:Actor => :WatchlineNode {
    canonical_id          :: STRING NOT NULL,  // format: ACT-[uuid]
    actor_type            :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    display_name          :: STRING NOT NULL,  // set during entity resolution
    state_registration_id :: STRING,           // NY Dept of State entity ID
    ein                   :: STRING,           // Federal EIN where available
    created_at            :: ZONED DATETIME NOT NULL,
    updated_at            :: ZONED DATETIME NOT NULL,
    resolution_confidence :: STRING NOT NULL,  // controlled: High | Medium | Low
    run_id                :: STRING            // pipeline run identifier (OwnershipNetwork only)
  }) REQUIRE a.canonical_id IS KEY,

  // ---------------------------------------------------------------------------
  // Event
  // A discrete recorded occurrence associated with a Building or Actor.
  // raw_record stores the complete source record verbatim -- never modified.
  // Violation subtype properties (violation_class, open_date, days_open, etc.)
  // are stored as optional properties on Event nodes of event_type Violation.
  // ---------------------------------------------------------------------------
  (e:Event => :WatchlineNode {
    event_id        :: STRING NOT NULL,  // format: EVT-[uuid]
    event_type      :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    source_id       :: STRING NOT NULL,  // identifier from originating source system
    source_name     :: STRING NOT NULL,  // e.g. HPD, DOB, ACRIS, DHCR, OATH
    event_date      :: DATE,             // nullable: some CourtFiling records have no date
    status          :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    legal_authority :: STRING,           // statutory or regulatory basis
    description     :: STRING,           // plain-language description from source
    raw_record      :: STRING NOT NULL,  // complete source record as JSON string
    created_at      :: ZONED DATETIME NOT NULL,
    // Violation subtype properties (optional; present only on Violation events)
    violation_class :: STRING,   // HPD: A | B | C
    violation_code  :: STRING,   // source-specific code
    open_date       :: DATE,
    closed_date     :: DATE,
    days_open       :: INTEGER,  // calculated: current date minus open_date
    section         :: STRING    // Housing Maintenance Code section cited
  }) REQUIRE e.event_id IS KEY,

  // ---------------------------------------------------------------------------
  // Relationship
  // A documented or inferred connection between two Actors, or between an
  // Actor and a Building. Temporal validity tracked via effective_from/to.
  // interpretive_status and relationship_type are controlled vocabularies
  // enforced by pipeline code.
  // PRODUCED_BY edge to Rule required when interpretive_status is Inferred
  // (enforced in pipeline -- invariant 8).
  // ---------------------------------------------------------------------------
  (r:Relationship => :WatchlineNode {
    relationship_id     :: STRING NOT NULL,  // format: REL-[uuid]
    relationship_type   :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    subject_id          :: STRING NOT NULL,  // canonical_id of subject Actor
    object_id           :: STRING NOT NULL,  // canonical_id of Actor or BBL of Building
    effective_from      :: DATE,
    effective_to        :: DATE,             // null if currently in effect
    interpretive_status :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    basis               :: STRING NOT NULL,  // plain-language explanation
    created_at          :: ZONED DATETIME NOT NULL
  }) REQUIRE r.relationship_id IS KEY,

  // ===========================================================================
  // LAYER 2: EVIDENCE
  // How the system knows what it knows.
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // Source
  // An originating dataset or document. legal_authority records what the
  // source is legally empowered to assert (see Charter Principle 16).
  // ---------------------------------------------------------------------------
  (s:Source => :WatchlineNode {
    source_id        :: STRING NOT NULL,  // format: SRC-[uuid]
    source_name      :: STRING NOT NULL,
    producing_agency :: STRING NOT NULL,
    legal_authority  :: STRING,           // statute or regulation
    data_url         :: STRING,
    retrieval_date   :: DATE NOT NULL,    // date Watchline last retrieved data
    coverage_start   :: DATE,
    coverage_end     :: DATE,             // null if ongoing
    description      :: STRING NOT NULL   // what this source is empowered to assert
  }) REQUIRE s.source_id IS KEY,

  // ---------------------------------------------------------------------------
  // Observation
  // A single source record as ingested, before any transformation.
  // raw_content is stored verbatim and never modified after ingestion.
  // This is the atomic unit of evidence and the permanent audit record.
  // ---------------------------------------------------------------------------
  (o:Observation => :WatchlineNode {
    observation_id   :: STRING NOT NULL,  // format: OBS-[uuid]
    source_id        :: STRING NOT NULL,  // foreign key to Source
    raw_content      :: STRING NOT NULL,  // verbatim JSON; never modified
    ingested_at      :: ZONED DATETIME NOT NULL,
    source_record_id :: STRING            // identifier from source system
  }) REQUIRE o.observation_id IS KEY,

  // ---------------------------------------------------------------------------
  // Evidence
  // One or more Observations that together support a Claim or Relationship.
  // Cardinality invariant (at least one DERIVED_FROM edge) enforced in pipeline.
  // ---------------------------------------------------------------------------
  (ev:Evidence => :WatchlineNode {
    evidence_id :: STRING NOT NULL,  // format: EVI-[uuid]
    summary     :: STRING NOT NULL,  // plain-language summary of what this shows
    created_at  :: ZONED DATETIME NOT NULL
  }) REQUIRE ev.evidence_id IS KEY,

  // ---------------------------------------------------------------------------
  // Claim
  // A statement the system asserts about the world. Every Claim must be
  // traceable through Evidence to Observations (pipeline invariants 1 and 2).
  // interpretive_status distinguishes Observed/Derived/Estimated/Inferred/
  // Stipulated/Disputed -- enforced as controlled vocab by pipeline.
  // superseded_by records the claim_id of a replacement Claim when revised.
  // ---------------------------------------------------------------------------
  (c:Claim => :WatchlineNode {
    claim_id            :: STRING NOT NULL,  // format: CLM-[uuid]
    claim_text          :: STRING NOT NULL,  // plain-language assertion
    interpretive_status :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    subject_type        :: STRING NOT NULL,  // controlled: Building|Actor|Relationship|Portfolio
    subject_id          :: STRING NOT NULL,  // canonical_id or BBL
    valid_from          :: DATE,
    valid_to            :: DATE,             // null if currently asserted
    created_at          :: ZONED DATETIME NOT NULL,
    superseded_by       :: STRING            // claim_id of replacement, if revised
  }) REQUIRE c.claim_id IS KEY,

  // ===========================================================================
  // LAYER 3: IDENTITY
  // How observations become canonical entities.
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // IdentityObservation
  // A specific appearance of a name or identifier in a source record.
  // Multiple IdentityObservations for the same real-world entity are linked
  // via IdentityAssertion before an Actor node is created.
  // ---------------------------------------------------------------------------
  (io:IdentityObservation => :WatchlineNode {
    iobs_id        :: STRING NOT NULL,  // format: IOBS-[uuid]
    raw_name       :: STRING NOT NULL,  // name exactly as it appears in source
    source_id      :: STRING NOT NULL,  // foreign key to Source
    observation_id :: STRING NOT NULL,  // foreign key to Observation
    context        :: STRING,           // role in source record (e.g. Head Officer)
    ingested_at    :: ZONED DATETIME NOT NULL
  }) REQUIRE io.iobs_id IS KEY,

  // ---------------------------------------------------------------------------
  // IdentityAssertion
  // A reasoned judgment that two or more IdentityObservations refer to the
  // same real-world entity. Carries its own interpretive_status and confidence.
  // Pipeline invariant 5: must have at least two ASSERTS_IDENTITY_OF edges.
  // ---------------------------------------------------------------------------
  (ia:IdentityAssertion => :WatchlineNode&AuditableRecord {
    iassertion_id        :: STRING NOT NULL,  // format: IAS-[uuid]
    resolution_method_id :: STRING NOT NULL,  // foreign key to ResolutionMethod
    interpretive_status  :: STRING NOT NULL,  // controlled: Observed|Inferred|Estimated
    confidence           :: STRING NOT NULL,  // controlled: High|Medium|Low
    rationale            :: STRING NOT NULL,  // plain-language explanation
    created_at           :: ZONED DATETIME NOT NULL,
    created_by           :: STRING NOT NULL   // pipeline, algorithm, or person
  }) REQUIRE ia.iassertion_id IS KEY,

  // ---------------------------------------------------------------------------
  // ResolutionMethod
  // A named, versioned procedure for producing IdentityAssertions.
  // Examples: ExactBBLMatch, SharedRegisteredAgent, ProbabilisticNameMatch.
  // ---------------------------------------------------------------------------
  (rm:ResolutionMethod => :WatchlineNode&VersionedObject {
    method_id           :: STRING NOT NULL,  // format: RMT-[uuid]
    name                :: STRING NOT NULL,  // e.g. ExactBBLMatch
    version             :: STRING NOT NULL,
    description         :: STRING NOT NULL,
    expected_confidence :: STRING NOT NULL,  // controlled: High|Medium|Low
    effective_date      :: DATE NOT NULL
  }) REQUIRE rm.method_id IS KEY,

  // ===========================================================================
  // LAYER 4: INTERPRETATION
  // Rules that transform Evidence into Claims.
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // Rule
  // A named, versioned, documented procedure for producing a Claim from
  // Evidence. Rules are first-class ontological objects (Charter Principle 11).
  // Deprecated Rules are retained with deprecated=true; never deleted
  // (Charter Principle 15). input_types and explanation_template stored
  // as strings; arrays serialized as pipe-delimited values in pipeline.
  // ---------------------------------------------------------------------------
  (ru:Rule => :WatchlineNode&VersionedObject&AuditableRecord {
    rule_id                    :: STRING NOT NULL,  // format: RUL-[uuid]
    name                       :: STRING NOT NULL,  // short code e.g. PHC-001
    title                      :: STRING NOT NULL,  // plain-language title
    version                    :: STRING NOT NULL,
    author                     :: STRING NOT NULL,
    authority                  :: STRING NOT NULL,  // source of authority
    interpretive_concept       :: STRING NOT NULL,  // e.g. PersistentHazardousConditions
    input_types                :: STRING NOT NULL,  // pipe-delimited node type list
    threshold_description      :: STRING NOT NULL,  // plain-language threshold
    threshold_logic            :: STRING NOT NULL,  // formal/pseudocode expression
    output_interpretive_status :: STRING NOT NULL,  // controlled vocab -- enforced in pipeline
    effective_date             :: DATE NOT NULL,
    expiry_date                :: DATE,             // null if no expiry
    explanation_template       :: STRING NOT NULL,  // template with {placeholder} vars
    falsification_conditions   :: STRING NOT NULL,  // what would negate or dispute
    amendment_notes            :: STRING,           // what changed from prior version
    deprecated                 :: BOOLEAN NOT NULL  // true if superseded; never delete
  }) REQUIRE ru.rule_id IS KEY,

  // ===========================================================================
  // LAYER 5: INVESTIGATION
  // What users are trying to discover.
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // InvestigativeIntent
  // The category of question a user is asking. Used by the AI agent to
  // select Rules and graph traversal patterns. Arrays stored as
  // pipe-delimited strings; resolved by query planner at runtime.
  // ---------------------------------------------------------------------------
  (ii:InvestigativeIntent => :WatchlineNode {
    intent_id              :: STRING NOT NULL,  // format: INT-[uuid]
    name                   :: STRING NOT NULL,  // e.g. BeneficialOwnership
    description            :: STRING NOT NULL,
    applicable_rules       :: STRING NOT NULL,  // pipe-delimited rule_ids
    canonical_question_ids :: STRING NOT NULL   // pipe-delimited cq_ids
  }) REQUIRE ii.intent_id IS KEY,

  // ---------------------------------------------------------------------------
  // CanonicalQuestion
  // A reusable template for a class of user questions. Maps natural-language
  // patterns to graph traversal strategies and applicable Rules.
  // ---------------------------------------------------------------------------
  (cq:CanonicalQuestion => :WatchlineNode {
    cq_id                :: STRING NOT NULL,  // format: CQ-[uuid]
    intent_id            :: STRING NOT NULL,  // foreign key to InvestigativeIntent
    question_template    :: STRING NOT NULL,  // e.g. "Who owns {building}?"
    traversal_description :: STRING NOT NULL, // plain-language traversal plan
    required_node_types  :: STRING NOT NULL,  // pipe-delimited node type list
    applicable_rule_ids  :: STRING            // pipe-delimited rule_ids (optional)
  }) REQUIRE cq.cq_id IS KEY,

  // ===========================================================================
  // EDGES: DOMAIN LAYER
  // ===========================================================================

  (:Building)-[:HAS_EVENT =>]->(:Event),
  // Chains a later ACRIS financial instrument back to the document it
  // modifies -- MortgageAssignment/MortgageSatisfaction Event -> the
  // Mortgage Event (or prior Assignment) it references. Mirrors
  // discovery/schema/graph_type.cypher's REFERENCES declaration exactly
  // (same ref_type semantics: 'DOCID' or 'CRFN', see
  // watchline/evidentiary/ingest/acris_mortgages/pipeline.py). Populated by
  // acris_mortgages step 3, MATCH-only on both ends -- never MERGE -- so a
  // reference to a document type this graph doesn't ingest is silently
  // skipped rather than creating a placeholder Event.
  (:Event)-[:REFERENCES => { ref_type :: STRING NOT NULL }]->(:Event),
  // INVOLVES_BUILDING: Relationship -> Building
  // Connects a Relationship node (e.g. BeneficialControl) to the Building
  // it concerns. Symmetric to INVOLVES_ACTOR for the asset side.
  (:Relationship)-[:INVOLVES_BUILDING =>]->(:Building),
  // Building and Actor both imply WatchlineNode; use shared implied label to
  // avoid duplicate SUBJECT_OF declarations (one identifying type per edge type)
  (:WatchlineNode)-[:SUBJECT_OF =>]->(:Claim),
  (:Actor)-[:PARTY_TO =>]->(:Event),
  (:Relationship)-[:INVOLVES_ACTOR =>]->(:Actor),

  // ===========================================================================
  // EDGES: EVIDENCE LAYER
  // ===========================================================================

  // Event and Observation both imply WatchlineNode; collapsed to avoid
  // duplicate ORIGINATES_IN declarations
  (:WatchlineNode)-[:ORIGINATES_IN =>]->(:Source),
  (:Evidence)-[:DERIVED_FROM =>]->(:Observation),
  // AGGREGATES: Evidence -> IdentityAssertion
  // Used by the portfolio pipeline when Evidence aggregates one or more
  // IdentityAssertions rather than raw Observations. Distinct from
  // DERIVED_FROM which is reserved for Evidence -> Observation.
  (:Evidence)-[:AGGREGATES =>]->(:IdentityAssertion),
  // Claim and Relationship both imply WatchlineNode; collapsed to avoid
  // duplicate SUPPORTED_BY and PRODUCED_BY declarations
  (:WatchlineNode)-[:SUPPORTED_BY =>]->(:Evidence),
  (:WatchlineNode)-[:PRODUCED_BY =>]->(:Rule),

  // ===========================================================================
  // EDGES: IDENTITY LAYER
  // ===========================================================================

  (:Actor)-[:RESOLVED_FROM =>]->(:IdentityObservation),
  (:IdentityAssertion)-[:ASSERTS_IDENTITY_OF =>]->(:IdentityObservation),
  (:IdentityAssertion)-[:RESOLVES_TO =>]->(:Actor),

  // Versioned update edges for OwnershipNetwork Actors.
  // MERGED_INTO: two OwnershipNetwork Actors from a previous run that now
  //   form a single community. The superseded Actor points to the surviving one.
  // SPLIT_INTO: one OwnershipNetwork Actor from a previous run that now
  //   forms two or more communities. The original points to each fragment.
  (:Actor)-[:MERGED_INTO =>]->(:Actor),
  (:Actor)-[:SPLIT_INTO =>]->(:Actor),

  // ===========================================================================
  // EDGES: INTERPRETATION LAYER
  // ===========================================================================

  (:Rule)-[:SUPERSEDED_BY =>]->(:Rule)

}

// =============================================================================
// POST-CREATION VERIFICATION
// After running the above, verify the schema with:
//
//   SHOW CURRENT GRAPH TYPE
//
// Commit the output to schema_changelog.md as the Version 1.0 baseline
// before making any further changes.
//
// Expected constraint count: approximately 20-25 constraints generated
// automatically by Neo4j from this declaration.
// =============================================================================
