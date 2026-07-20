// =============================================================================
// Watchline NYC -- Rule Seed Script
// File: seed_rules.cypher
//
// Purpose: Load all Rule nodes required by the portfolio detection pipeline
//          into the graph before the first pipeline run.
//
// Prerequisites:
//   1. watchline_schema.cypher must have been run first.
//   2. Run this script once against the Watchline Neo4j database.
//   3. Verify with: MATCH (r:Rule) RETURN r.name, r.version, r.deprecated
//
// Rules loaded:
//   RUL-00001  PHC-001   Persistent Hazardous Conditions (Interpretation layer)
//   RUL-00002  PBC-001   Probable Beneficial Control (Interpretation layer)
//   RUL-00003  RMT-001   HPD Name-Based Connection (Identity layer)
//   RUL-00004  RMT-002   HPD Address-Based Connection (Identity layer)
//   RUL-00005  RMT-003   WCC Portfolio Detection (Identity layer)
//   RUL-00006  RMT-004   Louvain Community Splitting (Identity layer)
//   RUL-00007  DT-001    Deterioration Trajectory (Interpretation layer)
//   RUL-00008  NE-001    Network Exposure (Interpretation layer)
//   RUL-00009  MA-001    Management Differential (Interpretation layer)
//   RUL-00010  RS-001    Rent Stabilization Loss (Interpretation layer)
//   RUL-00011  FE-001    Fine Evasion (Interpretation layer)
//   RUL-00012  EA-001    Enforcement Accountability Gap (Interpretation layer)
//   RUL-00013  RCV-001   Recidivism (Interpretation layer)
//   RUL-00014  OC-001    Ownership Change Deterioration (Interpretation layer)
//   RUL-00015  VA-001    Vacate History (Interpretation layer)
//   RUL-00016  OND-001   Ownership Name Discrepancy (Interpretation layer)
//   RUL-00017  MBC-001   Mortgage-Based Concealment (Interpretation layer)
//
// Amendment protocol (Charter Principle 15):
//   To update a Rule: increment version, set deprecated=true on the old node,
//   create a new Rule node with a new rule_id, and add a SUPERSEDED_BY edge
//   from the old node to the new one. Never delete Rule nodes.
//
// Version: 1.0 -- June 2026
// =============================================================================


// -----------------------------------------------------------------------------
// RUL-00001: PHC-001 -- Persistent Hazardous Conditions
// Interpretation layer. Generates Claims about buildings with persistent
// open Class C violations. Evaluated by the PHC-001 evaluation pipeline.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00001'})
SET
  r.name                       = 'PHC-001',
  r.title                      = 'Persistent Hazardous Conditions',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'HPD violation classification standards (Class C: immediately hazardous). Threshold values reflect Watchline editorial judgment based on review of HPD enforcement practice; they are not derived from a statutory definition.',
  r.interpretive_concept       = 'PersistentHazardousConditions',
  r.input_types                = 'Event[Violation,class=C,status=Open]',
  r.threshold_description      = 'Three or more Class C (immediately hazardous) violations are currently open AND the oldest open Class C violation has been open for more than 180 days AND no active remediation order is in effect for the building.',
  r.threshold_logic            = "COUNT(violations WHERE class='C' AND status='Open') >= 3 AND MAX(days_open WHERE class='C' AND status='Open') > 180",
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'This building satisfies Watchline Rule PHC-001 for Persistent Hazardous Conditions. It has {open_c_count} open Class C violations, the oldest of which has been open for {oldest_days} days. This conclusion is based on HPD violation data. Class C violations are classified by HPD as immediately hazardous. The 180-day threshold and the minimum count of three violations reflect Watchline editorial judgment, not a statutory definition. A different threshold would produce a different result.',
  r.falsification_conditions   = 'Fewer than three Class C violations are open. Or: the oldest open Class C violation has been open for 180 days or fewer. Produces Disputed status if any open violation is under active contest in Housing Court.',
  r.amendment_notes            = 'Initial version.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00002: PBC-001 -- Probable Beneficial Control
// Interpretation layer. Generates Claims from OwnershipNetwork IdentityAssertions.
// Referenced in store.py as RULE_ID_PBC001.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00002'})
SET
  r.name                       = 'PBC-001',
  r.title                      = 'Probable Beneficial Control',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'Watchline editorial judgment based on JustFix Who Owns What methodology. Not derived from a statutory definition of beneficial ownership under FinCEN rules, New York LLC Transparency Act, or any other legal standard. Users should not rely on this inference as a legal determination.',
  r.interpretive_concept       = 'ProbableBeneficialControl',
  r.input_types                = 'IdentityAssertion|Actor[OwnershipNetwork]|IdentityObservation',
  r.threshold_description      = 'An OwnershipNetwork Actor generates a ProbableBeneficialControl Claim when: (1) it has at least one IdentityAssertion of confidence Medium or above; AND (2) it contains at least two distinct BBLs; AND (3) it has at least one address-based connection (RMT-002 edge) OR at least two name-based connections (RMT-001 edges). Each building in the network receives a BeneficialControl Relationship node linking it to the OwnershipNetwork Actor.',
  r.threshold_logic            = "IdentityAssertion.confidence IN ['High', 'Medium'] AND COUNT(DISTINCT bbl) >= 2 AND (COUNT(rmt002_edges) >= 1 OR COUNT(rmt001_edges) >= 2)",
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'These {bbl_count} properties appear to be under the probable beneficial control of a single ownership network, which Watchline identifies as {network_display_name} (ID: {canonical_id}). This conclusion is based on {address_edge_count} shared business address connection(s) and {name_edge_count} shared name connection(s) found in HPD registration data. The ownership network was identified using Watchline Rules RMT-001 through RMT-004 and this conclusion was generated by Rule PBC-001 v1.0. The confidence of this grouping is {confidence}, based on the density and strength of connections within the network.\n\nIMPORTANT: This is an inference based on patterns in HPD registration data, not a legal determination of ownership or control. The term ownership network refers to a cluster of registrations identified by a computational algorithm, not a legally recognized entity. This conclusion should be treated as an investigative starting point requiring further verification, not as established fact.',
  r.falsification_conditions   = 'Fewer than two distinct BBLs remain in the community after removing Low-confidence IdentityAssertions. Or: all connections between two subgraphs are name-based only with no address-based connection. Or: an Actor named in the network provides documentation demonstrating that the shared registration attributes resulted from a management company, registered agent, or other third party acting on behalf of unrelated owners. Or: HPD registration data is corrected and the corrected data no longer supports the connection.',
  r.amendment_notes            = 'Initial version. The minimum threshold of one address-based edge OR two name-based edges reflects the judgment that a single name-based connection is insufficient to assert probable beneficial control. This threshold should be reviewed after the first full run and calibrated against known ground-truth cases.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00003: RMT-001 -- HPD Registration Name-Based Connection
