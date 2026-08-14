// ============================================================================
// Watchline DISCOVERY KG — standalone indexes
// watchline/discovery/schema/indexes.cypher
//
// Performance indexes that are NOT part of the graph type. `ALTER CURRENT
// GRAPH TYPE SET` (graph_type.cypher) only manages constraints and their
// automatic backing indexes (e.g. the one behind `Event.event_id IS KEY`) --
// it has no syntax for declaring a standalone index, so anything here is a
// separate DDL statement, applied independently by step_schema() after the
// graph type ALTER. Re-applying the graph type does not touch these, and
// re-running this file does not touch the graph type.
//
// Every statement here uses `IF NOT EXISTS`, so this file is safe to re-run.
// Index creation is online and non-blocking -- existing reads/writes keep
// running while a new index populates in the background; it just isn't used
// by the query planner until it reaches ONLINE. Check progress with:
//   SHOW INDEXES YIELD name, state, populationPercent
//
// Size and build time scale with total node count on the label, not with
// property cardinality -- these still cost real time/disk against Event's
// 42M+ nodes even though event_type only has ~10 distinct values.
// ============================================================================

// ---- Event.event_type ------------------------------------------------------
// The most common Event filter across the tool library ("just the
// violations," "just the judgments," etc.) has no index today -- confirmed
// by hitting a real query timeout while probing this live. Payoff is uneven
// across event_type values: for the sparser types (VacateOrder, Eviction,
// CourtFiling) this is close to a 1000x+ reduction in nodes scanned; for the
// largest (Complaint, Violation) the relative win is smaller but still real
// once combined with any second filter.

CREATE RANGE INDEX event_event_type IF NOT EXISTS
FOR (e:Event) ON (e.event_type);

// ---- Event.(event_type, event_date) — not yet enabled ----------------------
// Worth adding once the tool library actually has "recent violations" /
// "judgments in this date range" style access patterns -- premature before
// that, since we don't yet have real evidence this specific composite (vs.
// e.g. (event_type, source_name), given `Violation` spans both HPD and DOB)
// is the one that pays for itself. Uncomment when a real tool needs it:
//
// CREATE RANGE INDEX event_event_type_event_date IF NOT EXISTS
// FOR (e:Event) ON (e.event_type, e.event_date);

// ============================================================================
// Watchline DISCOVERY KG — indexes required by the discovery AGENT
// specs/required_indexes.cypher
//
// Authored 2026-07-29 by the agent module, for the pipeline owner to fold into
// the ingestion pipeline. The agent module itself is strictly read-only and
// never executes this file.
//
// Rationale: the agent's entry points are what a human types — a street
// address or a party name — but the live graph currently indexes only the
// four synthetic keys (bbl, actor_id, event_id, portfolio_id) plus
// Event(event_type) and Event(event_type, event_date). Measured cost of an
// unindexed exact-match address scan on 859,794 Buildings: ~2.9s. The
// equivalent over 14,821,930 Actor nodes is not viable at interactive
// latency.
//
// All statements are IF NOT EXISTS and safe to re-run. Apply AFTER bulk load
// (index maintenance during bulk insert is slower than building once at the
// end). Verify with `SHOW INDEXES`.
//
// Requirements: Neo4j 2026.06+ Enterprise, Cypher 25 — same target as
// graph_type.cypher.
// ============================================================================


// ---- REQUIRED ------------------------------------------------------------
// Without these, the corresponding tools cannot meet interactive latency.

// (1) Building.address — TEXT.
// Serves: Tier 1 #1/#2/#5, and the resolve_address tool that nearly every
// other query funnels through. TEXT (not RANGE) because user-typed addresses
// need CONTAINS / ENDS WITH as fallbacks after exact and prefix match fail —
// RANGE supports only exact, prefix, and range predicates.
// Note: `address` is neither unique nor always fully qualified — some rows
// carry a street with no house number (e.g. 'CARDER ROAD') — so this index
// enables candidate retrieval for disambiguation, not unique resolution.
CREATE TEXT INDEX building_address_text IF NOT EXISTS
FOR (b:Building) ON (b.address);

