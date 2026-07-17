// =============================================================================
// Watchline NYC -- Investigative Intent + Canonical Question Seed Script
// File: 04_seed_investigative_intents.cypher
//
// Purpose: Populate Layer 5 (Investigation Nodes) of the ontology --
//          InvestigativeIntent and CanonicalQuestion -- which was specified
//          in documents/ontology-implementable.md and scripts/01_schema.cypher
//          from day one but never seeded. Closes a real gap against Charter
//          Principle 17 (Deterministic AI Orchestration): "Every conditional
//          transition must be justified by a defined Rule or Canonical
//          Question in the ontology." Until this script runs, the
//          identify_intent -> select_rules routing decision in
//          watchline/fw/ is justified by nothing but an LLM prompt
//          (watchline/fw/intent.py::INTENT_SYSTEM_PROMPT) -- there is no
//          InvestigativeIntent or CanonicalQuestion node in the graph for
//          watchline/fw/router.py::select_rules to check the LLM's
//          classification against.
//
// Prerequisites:
//   1. scripts/01_schema.cypher must have been run first (declares the
//      InvestigativeIntent and CanonicalQuestion node types).
//   2. Run this script once against the evidentiary Neo4j database.
//   3. Verify with: MATCH (ii:InvestigativeIntent) RETURN ii.name, ii.intent_id
//                    MATCH (cq:CanonicalQuestion) RETURN cq.cq_id, cq.intent_id
//
// One InvestigativeIntent per fw/intents REGISTRY entry (13 -- excludes
// General, which is a catch-all fallback, not a named investigative
// question). Descriptions are drawn verbatim from the one-line definitions
// already approved for production use in intent.py::INTENT_SYSTEM_PROMPT,
// so this script does not introduce new, unreviewed language.
//
// applicable_rules and canonical_question_ids are stored as pipe-delimited
// strings, matching the convention already used for Rule.input_types (see
// 02_seed_rules.cypher) and documented in 01_schema.cypher's comment:
// "Arrays stored as pipe-delimited strings; resolved by query planner at
// runtime." rule_id values below were verified against the actual
// _GRAPH_RULE_ID constants in each watchline/fw/intents/*.py handler file,
// not copied from CLAUDE.md's Rule table, which is stale (it lists
// RUL-00009 as the highest rule_id; RUL-00010 through RUL-00014 already
// exist in the handler code as of this script).
//
// CanonicalQuestion question_templates are generalized directly from real
// tested questions supplied by the project owner (2026-07-16), not
// invented for this script. Where two phrasings were tested for the same
// intent (EnforcementAccountability, OwnershipChange), both are seeded --
// this is the intended many-to-one cardinality: InvestigativeIntent.
// canonical_question_ids is an array precisely because more than one
// template can map to the same intent.
//
// Version: 1.0 -- July 2026
// =============================================================================


// -----------------------------------------------------------------------------
// INT-00001 -- DeteriorationTrajectory
// Tested question: "Is 122 West 97th Street in Manhattan getting worse?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00001'})
SET
  ii.name                 = 'DeteriorationTrajectory',
  ii.description          = 'Is this building getting worse over time (violation trend)?',
  ii.applicable_rules     = 'RUL-00007',
  ii.canonical_question_ids = 'CQ-00001';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00001'})
SET
  cq.intent_id             = 'INT-00001',
  cq.question_template     = 'Is {building} in {borough} getting worse?',
  cq.traversal_description = 'Fetch annual open/closed Class A/B/C violation counts for the building and evaluate DT-001 trend thresholds year over year.',
  cq.required_node_types   = 'Building|Event',
  cq.applicable_rule_ids   = 'RUL-00007';


// -----------------------------------------------------------------------------
// INT-00002 -- PortfolioIdentification
// Tested question: "Who controls 530 East 169th Street in the Bronx?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00002'})
SET
  ii.name                 = 'PortfolioIdentification',
  ii.description          = 'Who actually controls this building (trace through LLC layers)?',
  ii.applicable_rules     = 'RUL-00002',
  ii.canonical_question_ids = 'CQ-00002';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00002'})