// Identity layer. Governs name-based edge construction in landlords_with_connections.sql.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00003'})
SET
  r.name                       = 'RMT-001',
  r.title                      = 'HPD Registration Name-Based Connection',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'JustFix Who Owns What methodology. Watchline adaptation. Not derived from a statutory definition.',
  r.interpretive_concept       = 'NameBasedOwnershipConnection',
  r.input_types                = 'IdentityObservation',
  r.threshold_description      = 'Two IdentityObservations are connected by a name-based edge when their normalized landlord names match exactly after stripping legal entity suffixes (LLC, INC, CORP, LP, LLP, PLLC), AND their business addresses have a street name and number similarity score above 0.85 AND share the same ZIP code. The edge carries a weight of 1.0 plus the address similarity score plus 0.25 if apartment numbers also match.',
  r.threshold_logic            = 'normalize(name_a) == normalize(name_b) AND address_similarity(addr_a, addr_b) > 0.85 AND zip_a == zip_b; weight = 1.0 + address_similarity_score + (0.25 IF apt_a == apt_b AND apt_a IS NOT NULL)',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'These two landlord registrations are connected because they share the same normalized name ({normalized_name}) and their business addresses are highly similar ({addr_a} and {addr_b}, similarity {similarity_score}). Name-based connections are treated as lower-confidence evidence of ownership relationship because names are more commonly shared by coincidence than addresses. This connection was identified using Watchline Rule RMT-001 v1.0 against HPD registration data retrieved on {retrieval_date}.',
  r.falsification_conditions   = 'Name similarity falls below exact match after normalization. Or: address similarity score falls below 0.85. Or: ZIP codes differ. Or: one or both registrations are subsequently identified as government entities or known property managers acting on behalf of unrelated owners.',
  r.amendment_notes            = 'Initial version. Normalization list (legal entity suffixes) should be reviewed when new entity types appear frequently in HPD data. Address similarity threshold (0.85) should be reviewed after the first full pipeline run.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00004: RMT-002 -- HPD Registration Address-Based Connection
// Identity layer. Governs address-based edge construction in landlords_with_connections.sql.
// High-volume address filter (>= 50 contacts) applied before edge construction.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00004'})
SET
  r.name                       = 'RMT-002',
  r.title                      = 'HPD Registration Address-Based Connection',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'JustFix Who Owns What methodology. Watchline adaptation. Not derived from a statutory definition.',
  r.interpretive_concept       = 'AddressBasedOwnershipConnection',
  r.input_types                = 'IdentityObservation',
  r.threshold_description      = 'Two IdentityObservations are connected by an address-based edge when their Geosupport-normalized business addresses share an exact house number, exact street name, and exact ZIP code. Apartment number matching tolerates missing values on either side. The edge carries a weight of 2.0 plus the name similarity score between the two contacts. Addresses with 50 or more contacts in hpd_business_addresses are excluded from edge construction (high-volume address filter).',
  r.threshold_logic            = 'house_number_a == house_number_b AND street_name_a == street_name_b AND zip_a == zip_b AND (apt_a == apt_b OR apt_a IS NULL OR apt_b IS NULL) AND numberofcontacts < 50; weight = 2.0 + name_similarity(name_a, name_b)',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'These two landlord registrations are connected because they list the same business address ({normalized_address}) in HPD registration data. Address co-location is treated as higher-confidence evidence of an ownership relationship than name similarity alone. The combined edge weight is {edge_weight}, incorporating a name similarity score of {name_similarity_score}. This connection was identified using Watchline Rule RMT-002 v1.0 against HPD registration data retrieved on {retrieval_date}.',
  r.falsification_conditions   = 'Normalized addresses differ on house number, street name, or ZIP code. Or: the address is identified as a high-volume professional address (>= 50 HPD contacts) and excluded by the filter. Or: the address is subsequently identified as a registered agent office, law firm, or management company serving unrelated clients.',
  r.amendment_notes            = 'Initial version. High-volume address filter threshold is 50 contacts (hpd_business_addresses.numberofcontacts >= 50). This threshold should be reviewed after the first full run. A named blocklist of known professional addresses is a planned future improvement.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00005: RMT-003 -- WCC Portfolio Detection
// Identity layer. Governs Stage 5 (WCC) of the pipeline.
// Referenced in store.py as RULE_ID_RMT003.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00005'})
SET
  r.name                       = 'RMT-003',
  r.title                      = 'Weakly Connected Components Portfolio Detection',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'JustFix Who Owns What methodology. Neo4j GDS implementation. Watchline adaptation.',
  r.interpretive_concept       = 'CandidateOwnershipNetwork',
  r.input_types                = 'IdentityObservation|NameBasedOwnershipConnection|AddressBasedOwnershipConnection',
  r.threshold_description      = 'A set of IdentityObservations forms a candidate OwnershipNetwork when they are all reachable from each other through any chain of name-based or address-based connections (RMT-001 or RMT-002 edges), regardless of edge direction or weight. Minimum component size: 2 IdentityObservations. Components with aggregate BBL count above 300 are passed to RMT-004 for splitting.',
  r.threshold_logic            = "CALL gds.wcc.stream('landlord-graph') YIELD nodeId, componentId; GROUP BY componentId WHERE COUNT(nodeId) >= 2",
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'These {bbl_count} properties are grouped as a candidate ownership network because their HPD registration contacts are connected through a chain of {connection_count} shared name or address connections. This grouping was produced by the Weakly Connected Components algorithm (Watchline Rule RMT-003 v1.0) applied to HPD registration data retrieved on {retrieval_date}. The algorithm finds all properties reachable through any chain of connections; it does not weight connections. {split_note}',
  r.falsification_conditions   = 'Removing any single edge disconnects the component into two or more separate components (indicates a bridge connection that may be spurious). Component BBL count exceeds 300, triggering Louvain splitting (RMT-004). All connections within the component are name-based only with no address-based connections.',
  r.amendment_notes            = 'Initial version. The 300 BBL threshold for Louvain splitting is configurable (MAX_SIZE in algorithms.py) and should be reviewed after the first full run. Geosupport version used for address standardization: 25b. Record this alongside any version change.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00006: RMT-004 -- Louvain Community Splitting
