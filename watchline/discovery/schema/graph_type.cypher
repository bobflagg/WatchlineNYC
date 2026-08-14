// ============================================================================
// Watchline DISCOVERY KG — graph type (GQL schema)
// watchline/discovery/schema/graph_type.cypher
//
// Single source of truth for the discovery graph's schema. Applied with
// `ALTER CURRENT GRAPH TYPE SET`, which REPLACES the entire graph type and
// all existing constraints. Therefore:
//   - Keep this file authoritative: any schema change is made HERE, then
//     re-applied. Do not add element types out-of-band with EXTEND unless you
//     immediately fold them back into this file.
//   - Apply this ONCE on the empty discovery database, before the buildings
//     pipeline, so every write is validated from the first row.
//
// Requirements: Neo4j 2026.06+ Enterprise (graph types GA), Cypher 25.
// Open schema: only the declared element types are constrained; anything
// undeclared is left untouched.
//
// This is the DISCOVERY type — deliberately NO Observation / Evidence / Claim /
// Rule / IdentityAssertion element types. Those belong to the epistemic graph.
// Lead / Explore element types (CONCERNS, MOTIVATED_BY) are also out of scope
// for now — reintroduce if/when that feature comes back into scope.
// ============================================================================

ALTER CURRENT GRAPH TYPE SET {

  // ---- Node element types (identifying label => implied label) -------------

  (:Building => :WatchlineNode {
     bbl               :: STRING IS KEY,
     address           :: STRING,
     borough           :: STRING,
     bin               :: STRING,
     latitude          :: FLOAT,
     longitude         :: FLOAT,
     residential_units :: INTEGER,
     year_built        :: INTEGER,
     building_class    :: STRING,
     // Rent stabilization enrichment (ADR-014: shared substrate, loaded by discovery-rentstab)
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
     // pulled in by the core buildings pipeline), loaded by discovery-pluto-dof.
     // dof_ prefix distinguishes DOF-sourced fields from PLUTO's own core
     // substrate columns above and signals provenance, same convention rs_
     // uses for DHCR-sourced rent stabilization fields.
     dof_ownername     :: STRING,
     dof_ownertype     :: STRING,
     dof_assessland    :: INTEGER,
     dof_assesstot     :: INTEGER,
     dof_exempttot     :: INTEGER,
     dof_zonedist1     :: STRING,
     dof_landmark      :: STRING,
     dof_histdist      :: STRING,
     created_at        :: ZONED DATETIME,
     updated_at        :: ZONED DATETIME
  }),

  (:Actor => :WatchlineNode {
     actor_id   :: STRING IS KEY,
     nodeid     :: INTEGER,
     name       :: STRING,
     bizaddr    :: STRING,
     bbls       :: LIST<STRING NOT NULL>,  // inner type must be NOT NULL; property itself is optional
     created_at :: ZONED DATETIME,
     updated_at :: ZONED DATETIME
  }),

  // Actors identified as controlling one or more buildings (via the
  // portfolio pipeline's landlord-detection heuristics) carry this label in
  // addition to :Actor. Implies :WatchlineNode directly rather than :Actor,
  // since a label can't be both identifying (in :Actor's own declaration
  // above) and implied elsewhere (gql_status 22NC4) — actor_id IS KEY
  // continues to be enforced separately via the :Actor declaration, since
  // every :Landlord node also carries :Actor. bbls is required here: every
  // landlord-labeled node has a populated bbls list; plain :Actor nodes do
  // not.
  (:Landlord => :WatchlineNode {
     bbls :: LIST<STRING NOT NULL> NOT NULL
  }),

  (:Event => :WatchlineNode {
     event_id         :: STRING IS KEY,
     event_type       :: STRING NOT NULL,
     source_name      :: STRING NOT NULL,
     source_id        :: STRING,
     source_record_id :: STRING,
     event_date       :: DATE,            // nullable: many records omit dates
     status           :: STRING,
     violation_class  :: STRING,
     legal_authority  :: STRING,
     raw_record       :: STRING,
     created_at       :: ZONED DATETIME
  }),

  (:Portfolio => :WatchlineNode {
     portfolio_id      :: STRING IS KEY,
     run_id            :: STRING NOT NULL,
     method            :: STRING NOT NULL,
     generated_at      :: ZONED DATETIME,
     member_count      :: INTEGER,
     building_count    :: INTEGER,
     residential_units :: INTEGER
  }),

  // ---- Relationship element types ------------------------------------------

  (:Building)-[:HAS_EVENT =>]->(:Event),

  // role is nullable in v1: sourced from wow_landlords (which lacks the contact
  // type). Populating role from hpd_contacts is a deferred refinement requiring
  // a deterministic contact->nodeid resolution step (see hpd_registrations).
  // Source is :Actor, not :Landlord: hpd_registrations/pipeline.py writes this
  // edge from the Actor node it just created in the same run, before the
  // portfolio pipeline has necessarily attached the landlord label —
  // requiring :Landlord here would break that pipeline's real write order.
  (:Actor)-[:REGISTERED_FOR => {
     role                  :: STRING,
     registrationid        :: INTEGER,
     registration_end_date :: DATE
  }]->(:Building),

  // Left on :Actor deliberately (not :Landlord): any actor — landlord or not —
  // can be party to an event (e.g. a tenant filing a complaint).
  (:Actor)-[:PARTY_TO => { role :: STRING }]->(:Event),

  // Chains a later ACRIS financial instrument back to the document it
  // modifies -- MortgageAssignment/MortgageSatisfaction Event -> the
  // Mortgage Event (or prior Assignment) it references. Populated by
  // acris_mortgages step 3 from real_property_references, resolved via
  // referencebydocid (exact) or, when that's blank, via referencebycrfn
  // joined back to real_property_master.crfn (also exact -- CRFN is a
  // unique recording number, not a fuzzy match). ref_type records which
  // of the two resolved the edge, for traceability. Both endpoints MUST
  // already exist as Event nodes (event_id = EVT-ACRIS-<documentid>) --
  // this is deliberately MATCH, never MERGE, on either side, so a
  // reference to a document type this graph doesn't ingest (e.g. AGMT,
  // PAT) is silently skipped rather than creating a placeholder Event.
  (:Event)-[:REFERENCES => { ref_type :: STRING NOT NULL }]->(:Event),

  // Written exclusively by portfolio/pipeline.py, after it has already
  // attached :Landlord (and bbls) to both endpoint nodes in one atomic write.
  (:Landlord)-[:CONNECTED_BY_NAME => { weight :: FLOAT NOT NULL }]->(:Landlord),

  (:Landlord)-[:CONNECTED_BY_ADDRESS => { weight :: FLOAT NOT NULL }]->(:Landlord),

  (:Landlord)-[:MEMBER_OF =>]->(:Portfolio),

  (:Building)-[:IN_PORTFOLIO =>]->(:Portfolio),

  // Heuristic discovery edge — never an ownership claim. The graph type can
  // enforce that `heuristic` exists and is boolean, but NOT that it is `true`;
  // the pipeline + code review guarantee the value.
  (:Landlord)-[:APPARENT_CONTROL => {
     heuristic    :: BOOLEAN NOT NULL,
     method       :: STRING NOT NULL,
     run_id       :: STRING NOT NULL,
     generated_at :: ZONED DATETIME
  }]->(:Building)

}
