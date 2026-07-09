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
// undeclared (e.g. legacy :Landlord) is left untouched.
//
// This is the DISCOVERY type — deliberately NO Observation / Evidence / Claim /
// Rule / IdentityAssertion element types. Those belong to the epistemic graph.
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
  (:Actor)-[:REGISTERED_FOR => {
     role                  :: STRING,
     registrationid        :: INTEGER,
     registration_end_date :: DATE
  }]->(:Building),

  (:Actor)-[:PARTY_TO => { role :: STRING }]->(:Event),

  (:Actor)-[:CONNECTED_BY_NAME => { weight :: FLOAT NOT NULL }]->(:Actor),

  (:Actor)-[:CONNECTED_BY_ADDRESS => { weight :: FLOAT NOT NULL }]->(:Actor),

  (:Actor)-[:MEMBER_OF =>]->(:Portfolio),

  (:Building)-[:IN_PORTFOLIO =>]->(:Portfolio),

  // Heuristic discovery edge — never an ownership claim. The graph type can
  // enforce that `heuristic` exists and is boolean, but NOT that it is `true`;
  // the pipeline + code review guarantee the value.
  (:Actor)-[:APPARENT_CONTROL => {
     heuristic    :: BOOLEAN NOT NULL,
     method       :: STRING NOT NULL,
     run_id       :: STRING NOT NULL,
     generated_at :: ZONED DATETIME
  }]->(:Building)

}