// Identity layer. Governs Stage 6 (recursive Louvain) of the pipeline.
// Referenced in store.py as RULE_ID_RMT004.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00006'})
SET
  r.name                       = 'RMT-004',
  r.title                      = 'Louvain Community Detection for Oversized Portfolio Splitting',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'JustFix Who Owns What methodology. Neo4j GDS implementation. Watchline adaptation.',
  r.interpretive_concept       = 'RefinedOwnershipNetwork',
  r.input_types                = 'CandidateOwnershipNetwork|NameBasedOwnershipConnection|AddressBasedOwnershipConnection',
  r.threshold_description      = 'A CandidateOwnershipNetwork with aggregate BBL count above 300 is split using the Louvain community detection algorithm with edge weights. Splitting is recursive until all communities are below 300 BBLs or Louvain fails to produce a meaningful split. Communities retained after a failed split receive confidence=Low. Sub-communities from the same WCC component are linked by ProbableAffiliation relationships.',
  r.threshold_logic            = "CALL gds.louvain.mutate(subgraph, {mutateProperty: 'louvainId_N', relationshipWeightProperty: 'weight', seed: 42}) YIELD modularity; WHILE MAX(community_bbl_count) > 300 AND modularity_gain > 0.01: recurse; IF modularity_gain <= 0.01: yield as-is with confidence=Low",
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-06-01'),
  r.expiry_date                = null,
  r.explanation_template       = 'This ownership network of {bbl_count} properties was identified by splitting a larger candidate network of {original_bbl_count} properties. The split was performed using the Louvain community detection algorithm (Watchline Rule RMT-004 v1.0), which uses the strength of name and address connections as edge weights to find natural internal divisions. {split_iterations} splitting iteration(s) were required. {related_network_note} This grouping was produced against HPD registration data retrieved on {retrieval_date}.',
  r.falsification_conditions   = 'Louvain fails to produce a meaningful split, indicating the oversized community may represent a genuinely large ownership network rather than a false merge. In this case the community is retained with confidence=Low and flagged for manual review. Or: all intra-community connections are name-based only, suggesting the community boundary may be arbitrary.',
  r.amendment_notes            = 'Initial version. Louvain seed fixed at 42 for reproducibility. Resolution parameter uses GDS default. Confidence thresholds: High (>10 edges, avg weight >2.5, no bridge); Medium (3-10 edges, or avg weight 1.5-2.5, or one bridge); Low (<3 edges, avg weight <1.5, or no meaningful split). Changes to thresholds require version increment.',
  r.deprecated                 = false;




// -----------------------------------------------------------------------------
// RUL-00007: DT-001 -- Deterioration Trajectory
// Interpretation layer. Evaluates building-level Class C violation trend.
// Evaluated by the DeteriorationTrajectory intent handler in the investigator.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00007'})
SET
  r.name                       = 'DT-001',
  r.title                      = 'Deterioration Trajectory',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'Watchline editorial judgment. Not derived from any statutory or regulatory definition of building deterioration. The 180-day eligibility window aligns with HPD\'s internal classification of long-standing violations but is applied here as an investigative threshold, not a legal standard.',
  r.interpretive_concept       = 'DeteriorationTrajectory',
  r.input_types                = 'Building|Event[HPD Violation, Class C]',
  r.threshold_description      = 'A building satisfies Rule DT-001 (Deterioration Trajectory) if two signals are both present over the most recent 5 full calendar years: (A) average annual Class C violation issuance is higher in the most recent 2 years than in the earliest 2 years of the window; and (B) the resolution rate of Class C violations that have been open more than 180 days is lower in the most recent 2 years than in the earliest 2 years. Both signals must be satisfied.',
  r.threshold_logic            = 'Signal A: avg(issued[year-1], issued[year-2]) > avg(issued[year-4], issued[year-5]). Signal B: avg(rate[year-1], rate[year-2]) < avg(rate[year-4], rate[year-5]). Where rate[y] = resolved_over_180[y] / eligible_over_180[y] for violations issued in year y. Minimum 3 years of data required; otherwise result is insufficient_data.',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-04'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule DT-001 (Deterioration Trajectory). {signal_a_description} {signal_b_description} This finding is based on HPD Class C violation records from {window_years}. The interpretive status is Inferred.',
  r.falsification_conditions   = 'Signal A not satisfied: average annual Class C issuance in the most recent 2 years is not higher than in the earliest 2 years. Or: Signal B not satisfied: average resolution rate in the most recent 2 years is not lower than in the earliest 2 years. Or: fewer than 3 full calendar years of Class C violation data are available for this building. Or: HPD data for this building is corrected and the corrected data no longer supports the trajectory.',
  r.amendment_notes            = 'Initial version. The 5-year window and 2-year early/recent comparison periods reflect judgment that 3 years is the minimum to distinguish a trend from noise, while 5 years avoids conflating current management with prior ownership. The 180-day eligibility threshold for resolution rate aligns with PHC-001 (RUL-00001) for consistency. Both signals are required rather than either alone: Signal C alone is already captured by PHC-001; Signal A alone is too easily satisfied in large buildings. These thresholds should be reviewed after the first year of operation and calibrated against known deteriorating and non-deteriorating buildings.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00008: NE-001 -- Network Exposure
// Interpretation layer. Evaluates cross-network affiliation via ProbableAffiliation.
// KNOWN LIMITATION: management-mediated bridges can produce false positives.
// See amendment_notes for required ingestion-time refinement (not yet implemented).
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00008'})
SET
  r.name                       = 'NE-001',
  r.title                      = 'Network Exposure',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'Watchline editorial judgment based on graph-theoretic analysis of HPD registration data. ProbableAffiliation is derived from shared Weakly Connected Component membership (RUL-00005) and Louvain community detection (RUL-00006). This is a weaker inference than ProbableBeneficialControl — it indicates structural proximity in the registration graph, not proven common ownership or control. Not derived from any statutory definition of affiliated ownership.',
  r.interpretive_concept       = 'NetworkExposure',
  r.input_types                = 'Actor[OwnershipNetwork]|Relationship[ProbableAffiliation]|Building|Claim[PersistentHazardousConditions]',
  r.threshold_description      = 'Two or more actors satisfy Watchline Rule NE-001 (Network Exposure) if they are connected by ProbableAffiliation relationships derived from shared Weakly Connected Component membership in HPD registration data (RUL-00005 and RUL-00006). This is a weaker signal than Probable Beneficial Control: it indicates that the two ownership networks were originally part of the same registration graph before community detection split them. Confidence is Medium. A different community detection threshold would produce a different network boundary.',
  r.threshold_logic            = 'EXISTS ProbableAffiliation(actor_a, actor_b) WHERE basis CONTAINS WCC component membership. Minimum 2 distinct actors required. Combined PHC rate = sum(phc_buildings) / sum(portfolio_size) across all affiliated actors.',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-05'),
  r.expiry_date                = null,
  r.explanation_template       = '{actor_name} is connected to {affiliate_count} affiliated ownership network(s) via ProbableAffiliation relationships. The combined portfolio spans {combined_portfolio} buildings and {combined_units} residential units, of which {combined_phc} ({combined_phc_rate}%) satisfy Rule PHC-001 for Persistent Hazardous Conditions. The affiliation basis is: {affiliation_basis}.',
  r.falsification_conditions   = 'No ProbableAffiliation relationships exist between the named actor and any other Actor node. Or: all ProbableAffiliation relationships are removed after recalculation of WCC components with updated HPD registration data. Or: an actor provides documentation demonstrating that the shared WCC membership resulted from a common registered agent or management company acting on behalf of unrelated owners. Or: the community detection algorithm is recalibrated and the two networks fall into separate components.',
  r.amendment_notes            = 'Initial version. NE-001 is intentionally weaker than PBC-001: it flags that two inferred ownership networks share a structural origin in the HPD registration graph, not that they are under common beneficial control. The Medium confidence level reflects this epistemic distinction. The threshold of 2 actors is the minimum meaningful network; single-actor results are flagged as insufficient_data.\n\nKNOWN LIMITATION — management-mediated bridges: ProbableAffiliation edges can be false positives when the WCC link between two networks is mediated primarily through a high-degree address belonging to a property management company rather than a common owner. Investigation of the Michael Bennett / Ryan Hiller affiliation (July 2026) confirmed this pattern: the connection was an artifact of shared management infrastructure, not common ownership.\n\nREQUIRED INGESTION-TIME REFINEMENT (not yet implemented): When the WCC/Louvain pipeline creates ProbableAffiliation relationships, each relationship should be evaluated for management mediation before being written to the graph. For each bridging IdentityObservation between the two WCC components, check the degree of the shared address node. If the sole or dominant bridge passes through an address with degree above a calibration threshold (suggested starting point: 50 distinct buildings), set management_mediated: true on the ProbableAffiliation relationship. The NE-001 evaluate() function should then suppress or downgrade (confidence: Low) any affiliation where management_mediated is true.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00009: MA-001 -- Management Differential