SET
  cq.intent_id             = 'INT-00002',
  cq.question_template     = 'Who controls {building} in {borough}?',
  cq.traversal_description = 'Follow BeneficialControl Relationship from Building to Actor, then fetch the ProbableBeneficialControl Claim for that Actor.',
  cq.required_node_types   = 'Building|Relationship|Actor|Claim',
  cq.applicable_rule_ids   = 'RUL-00002';


// -----------------------------------------------------------------------------
// INT-00003 -- PortfolioCondition
// Tested question: "How bad is Mark Engel's record across all his buildings?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00003'})
SET
  ii.name                 = 'PortfolioCondition',
  ii.description          = 'How bad is this landlord''s record across all their buildings?',
  ii.applicable_rules     = 'RUL-00001',
  ii.canonical_question_ids = 'CQ-00003';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00003'})
SET
  cq.intent_id             = 'INT-00003',
  cq.question_template     = 'How bad is {actor}''s record across all their buildings?',
  cq.traversal_description = 'Resolve Actor, follow BeneficialControl to every Building in the portfolio, count how many satisfy the PHC-001 PersistentHazardousConditions Claim.',
  cq.required_node_types   = 'Actor|Relationship|Building|Claim',
  cq.applicable_rule_ids   = 'RUL-00001';


// -----------------------------------------------------------------------------
// INT-00004 -- Recidivism
// Tested question: "Has Margaret Brunn let hazardous conditions persist repeatedly?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00004'})
SET
  ii.name                 = 'Recidivism',
  ii.description          = 'Has this landlord let hazardous conditions persist repeatedly?',
  ii.applicable_rules     = 'RUL-00013',
  ii.canonical_question_ids = 'CQ-00004';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00004'})
SET
  cq.intent_id             = 'INT-00004',
  cq.question_template     = 'Has {actor} let hazardous conditions persist repeatedly?',
  cq.traversal_description = 'Resolve Actor''s portfolio, aggregate multi-year PHC trajectory across buildings, apply RCV-001 persistence thresholds.',
  cq.required_node_types   = 'Actor|Relationship|Building|Event',
  cq.applicable_rule_ids   = 'RUL-00013';


// -----------------------------------------------------------------------------
// INT-00005 -- WorstFirst
// Tested question: "Who is the worst landlord in NYC?"
// Dataset-level query -- no named entity; router.py bypasses entity
// resolution for this intent_category.
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00005'})
SET
  ii.name                 = 'WorstFirst',
  ii.description          = 'Which buildings or landlords should be inspected first?',
  ii.applicable_rules     = '',
  ii.canonical_question_ids = 'CQ-00005';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00005'})
SET
  cq.intent_id             = 'INT-00005',
  cq.question_template     = 'Who is the worst landlord in NYC?',
  cq.traversal_description = 'Rank Actors by PHC-flagged building count weighted by portfolio size, no named entity required.',
  cq.required_node_types   = 'Actor|Relationship|Building|Claim',
  cq.applicable_rule_ids   = '';


// -----------------------------------------------------------------------------
// INT-00006 -- ConcealmentDetection
// Tested question: "Are LLCs being used to hide someone's identity in the
// Kamran Hakim portfolio?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00006'})
SET
  ii.name                 = 'ConcealmentDetection',
  ii.description          = 'Is someone using LLCs or name variations to obscure identity?',
  ii.applicable_rules     = 'RUL-00003|RUL-00004',
  ii.canonical_question_ids = 'CQ-00006';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00006'})
SET
  cq.intent_id             = 'INT-00006',
  cq.question_template     = 'Are LLCs being used to hide someone''s identity in the {actor} portfolio?',
  cq.traversal_description = 'Fetch IdentityObservation/IdentityAssertion records for the Actor and the PBC claim_text, flag if address-based connections dominate over name-based connections.',
  cq.required_node_types   = 'Actor|IdentityAssertion|IdentityObservation|Claim',
  cq.applicable_rule_ids   = 'RUL-00003|RUL-00004';