// (2) Building(borough, address) — composite RANGE.
// Borough is the natural first-pass disambiguator for a duplicated street
// address, and CLAUDE.md's ambiguity contract requires narrowing by an
// already-pinned borough deterministically before asking the user. Equality
// on borough + exact/prefix on address.
CREATE INDEX building_borough_address IF NOT EXISTS
FOR (b:Building) ON (b.borough, b.address);

// (3) Landlord.name — FULLTEXT.
// Serves: Tier 3 #4 ("given just a name a user typed, find the most likely
// matching landlord"). Scoped to :Landlord (118,493 nodes) rather than :Actor
// so the common, high-precision path stays small and fast. Fulltext because
// the stored values are genuinely dirty — real examples include ',MARIA
// CROSS', '.ARSILLO ANGELO', '(LARS) PETER LIBERT' — with leading
// punctuation, parentheticals, and frequent surname-first ordering. Exact
// and prefix matching cannot resolve these; token-based scoring can.
CREATE FULLTEXT INDEX landlord_name_fulltext IF NOT EXISTS
FOR (n:Landlord) ON EACH [n.name];

// (4) Event(source_name, event_type, event_date) — composite RANGE.
// Serves: Tier 2 #4 (evictions in the Bronx in 2025) and #7 (DOB violations
// citywide last month) — the two aggregations not scoped to a single
// building or portfolio, and therefore the two that actually need an index
// over 42,296,617 Event nodes.
// source_name leads deliberately: event_type is coarse — 'Violation' spans
// BOTH source_name 'DOB' and 'HPD', and DOB's violation_class codebook
// reuses 'A'/'B'/'C', colliding with HPD's A/B/C/I classes. Every violation
// query in this system must therefore constrain source_name, making it the
// correct leading equality column. The existing Event(event_type,
// event_date) index does not serve a source-constrained query.
CREATE INDEX event_source_type_date IF NOT EXISTS
FOR (e:Event) ON (e.source_name, e.event_type, e.event_date);


// ---- RECOMMENDED ---------------------------------------------------------
// Meaningful speedups for specific tools; not hard blockers.

// (5) Landlord.bizaddr — TEXT.
// Serves: Tier 3 #1 ("who else controls buildings registered at the same
// business address as this landlord?"). The CONNECTED_BY_ADDRESS edge already
// encodes this inference and should remain the primary path, but a direct
// address lookup is needed to (a) corroborate that edge and (b) catch
// same-address landlords the clustering run missed. Also supports the
// business-address distinguishing detail the disambiguation contract
// requires in candidate lists.
CREATE TEXT INDEX landlord_bizaddr_text IF NOT EXISTS
FOR (n:Landlord) ON (n.bizaddr);

// (6) Actor.name — FULLTEXT.
// Serves: Tier 3 #10 (walk a raw ACRIS deed-party name to the Landlord it
// matches, if any) — the one tool that must search the full, unresolved
// actor population rather than just resolved landlords.
// COST WARNING: 14,821,930 nodes. This index is materially expensive to
// build and to store, and it is needed by exactly one tool. Consider
// deferring until Phase 4, and confirm the disk/build-time budget first.
CREATE FULLTEXT INDEX actor_name_fulltext IF NOT EXISTS
FOR (n:Actor) ON EACH [n.name];


// ---- PIPELINE ENHANCEMENT (not an index) --------------------------------
// The higher-leverage fix for address resolution, if you're willing to add a
// property rather than only an index.
//
// Addresses are stored PLUTO-normalized: uppercase, ordinals stripped
// ('WEST 120 STREET', not 'West 120th Street'), abbreviations inconsistent.
// Every address the agent receives must be normalized to match, and that
// normalization currently has to live in agent code — meaning agent and
// pipeline can drift, silently, into disagreeing about what a match is.
//
// Emitting a canonical `Building.address_normalized` at ingest, and indexing
// THAT, moves normalization to the single place that owns the source format:
//
//   CREATE TEXT INDEX building_address_norm_text IF NOT EXISTS
//   FOR (b:Building) ON (b.address_normalized);
//
// If you add it, the agent will prefer it over (1) and (2) and apply the
// identical normalization function on the input side. Please expose the exact
// normalization rules used, so the agent can mirror them rather than guess.


// ---- VERIFY --------------------------------------------------------------
// SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state
//   WHERE state <> 'ONLINE' RETURN *;   // expect zero rows once built