// Interpretation layer. Evaluates differential maintenance across a managing
// agent's portfolio. Requires agents ingestion pipeline (make agents) to run
// first, populating ManagedBy Relationship nodes and ManagingAgent Actor nodes.
// NOT YET IMPLEMENTED: stub rule registered to satisfy Charter §11 requirement
// that Rules are first-class graph objects before any code is written.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00009'})
SET
  r.name                       = 'MA-001',
  r.title                      = 'Management Differential',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'Watchline editorial judgment. Not derived from any statutory or regulatory standard for property management quality. The quartile comparison and 2x differential threshold reflect editorial judgment about what constitutes a meaningful disparity in maintenance standards across a portfolio. Not a legal determination.',
  r.interpretive_concept       = 'ManagementDifferential',
  r.input_types                = 'Actor[ManagingAgent]|Relationship[ManagedBy]|Building|Claim[PersistentHazardousConditions]',
  r.threshold_description      = 'A managing agent satisfies Rule MA-001 (Management Differential) if the PHC rate among buildings in the bottom quartile of their portfolio by enforcement record is more than twice the PHC rate among buildings in the top quartile, across a portfolio of at least 10 buildings. This indicates a pattern of differential maintenance that is unlikely to be explained by building age or size alone.',
  r.threshold_logic            = 'portfolio_size >= 10 AND (phc_rate_bottom_quartile / phc_rate_top_quartile) > 2.0. Quartiles defined by open Class C violation count per residential unit. Bottom quartile = highest violation density. Top quartile = lowest violation density. phc_rate = count(PHC buildings) / count(buildings) within each quartile.',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-07'),
  r.expiry_date                = null,
  r.explanation_template       = 'The managing agent {agent_name} ({agent_address}) satisfies Watchline Rule MA-001 (Management Differential) across a portfolio of {portfolio_size} buildings. The PHC rate in the worst-maintained quartile is {phc_rate_bottom}% compared to {phc_rate_top}% in the best-maintained quartile — a differential ratio of {differential_ratio}x. This pattern suggests differential maintenance standards across the portfolio. Interpretive status: Inferred.',
  r.falsification_conditions   = 'Portfolio size is fewer than 10 buildings. Or: the PHC rate differential ratio between bottom and top quartiles is 2.0 or below. Or: the differential is explained by systematic building-type or age differences between quartiles (e.g. all bottom-quartile buildings are pre-war rental walk-ups while all top-quartile buildings are post-war co-ops). Or: the managing agent contact in HPD registration data is found to be a shared registered agent acting for unrelated owners rather than a genuine property management relationship.',
  r.amendment_notes            = 'Initial version. Stub registration only — MA-001 evaluation pipeline not yet implemented. Requires agents ingestion pipeline to populate ManagedBy relationships and ManagingAgent Actor nodes before evaluation is possible. The 2x differential threshold and 10-building minimum portfolio size are initial estimates that should be calibrated against known cases of differential management before deployment. The quartile definition (by open Class C violations per residential unit) normalises for building size but not for building age or type — a future version should consider age/type adjustment.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00010: RS-001 -- Rent Stabilization Loss
// Interpretation layer. Evaluates DHCR rent-stabilized unit loss over time.
// Evaluated by the RentStabilization intent handler in the investigator.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00010'})
SET
  r.name                       = 'RS-001',
  r.title                      = 'Rent Stabilization Loss',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'DHCR (NYS Division of Housing and Community Renewal) rent registration records as analyzed by the Furman Center for Real Estate and Urban Policy. The rs_deregulating flag and annual unit counts are derived from the Furman Center NYC rent stabilization dataset. The threshold reflects Watchline editorial judgment, not a statutory definition of deregulation.',
  r.interpretive_concept       = 'RentStabilizationLoss',
  r.input_types                = 'Building|Property[DHCR rent registration]',
  r.threshold_description      = 'A building satisfies Watchline Rule RS-001 (Rent Stabilization Loss) if two conditions are both present: (1) the change in rent-stabilized unit count from the earliest available year to the most recent is negative (rs_units_change < 0); and (2) the DHCR rs_deregulating flag is true, indicating active removal of units from the stabilization registry. Both conditions must be satisfied. A building with a negative unit change but no active deregistration signal is noted but does not satisfy the rule.',
  r.threshold_logic            = 'rs_units_change < 0 AND rs_deregulating = true',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-07'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule RS-001 (Rent Stabilization Loss). {signal_a_description} {signal_b_description} This finding is based on DHCR rent registration records from {earliest_year} to {latest_year}. The interpretive status is Inferred.',
  r.falsification_conditions   = 'rs_units_change is zero or positive: the building has not lost rent-stabilized units over the available history. Or: rs_deregulating flag is false: no active DHCR deregistration signal. Or: unit count decline is explained by a building-wide rehabilitation exemption, temporary vacancy deregistration subsequently re-registered, or a DHCR data correction. Or: DHCR updates the historical record and the corrected data no longer supports the finding.',
  r.amendment_notes            = 'Initial version. The rs_deregulating flag is derived from Furman Center analysis of DHCR records; Watchline does not independently compute this flag. A building can show rs_units_change < 0 due to legitimate vacancies or data corrections — requiring the deregistration flag is intended to filter for systematic removal rather than transient fluctuations. The threshold should be reviewed as newer DHCR snapshots (2024 onward) become available.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00011: FE-001 -- Fine Evasion
// Interpretation layer. Evaluates unpaid ECB/OATH judgment balances.
// Evaluated by the FineEvasion intent handler in the investigator.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00011'})
SET
  r.name                       = 'FE-001',
  r.title                      = 'Fine Evasion',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'NYC Office of Administrative Trials and Hearings (OATH) / Environmental Control Board (ECB) judgment records. The $10,000 single-building balance threshold reflects Watchline editorial judgment and is not derived from any statutory definition of fine evasion or willful non-payment.',
  r.interpretive_concept       = 'FineEvasion',
  r.input_types                = 'Building|Event[Judgment,ECB]',
  r.threshold_description      = 'A building satisfies Watchline Rule FE-001 (Fine Evasion) if it has one or more outstanding ECB/OATH judgments with a combined unpaid balance exceeding $10,000. ECB judgments are civil penalty decisions issued by the Office of Administrative Trials and Hearings (OATH) for violations of the NYC Administrative Code. A balance_due greater than zero indicates a judgment that has not been fully paid. This threshold reflects Watchline editorial judgment, not a statutory definition.',
  r.threshold_logic            = 'SUM(balance_due WHERE balance_due > 0) > 10000',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-07'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule FE-001 (Fine Evasion). It has {judgments_with_balance} ECB/OATH judgment(s) with an outstanding balance, totaling ${total_balance_due} unpaid of ${total_penalties_imposed} in penalties imposed. The interpretive status is Inferred.',
  r.falsification_conditions   = 'Combined outstanding ECB balance is $10,000 or less. Or: all judgment balances are zero or null, indicating full payment or administrative cancellation. Or: outstanding balance is under active contest in OATH proceedings and has not yet been finalized. Or: ECB records are corrected and the corrected data shows a lower balance.',
  r.amendment_notes            = 'Initial version. The $10,000 threshold is a single-building signal. A future actor-level version of this rule (FE-001 v2.0) should flag actors with outstanding balance > $0 across two or more buildings in their portfolio, which is a stronger evasion signal than a single-building threshold.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00012: EA-001 -- Enforcement Accountability Gap