// -----------------------------------------------------------------------------
// INT-00007 -- GeographicConcentration
// Tested question: "Are there clusters of troubled buildings in the Bronx?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00007'})
SET
  ii.name                 = 'GeographicConcentration',
  ii.description          = 'Is there a cluster of troubled buildings in a particular neighborhood?',
  ii.applicable_rules     = '',
  ii.canonical_question_ids = 'CQ-00007';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00007'})
SET
  cq.intent_id             = 'INT-00007',
  cq.question_template     = 'Are there clusters of troubled buildings in {borough}?',
  cq.traversal_description = 'Group PHC-flagged buildings by borough (optionally filtered), count buildings and affected units.',
  cq.required_node_types   = 'Building|Claim',
  cq.applicable_rule_ids   = '';


// -----------------------------------------------------------------------------
// INT-00008 -- OwnershipChange
// Tested questions:
//   "Did conditions change after 883 East 180 Street in the Bronx was sold?"
//   "Did conditions change after 122 West 97th Street in Manhattan was sold?"
// Note: CLAUDE.md flags this intent as data-constrained pending historical
// registration snapshots, but watchline/fw/intents/ownership_change.py is
// registered and implemented (RUL-00014 / OC-001) as of this script --
// CLAUDE.md's guidance here appears stale relative to the code. Seeding
// this InvestigativeIntent regardless, since REGISTRY already exposes it.
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00008'})
SET
  ii.name                 = 'OwnershipChange',
  ii.description          = 'Did conditions change after this building was sold?',
  ii.applicable_rules     = 'RUL-00014',
  ii.canonical_question_ids = 'CQ-00008|CQ-00009';