// Interpretation layer. Evaluates whether HPD has taken court action on
// buildings with long-open Class C violations.
// Evaluated by the EnforcementAccountability intent handler.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00012'})
SET
  r.name                       = 'EA-001',
  r.title                      = 'Enforcement Accountability Gap',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'HPD violation data and HPD housing court litigation data. A building with multiple open Class C (immediately hazardous) violations open for more than one year, combined with no court action in the same period, indicates a failure of administrative enforcement follow-through. This is Watchline editorial judgment, not a statutory enforcement standard.',
  r.interpretive_concept       = 'EnforcementAccountabilityGap',
  r.input_types                = 'Building|Event[HPD Violation, Class C, Open]|Event[CourtFiling]',
  r.threshold_description      = 'A building satisfies Watchline Rule EA-001 (Enforcement Accountability Gap) if it has 3 or more open Class C (immediately hazardous) violations that have been open for more than 365 days, combined with zero HPD court filings recorded since the earliest such violation was opened. Class C violations are the highest severity category in the HPD system and represent immediately hazardous conditions. A one-year threshold filters for prolonged neglect rather than normal administrative processing delays.',
  r.threshold_logic            = 'long_open_c >= 3 AND court_actions_in_period == 0',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-07'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule EA-001 (Enforcement Accountability Gap). It has {long_open_c} open Class C violations that have been open for more than 365 days, with {court_actions_in_period} HPD court filing(s) since the earliest such violation was opened on {earliest_stale_date}. The interpretive status is Inferred.',
  r.falsification_conditions   = 'Fewer than 3 open Class C violations older than 365 days: building does not meet the violation count threshold. Or: one or more HPD court filings are recorded since the earliest stale violation was opened: enforcement action is documented. Or: HPD has taken alternative enforcement action (Alternative Enforcement Program designation, Emergency Repair Program dispatch) that is not captured in the court filing source data. Or: OCA housing court data (not yet ingested) reveals court filings not present in the HPD litigations source. Or: stale violations are contested and under active administrative review.',
  r.amendment_notes            = 'Initial version. The 365-day threshold and 3-violation minimum are initial calibration choices. The court filing signal is limited to HPD litigations data — OCA housing court data (not yet ingested) may reveal additional court actions. The Alternative Enforcement Program (AEP) and Emergency Repair Program (ERP) represent enforcement actions short of court filing that would reduce the accountability gap signal; these are not currently captured. EA-001 confidence increases when combined with FE-001 (outstanding ECB balance) as a co-signal.',
  r.deprecated                 = false;


// -----------------------------------------------------------------------------
// RUL-00013: RCV-001 -- Recidivism
// Interpretation layer. Evaluates whether an actor has allowed hazardous
// conditions to persist repeatedly across their portfolio over multiple years
// or multiple boroughs.
// Evaluated by the Recidivism intent handler.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00013'})
SET
  r.name                       = 'RCV-001',
  r.title                      = 'Recidivism',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'HPD violation data and Watchline PHC-001 (Persistent Hazardous Conditions) claims. Recidivism in this context is Watchline editorial judgment: an actor who has allowed immediately hazardous conditions to persist across multiple boroughs or over multiple years demonstrates a pattern of neglect that is structural, not situational. This is not a statutory or regulatory determination.',
  r.interpretive_concept       = 'Recidivism',
  r.input_types                = 'Actor|Relationship[BeneficialControl]|Building|Claim[PersistentHazardousConditions]|Event[HPD Violation, Class C, Open]',
  r.threshold_description      = 'An actor satisfies Watchline Rule RCV-001 (Recidivism) if either of two signals is present: (1) Multi-borough persistence: the actor has PHC-001-flagged buildings in more than one NYC borough, indicating that hazardous conditions are not isolated to a single property or neighborhood; OR (2) Multi-year persistence: the actor has one or more buildings with at least one open Class C (immediately hazardous) violation that was first opened 3 or more years ago and remains unresolved, indicating that conditions have been allowed to persist over multiple years despite the immediately hazardous designation. Either signal alone satisfies the rule.',
  r.threshold_logic            = 'phc_borough_count > 1 OR multi_year_buildings > 0 (where multi_year_buildings counts buildings with min(open_date.year) of currently-open Class C violations <= current_year - 3)',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-08'),
  r.expiry_date                = null,
  r.explanation_template       = 'The actor {name} {verdict} Watchline Rule RCV-001 (Recidivism). {signal_a_description} {signal_b_description} The interpretive status is Inferred.',
  r.falsification_conditions   = 'phc_borough_count is 1 or 0: all PHC buildings are in the same borough, consistent with a geographic concentration of problems rather than systemic portfolio neglect. AND no buildings have open Class C violations older than 3 years: conditions have not been allowed to persist for multiple years. Or: the actor is no longer the beneficial controller of the buildings in question. Or: PHC-001 claims are overturned on re-evaluation of the underlying violation data.',
  r.amendment_notes            = 'Initial version. The 3-year multi-year threshold and the >1 borough multi-borough threshold are initial calibration choices. The multi-year signal uses the year of the oldest currently-open Class C violation as a proxy for years with persistent conditions — it does not track whether Class C violations were continuously open in each intervening year, only that at least one has been open since the threshold year. A more precise implementation would compute open violation counts for each calendar year and identify consecutive years with PHC-triggering conditions. The multi-borough signal is a weak indicator on its own for large portfolios; the threshold could be raised (e.g., >2 boroughs) for actors with portfolios above 50 buildings.',
  r.deprecated                 = false;


// RUL-00014: OC-001 -- Ownership Change Deterioration
// Interpretation layer. Evaluates whether building conditions worsened after
// an arm's-length deed transfer, using ACRIS deed records as the change date
// and HPD Class C violation rates as the condition signal.
// Evaluated by the OwnershipChange intent handler.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00014'})
SET
  r.name                       = 'OC-001',
  r.title                      = 'Ownership Change Deterioration',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'ACRIS deed transfer records (NYC Department of Finance) establish the ownership change date. HPD violation data establishes the Class C violation rate before and after the transfer. The deterioration signal is Watchline editorial judgment: a 50% or greater increase in the annualized Class C violation rate after an arm\'s-length sale indicates that the new owner has allowed conditions to worsen. This is not a statutory or regulatory determination.',
  r.interpretive_concept       = 'OwnershipChange',
  r.input_types                = 'Building|Event[DeedTransfer, ACRIS]|Event[HPD Violation, Class C]',
  r.threshold_description      = 'A building satisfies Watchline Rule OC-001 (Ownership Change Deterioration) if: (1) at least one arm\'s-length deed transfer is recorded in ACRIS since 2010, defined as doc_type DEED with doc_amount greater than zero and pct_transferred of 50 or more; AND (2) the annualized rate of Class C (immediately hazardous) HPD violations in the period after the most recent qualifying transfer is at least 50% higher than the annualized rate in the period before the transfer; AND (3) at least 180 days have elapsed since the transfer (insufficient post-transfer data otherwise). A building with no Class C violations before the transfer and at least one after also satisfies the rule. Minimum pre-transfer data requirement: 365 days of violation history. The 50% rate-increase threshold and the 180-day minimum post-transfer window are initial calibration choices.',
  r.threshold_logic            = 'has_qualifying_deed AND days_after >= 180 AND (rate_after >= rate_before * 1.5 OR (rate_before == 0 AND c_after > 0))',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-08'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address} {verdict} Watchline Rule OC-001 (Ownership Change Deterioration). The most recent qualifying deed transfer occurred on {deed_date} from {grantor} to {grantee}. In the {days_before}-day period before the transfer, {c_before} Class C violations were issued ({rate_before} per year). In the {days_after}-day period after the transfer, {c_after} Class C violations were issued ({rate_after} per year). The interpretive status is Inferred.',
  r.falsification_conditions   = 'No qualifying deed transfer found in ACRIS since 2010 (data constraint: earlier deeds not ingested). Or: the annualized Class C rate after the transfer does not exceed the before rate by 50% or more. Or: fewer than 180 days have elapsed since the transfer (insufficient data). Or: the deed transfer was a legal instrument change (trust, LLC restructuring) rather than a change of beneficial control — in which case grantee_canonical_id reconciliation to an existing Actor node would indicate continuity of control.',
  r.amendment_notes            = 'Initial version. Uses ACRIS deed date as the change event. Arm\'s-length filter (doc_amount > 0, pct_transferred >= 50) excludes trust transfers, intra-family transfers, and partial interest sales. ACRIS coverage starts 2010; deed transfers before 2010 are not in the graph, which means some buildings will show a shorter before-period than their actual history. The 50% rate-increase threshold was chosen to reduce false positives from buildings with naturally high violation rates before sale. A future version should account for building size (violations per residential unit rather than raw count).',
  r.deprecated                 = false;


// RUL-00015: VA-001 -- Vacate History
// Interpretation layer. Evaluates whether HPD has ever issued a vacate order
// against the building -- a stronger displacement/safety signal than a Class
// C violation, since it represents actual forced displacement rather than a
// citation that may or may not be remediated. Evaluated by the VacateHistory
// intent handler.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00015'})
SET
  r.name                       = 'VA-001',
  r.title                      = 'Vacate History',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'HPD vacate orders (NYC Multiple Dwelling Law / Housing Maintenance Code, Admin Code Title 27) are HPD\'s own determination that a building or unit is dangerous enough that residents must leave -- the most severe displacement action short of demolition. The count threshold (one or more orders is sufficient to flag; two or more is flagged as recurring) is Watchline editorial judgment, not a statutory definition of chronic displacement risk.',
  r.interpretive_concept       = 'VacateHistory',
  r.input_types                = 'Building|Event[HPD VacateOrder]',
  r.threshold_description      = 'A building satisfies Watchline Rule VA-001 (Vacate History) if HPD has issued one or more vacate orders against the building on record. Because a vacate order already represents HPD\'s own severe safety determination -- residents were displaced, not merely cited -- no minimum count above one is required to establish evidentiary significance, unlike routine violation-count thresholds elsewhere in this ruleset. A vacate order with no recorded rescind date is currently Active, indicating ongoing displacement at query time. Two or more vacate orders recorded for the same building, active or historical, are additionally flagged as a recurring displacement pattern.',
  r.threshold_logic            = 'vacate_order_count = count(Event{event_type:"VacateOrder", source_name:"HPD"} linked via HAS_EVENT to Building). satisfied = vacate_order_count >= 1. currently_active = exists an order with status = "Active" (rescind_date IS NULL). recurring = vacate_order_count >= 2.',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-17'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule VA-001 (Vacate History). HPD has issued {vacate_order_count} vacate order(s) against this building. {active_description} {recurring_description} This finding is based on HPD vacate order records. The interpretive status is Inferred.',
  r.falsification_conditions   = 'No HPD vacate order record exists for the building at query time. Or: a previously counted vacate order is found to be a data entry error, duplicate, or was issued against a different BBL upon HPD correction. Or: HPD rescinds an order previously counted as currently Active (the currently_active sub-signal, though not the base vacate_order_count >= 1 verdict, would then no longer hold).',
  r.amendment_notes            = 'Initial version. No minimum multiplicity is required (unlike PHC-001\'s >=3 or RCV-001\'s multi-year pattern) because HPD vacate orders are rare (8,752 citywide across the full dataset, vs. millions of violations) and each one is already a severe, HPD-initiated displacement action, not a routine citation. This rule does not apply a recency window: a vacate order from any date in the available HPD history satisfies it, so long-rescinded historical orders and currently active ones are both flagged, distinguished only by the active/recurring sub-signals. A future version could add a recency-weighted or currently-active-only variant if long-past, fully-resolved vacate orders prove to be low-signal in practice.',
  r.deprecated                 = false;