MERGE (cq1:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00008'})
SET
  cq1.intent_id             = 'INT-00008',
  cq1.question_template     = 'Did conditions change after {building} in {borough} was sold?',
  cq1.traversal_description = 'Locate DeedTransfer Events for the Building, compare violation trajectory before/after the transfer date per OC-001.',
  cq1.required_node_types   = 'Building|Event',
  cq1.applicable_rule_ids   = 'RUL-00014';

MERGE (cq2:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00009'})
SET
  cq2.intent_id             = 'INT-00008',
  cq2.question_template     = 'Has {building} in {borough} gotten worse since it changed hands?',
  cq2.traversal_description = 'Same traversal as CQ-00008 -- alternate phrasing tested against the same handler.',
  cq2.required_node_types   = 'Building|Event',
  cq2.applicable_rule_ids   = 'RUL-00014';


// -----------------------------------------------------------------------------
// INT-00009 -- BuildingDueDiligence
// Tested question: "What is the full record on 122 West 97th Street in
// Manhattan?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00009'})
SET
  ii.name                 = 'BuildingDueDiligence',
  ii.description          = 'What is the full record on this building?',
  ii.applicable_rules     = '',
  ii.canonical_question_ids = 'CQ-00010';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00010'})
SET
  cq.intent_id             = 'INT-00009',
  cq.question_template     = 'What is the full record on {building} in {borough}?',
  cq.traversal_description = 'Single aggregated query: violation summary by class/status, court filings, ECB judgments, PHC claim, and ownership -- data retrieval only, no Rule applied.',
  cq.required_node_types   = 'Building|Event|Claim|Relationship|Actor',
  cq.applicable_rule_ids   = '';


// -----------------------------------------------------------------------------
// INT-00010 -- RentStabilization
// Tested question: "Is 925 9 Avenue losing rent stabilized units?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00010'})
SET
  ii.name                 = 'RentStabilization',
  ii.description          = 'What are the rent-stabilized unit counts and deregulation trajectory for this building?',
  ii.applicable_rules     = 'RUL-00010',
  ii.canonical_question_ids = 'CQ-00011';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00011'})
SET
  cq.intent_id             = 'INT-00010',
  cq.question_template     = 'Is {building} losing rent stabilized units?',
  cq.traversal_description = 'Fetch year-by-year rs_units_20xx properties on the Building and evaluate RS-001 deregulation threshold.',
  cq.required_node_types   = 'Building',
  cq.applicable_rule_ids   = 'RUL-00010';


// -----------------------------------------------------------------------------
// INT-00011 -- FineEvasion
// Tested question: "What are the ECB violations at 1459 Wythe Place Bronx?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00011'})
SET
  ii.name                 = 'FineEvasion',
  ii.description          = 'Does this landlord have outstanding ECB/OATH fines and payment patterns worth flagging?',
  ii.applicable_rules     = 'RUL-00011',
  ii.canonical_question_ids = 'CQ-00012';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00012'})
SET
  cq.intent_id             = 'INT-00011',
  cq.question_template     = 'What are the ECB violations at {building}?',
  cq.traversal_description = 'Aggregate ECB Judgment Events for the Building (penalty_imposed, amount_paid, balance_due) and evaluate FE-001 outstanding-balance threshold.',
  cq.required_node_types   = 'Building|Event',
  cq.applicable_rule_ids   = 'RUL-00011';


// -----------------------------------------------------------------------------
// INT-00012 -- EnforcementAccountability
// Tested questions:
//   "Is HPD following up on violations at 79 Post Avenue, Manhattan"
//   "Is HPD following up on violations at 1459 Wythe Place Bronx?"
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00012'})
SET
  ii.name                 = 'EnforcementAccountability',
  ii.description          = 'Is HPD actually following up on violations at this building?',
  ii.applicable_rules     = 'RUL-00012',
  ii.canonical_question_ids = 'CQ-00013|CQ-00014';

MERGE (cq1:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00013'})
SET
  cq1.intent_id             = 'INT-00012',
  cq1.question_template     = 'Is HPD following up on violations at {building} in {borough}?',
  cq1.traversal_description = 'Find long-open Class C violations older than 365 days with no associated CourtFiling in the same period, evaluate EA-001.',
  cq1.required_node_types   = 'Building|Event',
  cq1.applicable_rule_ids   = 'RUL-00012';

MERGE (cq2:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00014'})
SET
  cq2.intent_id             = 'INT-00012',
  cq2.question_template     = 'Is enforcement lagging at {building}?',
  cq2.traversal_description = 'Same traversal as CQ-00013 -- alternate phrasing tested against the same handler.',
  cq2.required_node_types   = 'Building|Event',
  cq2.applicable_rule_ids   = 'RUL-00012';


// -----------------------------------------------------------------------------
// INT-00013 -- NetworkExposure
// Tested question: "Are Michael Bennett and Ryan Hiller operating as a
// coordinated network?"
// Note: handler uses only the first named actor (canonical_id); the graph
// discovers ProbableAffiliation-linked affiliates automatically. The
// question_template below keeps both names since that is the phrasing
// actually tested, but only one entity is extracted at intent-parse time.
// -----------------------------------------------------------------------------
MERGE (ii:InvestigativeIntent:WatchlineNode {intent_id: 'INT-00013'})
SET
  ii.name                 = 'NetworkExposure',
  ii.description          = 'Are two or more apparently separate landlords operating as a coordinated network?',
  ii.applicable_rules     = 'RUL-00008',
  ii.canonical_question_ids = 'CQ-00015';

MERGE (cq:CanonicalQuestion:WatchlineNode {cq_id: 'CQ-00015'})
SET
  cq.intent_id             = 'INT-00013',
  cq.question_template     = 'Is {actor} connected to other landlords operating as a coordinated network?',
  cq.traversal_description = 'Follow ProbableAffiliation Relationship edges from the named Actor, fan out to each affiliate''s portfolio, aggregate combined PHC rate per NE-001.',
  cq.required_node_types   = 'Actor|Relationship|Building|Claim',
  cq.applicable_rule_ids   = 'RUL-00008';