// RUL-00016: OND-001 -- Ownership Name Discrepancy
// Interpretation layer. Compares DOF's recorded owner-of-record name
// (dof_ownername) against the display_name of the Actor Watchline has
// resolved as the building's probable beneficial controller (RUL-00002).
// Evaluated by the OwnershipNameDiscrepancy intent handler.
//
// IMPORTANT CALIBRATION NOTE (see amendment_notes): this rule's positive
// flag rate is HIGH relative to every other rule in this file (~71% of its
// applicable population, verified 2026-07-17) because display_name is
// chosen as the single most frequent registered contact name across an
// Actor's ENTIRE portfolio (see watchline/evidentiary/ingest/portfolio/
// store.py line ~920, `max(... key=frequency)`), not the specific name
// this individual building was registered under. A positive OND-001 flag
// is therefore Low confidence and should be read as a lead worth checking
// by hand, not evidence of concealment -- see threshold_description.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00016'})
SET
  r.name                       = 'OND-001',
  r.title                      = 'Ownership Name Discrepancy',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'DOF PLUTO owner-of-record data (NYC Department of Finance) establishes the name and type of the legal owner recorded on the tax roll. Watchline\'s ProbableBeneficialControl resolution (RUL-00002 / PBC-001) establishes who Watchline\'s WCC/Louvain portfolio-detection algorithm believes controls the building. The comparison threshold (corporate-name exclusion, zero-token-overlap trigger) is Watchline editorial judgment, not a statutory or regulatory determination of ownership discrepancy or concealment.',
  r.interpretive_concept       = 'OwnershipNameDiscrepancy',
  r.input_types                = 'Building|Relationship[BeneficialControl]|Actor|Claim[ProbableBeneficialControl]',
  r.threshold_description      = 'A building satisfies Watchline Rule OND-001 (Ownership Name Discrepancy) if: (1) DOF\'s recorded owner-of-record name (dof_ownername) does not look corporate -- does not contain a corporate-entity suffix such as LLC, INC, CORP, LP, LTD, TRUST, ASSOCIATES, REALTY, PROPERTIES, MANAGEMENT, or HOLDINGS; AND (2) DOF\'s owner name shares no name token in common with the display_name of the Actor Watchline has resolved as the building\'s probable beneficial controller. Corporate-looking DOF names are excluded from evaluation entirely (insufficient_data) because a corporate title-holder differing from a named natural-person beneficial owner is the expected, non-suspicious shape of NYC LLC-held rental property, not a discrepancy this rule is designed to detect. A building with no resolved beneficial controller, or no DOF owner name, is also insufficient_data.',
  r.threshold_logic            = 'is_corporate = dof_ownername matches /(?i)(LLC|INC|CORP|CO\\.|COMPANY|LP|LTD|TRUST|ASSOC|REALTY|PROPERTIES|MGMT|MANAGEMENT|HOLDINGS)/. token_overlap = normalize_tokens(dof_ownername) INTERSECT normalize_tokens(controller.display_name) is non-empty. satisfied = NOT is_corporate AND NOT token_overlap AND dof_ownername IS NOT NULL AND controller IS NOT NULL. confidence = Low (see amendment_notes).',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-17'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule OND-001 (Ownership Name Discrepancy). DOF records the owner of record as {dof_ownername}. Watchline has resolved {controller_name} as the building\'s probable beneficial controller (Rule PBC-001). {overlap_description} This finding is Low confidence -- see the Rules tab caveat about portfolio-wide name aggregation. The interpretive status is Inferred.',
  r.falsification_conditions   = 'DOF\'s owner name looks corporate (contains an LLC/INC/CORP/etc. suffix) -- rule does not apply, insufficient_data. Or: DOF\'s owner name shares at least one name token with the resolved beneficial controller\'s display_name -- treated as a plausible match, not a discrepancy. Or: no BeneficialControl relationship / ProbableBeneficialControl claim exists for the building -- insufficient_data, nothing to compare against. Or: the resolved beneficial controller\'s display_name changes on a portfolio pipeline re-run (versioned update), which can flip a prior discrepancy verdict without any change to the underlying DOF record.',
  r.amendment_notes            = 'Initial version. Calibrated against live evidentiary data 2026-07-17: of ~30,085 buildings with both a DOF owner name and a resolved BeneficialControl relationship, 22,392 (74%) have a corporate-looking DOF name and are excluded from evaluation entirely (out of this rule\'s scope). Of the remaining ~7,693 buildings with a natural-person-looking DOF name, 16.6% show an exact name-token match with the resolved controller\'s display_name, 12.5% show partial token overlap, and 70.9% show zero overlap -- this last group is the population OND-001 flags. The 70.9% rate is high enough that a positive flag must be read as Low confidence: display_name is the single most frequent registered contact name across the controller\'s ENTIRE portfolio network (see watchline/evidentiary/ingest/portfolio/store.py), not necessarily the specific name this individual building was registered under with HPD -- the raw per-building registered name is not currently preserved in the evidentiary graph (intermediate Landlord nodes are deleted after each portfolio run) so it cannot be checked directly. A future version should extend the portfolio pipeline to persist a constituent_names list per Actor (all distinct raw registered names contributing to the network, not just the plurality winner) and compare against that full set instead of the single display_name, which would substantially reduce the false-positive rate from network aggregation. Until then, OND-001 findings are leads pointing to a name worth checking by hand, not evidence of concealment on their own.',
  r.deprecated                 = false;


// RUL-00017: MBC-001 -- Mortgage-Based Concealment
// Interpretation layer. Compares the grantee name(s) on a building's most
// recent ACRIS DeedTransfer against the mortgagor name(s) on its nearest
// purchase-money Mortgage (recorded within -14 to +60 days of the deed).
// A mismatch means the party who took out financing on the purchase is not
// the party who took title -- a classic nominee/straw-buyer signal, since
// under normal purchase-money financing the buyer of record and the
// borrower of record are the same party. Evaluated by the
// MortgageBasedConcealment intent handler.
//
// CALIBRATION NOTE (see amendment_notes): unlike RUL-00016 (OND-001), this
// rule's positive-flag rate is LOW and well-discriminated (verified
// 2026-07-17: 2.9% of matched purchase-money pairs show zero name overlap,
// versus OND-001's 71%) because both compared names come from the SAME
// ACRIS self-reporting convention on the SAME closing package, not two
// independently-sourced/aggregated datasets. Confidence: Medium.
// -----------------------------------------------------------------------------
MERGE (r:Rule:WatchlineNode:VersionedObject:AuditableRecord {rule_id: 'RUL-00017'})
SET
  r.name                       = 'MBC-001',
  r.title                      = 'Mortgage-Based Concealment',
  r.version                    = '1.0',
  r.author                     = 'Watchline NYC project team',
  r.authority                  = 'ACRIS real_property_master/real_property_parties records (NYC Department of Finance) establish both the grantee named on a deed transfer and the mortgagor named on a mortgage instrument, self-reported at the same closing under the same recording convention. The comparison threshold (-14 to +60 day purchase-money window, zero-token-overlap trigger) is Watchline editorial judgment, not a statutory or regulatory determination of concealment.',
  r.interpretive_concept       = 'MortgageBasedConcealment',
  r.input_types                = 'Building|Event[DeedTransfer, ACRIS]|Event[Mortgage, ACRIS]',
  r.threshold_description      = 'A building satisfies Watchline Rule MBC-001 (Mortgage-Based Concealment) if: (1) its most recent ACRIS DeedTransfer has a grantee name on record; AND (2) a Mortgage event exists on the same building recorded within -14 to +60 days of that deed (its purchase-money mortgage); AND (3) the mortgagor name(s) on that mortgage share no name token in common with the deed\'s grantee name(s). A building with no deed transfer, or with a deed but no mortgage recorded in the purchase-money window (e.g. an all-cash purchase), is insufficient_data -- there is no financing party to compare against, which is not itself a discrepancy.',
  r.threshold_logic            = 'latest_deed = most recent DeedTransfer Event on Building by event_date. nearest_mortgage = Mortgage Event on Building minimizing abs(days(latest_deed.event_date, m.event_date)), restricted to the range [-14, 60] days. token_overlap = normalize_tokens(latest_deed.grantee_names) INTERSECT normalize_tokens(nearest_mortgage.mortgagor_names) is non-empty. satisfied = latest_deed IS NOT NULL AND nearest_mortgage IS NOT NULL AND NOT token_overlap. confidence = Medium (see amendment_notes).',
  r.output_interpretive_status = 'Inferred',
  r.effective_date             = date('2026-07-17'),
  r.expiry_date                = null,
  r.explanation_template       = 'The building at {address}, {borough} (BBL {bbl}) {verdict} Watchline Rule MBC-001 (Mortgage-Based Concealment). The most recent deed transfer, recorded {deed_date}, names {grantee_names} as grantee. A mortgage recorded {mortgage_date} names {mortgagor_names} as mortgagor. {overlap_description} This finding is Medium confidence -- see the Rules tab for the purchase-money-window methodology. The interpretive status is Inferred.',
  r.falsification_conditions   = 'The mortgagor name(s) share at least one name token with the deed grantee name(s) -- treated as the expected purchase-money pattern, not a discrepancy. Or: no Mortgage event falls within the -14 to +60 day purchase-money window of the most recent deed transfer (all-cash purchase, or the financing mortgage was recorded outside this window, or was never ingested) -- insufficient_data, not evaluated. Or: the deed transfer itself has no recorded grantee name. Or: a later-discovered deed transfer or mortgage record supersedes the ones used in this evaluation.',
  r.amendment_notes            = 'Initial version. Calibrated against a live evidentiary sample 2026-07-17: of ~39,933 nearest-deed-to-mortgage pairs (sampled from the full ACRIS mortgage population, restricted to the -14/+60 day purchase-money window), 85.1% show an exact grantee/mortgagor name-token match, 12.0% show partial overlap, and 2.9% show zero overlap -- this last group is the population MBC-001 flags. A sub-sample breakdown of the zero-overlap group (n=461) found no dominant corporate/individual sub-pattern (29.5% corporate grantee + individual mortgagor, 23.2% the reverse, 8.7% both corporate, 38.6% both individual with unrelated names) -- unlike OND-001, this rule does NOT exclude corporate names from evaluation, since an LLC-took-title / unrelated-individual-financed pattern is itself a classic nominee-structure signal, not noise. The 2.9% flag rate is low and well-discriminated relative to OND-001\'s 71%, because both compared names come from the same ACRIS self-reporting convention on the same closing package rather than two independently-sourced datasets -- hence Medium rather than Low confidence. This rule evaluates only the building\'s MOST RECENT deed transfer (matching the OC-001 precedent), not its full transaction history; a building with an older concealment-pattern transaction that has since been superseded by a clean later sale will not be flagged. A future version could surface historical (non-most-recent) purchase-money mismatches as additional evidence context without changing the rule\'s own verdict.',
  r.deprecated                 = false;


// =============================================================================
// ResolutionMethod seeds -- added 2026-07-20, see notes/RESOLUTIONMETHOD-amendment.md
//
// RUL-00005 (RMT-003) and RUL-00006 (RMT-004) each APPLIES_METHOD to their own
// ResolutionMethod node. Today method and Rule are effectively 1:1 for these two,
// but the relationship is seeded explicitly so every identity-resolution Rule is
// consistent, and so future Rules (e.g. Splink-based matching, which trains and
// versions a model independently of any single Rule's threshold) can share a
// ResolutionMethod across more than one Rule without a schema change.
//
// IdentityAssertion nodes no longer carry a resolution_method_id property; they
// reference their producing Rule via PRODUCED_BY (same edge Claim and Relationship
// use), and the ResolutionMethod is reached by traversing PRODUCED_BY then
// APPLIES_METHOD.
// -----------------------------------------------------------------------------
// MTH-001: WeaklyConnectedComponents -- backs RUL-00005 (RMT-003)
// -----------------------------------------------------------------------------
MERGE (m1:ResolutionMethod:WatchlineNode:VersionedObject {method_id: 'MTH-001'})
SET
  m1.name                = 'WeaklyConnectedComponents',
  m1.version              = '1.0',
  m1.description          = 'Graph-theoretic identity-resolution technique that groups HPD registration contacts into candidate ownership networks by finding all IdentityObservations reachable from each other through any chain of name-based or address-based connections (RMT-001/RMT-002 edges), using Neo4j GDS Weakly Connected Components. Operationalized by Rule RUL-00005 (RMT-003 -- Weakly Connected Components Portfolio Detection).',
  m1.expected_confidence  = 'Medium',
  m1.effective_date       = date('2026-06-01');

MATCH (r1:Rule {rule_id: 'RUL-00005'})
MATCH (m1:ResolutionMethod {method_id: 'MTH-001'})
MERGE (r1)-[:APPLIES_METHOD]->(m1);

// -----------------------------------------------------------------------------
// MTH-002: LouvainCommunityDetection -- backs RUL-00006 (RMT-004)
// -----------------------------------------------------------------------------
MERGE (m2:ResolutionMethod:WatchlineNode:VersionedObject {method_id: 'MTH-002'})
SET
  m2.name                = 'LouvainCommunityDetection',
  m2.version              = '1.0',
  m2.description          = 'Recursive Louvain community detection used to split candidate ownership networks exceeding 300 BBLs (as identified by MTH-001) into more cohesive sub-networks, using edge weights derived from name- and address-based HPD registration connections. Operationalized by Rule RUL-00006 (RMT-004 -- Louvain Community Detection for Oversized Portfolio Splitting).',
  m2.expected_confidence  = 'Medium',
  m2.effective_date       = date('2026-06-01');

MATCH (r2:Rule {rule_id: 'RUL-00006'})
MATCH (m2:ResolutionMethod {method_id: 'MTH-002'})
MERGE (r2)-[:APPLIES_METHOD]->(m2);


// =============================================================================
// Verification query -- run after seeding to confirm all seventeen rules are present
// =============================================================================
//
// MATCH (r:Rule)
// RETURN r.rule_id, r.name, r.title, r.version, r.deprecated
// ORDER BY r.rule_id;
//
// Expected output:
//   RUL-00001  PHC-001  Persistent Hazardous Conditions                          1.0  false
//   RUL-00002  PBC-001  Probable Beneficial Control                              1.0  false
//   RUL-00003  RMT-001  HPD Registration Name-Based Connection                  1.0  false
//   RUL-00004  RMT-002  HPD Registration Address-Based Connection               1.0  false
//   RUL-00005  RMT-003  Weakly Connected Components Portfolio Detection          1.0  false
//   RUL-00006  RMT-004  Louvain Community Detection for Oversized Splitting      1.0  false
//   RUL-00007  DT-001   Deterioration Trajectory                                 1.0  false
//   RUL-00008  NE-001   Network Exposure                                         1.0  false
//   RUL-00009  MA-001   Management Differential                                  1.0  false
//   RUL-00010  RS-001   Rent Stabilization Loss                                  1.0  false
//   RUL-00011  FE-001   Fine Evasion                                             1.0  false
//   RUL-00012  EA-001   Enforcement Accountability Gap                           1.0  false
//   RUL-00013  RCV-001  Recidivism                                               1.0  false
//   RUL-00014  OC-001   Ownership Change Deterioration                          1.0  false
//   RUL-00015  VA-001   Vacate History                                           1.0  false
//   RUL-00016  OND-001  Ownership Name Discrepancy                               1.0  false
//   RUL-00017  MBC-001  Mortgage-Based Concealment                               1.0  false
// =============================================================================
