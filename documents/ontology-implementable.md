# Watchline NYC: Ontology Specification
## Implementable Level

**Version 1.2 -- July 2026.**

**Amendment (2026-07-20):** `IdentityAssertion.resolution_method_id` removed; replaced
by a `PRODUCED_BY` edge to `Rule`, matching how `Claim` and `Relationship` already
reference the `Rule` that produced them. `ResolutionMethod.method_id` format changed
from `RMT-[uuid]` to `MTH-[uuid]` to avoid colliding with `Rule.name` short codes.
`Rule` gained an optional `APPLIES_METHOD` edge to `ResolutionMethod`. Rationale: no
`ResolutionMethod` node had ever been created; every `IdentityAssertion` instead
carried a `Rule.rule_id` in the mislabeled `resolution_method_id` field, an
unenforceable convention rather than a real reference. `ResolutionMethod` is retained,
not dropped, because upcoming entity-linking techniques (e.g. Splink) are trained and
versioned independently of any single Rule's thresholds and may back more than one
Rule at different confidence levels. See `notes/RESOLUTIONMETHOD-amendment.md`.

---

## Purpose of This Document

This document translates the Watchline Conceptual Ontology Specification into a form that can directly guide graph database design, ingestion pipeline development, and AI agent prompt engineering. It defines node types, edge types, required properties, optional properties, and the constraints that govern them.

This document is implementation-agnostic: it does not assume a specific graph database (Neo4j, Amazon Neptune, etc.) or a specific serialization format (RDF, LPG, etc.). The node and edge types defined here should translate directly into whatever storage layer is chosen.

This document must remain consistent with the Watchline Conceptual Ontology Specification. If a conflict arises, the Conceptual Specification governs. Proposed additions or changes to this document should be evaluated against the Founding Charter before adoption.

---

## Conventions

**Node types** are written in PascalCase: `Building`, `Actor`, `Claim`.

**Edge types** are written in SCREAMING_SNAKE_CASE: `OWNS`, `SUPPORTED_BY`, `PRODUCED_BY`.

**Required properties** are marked **(R)**.

**Optional properties** are marked **(O)**.

**Controlled vocabulary** fields list permitted values explicitly. No other values are permitted without a documented amendment.

---

## Layer 1: Domain Nodes

### Building

Represents a physical structure subject to NYC housing regulation.

| Property | Type | Req | Description |
|---|---|---|---|
| bbl | String | R | Borough-Block-Lot identifier. Canonical key. Format: 10-digit string. |
| address | String | R | Normalized street address. |
| borough | String | R | One of: Manhattan, Brooklyn, Queens, Bronx, Staten Island |
| bin | String | O | Building Identification Number (DOB). |
| latitude | Float | O | WGS84 latitude. |
| longitude | Float | O | WGS84 longitude. |
| building_class | String | O | NYC building classification code. |
| year_built | Integer | O | Year of construction per available records. |
| residential_units | Integer | O | Number of residential units per HPD registration. |
| created_at | DateTime | R | Timestamp of record creation in Watchline. |
| updated_at | DateTime | R | Timestamp of most recent update. |

**Edges out:**
- `HAS_EVENT` to `Event`
- `SUBJECT_OF` to `Claim`

**Notes:** BBL is the primary join key across HPD, DOB, ACRIS, and DHCR datasets. Ingestion pipelines must normalize all source identifiers to BBL before creating Building nodes.

---

### Actor

Represents any person, organization, or agency that appears in relation to a Building or Event. This is a single node type covering natural persons, LLCs, corporations, partnerships, government agencies, and ownership networks. The `actor_type` property distinguishes them.

**OwnershipNetwork** is a virtual actor type. It does not correspond to a legally registered entity. It represents a cluster of landlord observations identified as probably under common beneficial control by the portfolio detection algorithm (Rules RMT-001 through RMT-004 and PBC-001). Claims about an OwnershipNetwork must always disclose this in their explanation text.

| Property | Type | Req | Description |
|---|---|---|---|
| canonical_id | String | R | Watchline-assigned identifier. Format: ACT-[uuid]. |
| actor_type | String | R | Controlled vocabulary: NaturalPerson, LLC, Corporation, Partnership, GovernmentAgency, Court, OwnershipNetwork, Other |
| display_name | String | R | The name used for display. Set during entity resolution. For OwnershipNetwork, derived from the most prominent landlord name in the community. |
| state_registration_id | String | O | NY Department of State entity ID. Not applicable to OwnershipNetwork actors. |
| ein | String | O | Federal Employer Identification Number. Not applicable to OwnershipNetwork actors. |
| created_at | DateTime | R | Timestamp of record creation in Watchline. |
| updated_at | DateTime | R | Timestamp of most recent update. |
| resolution_confidence | String | R | Controlled vocabulary: High, Medium, Low. Reflects confidence in the canonical identity. For OwnershipNetwork, derived from community cohesion metrics. |
| run_id | String | O | Pipeline run identifier. Populated only on OwnershipNetwork actors. Records the pipeline run that created or last updated this actor for versioned audit. |

**Edges out:**
- `PARTY_TO` to `Event`
- `SUBJECT_OF` to `Claim`
- `RESOLVED_FROM` to `IdentityObservation` (one or more; not used for OwnershipNetwork)
- `MERGED_INTO` to `Actor` (OwnershipNetwork only; when this actor is superseded by a merge)
- `SPLIT_INTO` to `Actor` (OwnershipNetwork only; when this actor fragments into sub-communities)

**Edges in:**
- `INVOLVES_ACTOR` from `Relationship`
- `RESOLVES_TO` from `IdentityAssertion` (OwnershipNetwork actors are reached this way, not via RESOLVED_FROM)

**Notes:** Actor nodes are created by the Identity layer (Layer 3), not directly from source data. Source data produces IdentityObservation nodes first. Actor nodes are created only when an Identity Assertion justifies consolidation. OwnershipNetwork actors are an exception: they are created by the portfolio detection algorithm and matched across runs using the anchor node protocol defined in the Design Rationale.

---

### Event

Represents a discrete recorded occurrence associated with a Building or Actor.

| Property | Type | Req | Description |
|---|---|---|---|
| event_id | String | R | Watchline-assigned identifier. Format: EVT-[uuid]. |
| event_type | String | R | Controlled vocabulary: Violation, Complaint, Inspection, Permit, DeedTransfer, CourtFiling, Hearing, Judgment, LienFiling, RegistrationFiling |
| source_id | String | R | The identifier assigned by the originating source system. |
| source_name | String | R | The name of the originating source (e.g., HPD, DOB, ACRIS, DHCR, OATH). |
| event_date | Date | R | The date the event occurred or was recorded. |
| status | String | R | Controlled vocabulary: Open, Closed, Dismissed, Pending, Active, Expired, Unknown |
| legal_authority | String | O | The statutory or regulatory basis for the event. |
| description | String | O | Plain-language description from the source record. |
| raw_record | JSON | R | The complete source record as received, stored verbatim. |
| created_at | DateTime | R | Timestamp of record creation in Watchline. |

**Edges out:**
- `ORIGINATES_IN` to `Source`

**Edges in:**
- `HAS_EVENT` from `Building`
- `PARTY_TO` from `Actor`

**Subtype properties for Violation events:**

| Property | Type | Req | Description |
|---|---|---|---|
| violation_class | String | O | HPD: A, B, or C. DOB: varies by type. |
| violation_code | String | O | Source-specific violation code. |
| open_date | Date | O | Date violation was issued. |
| closed_date | Date | O | Date violation was resolved, if applicable. |
| days_open | Integer | O | Calculated: current date minus open_date if still open. |
| section | String | O | Housing Maintenance Code or other regulatory section cited. |

---

### Relationship

Represents a documented or inferred connection between two Actors, or between an Actor and a Building.

| Property | Type | Req | Description |
|---|---|---|---|
| relationship_id | String | R | Watchline-assigned identifier. Format: REL-[uuid]. |
| relationship_type | String | R | Controlled vocabulary: Owner, ManagingAgent, BeneficialOwner, Officer, RegisteredAgent, MortgageHolder, LegalRepresentative, ProbableControl |
| subject_id | String | R | canonical_id of the Actor in the subject position. |
| object_id | String | R | canonical_id of the Actor or BBL of the Building in the object position. |
| effective_from | Date | O | Date from which the relationship is known to be in effect. |
| effective_to | Date | O | Date after which the relationship is no longer in effect. Null if current. |
| interpretive_status | String | R | Controlled vocabulary: Observed, Derived, Inferred, Stipulated, Disputed |
| basis | String | R | Plain-language description of why this relationship was asserted. |
| created_at | DateTime | R | Timestamp of record creation in Watchline. |

**Edges out:**
- `SUPPORTED_BY` to `Evidence` (one or more)
- `PRODUCED_BY` to `Rule` (if Inferred or Derived)

---

## Layer 2: Evidence Nodes

### Source

Represents an originating dataset or document.

| Property | Type | Req | Description |
|---|---|---|---|
| source_id | String | R | Watchline-assigned identifier. Format: SRC-[uuid]. |
| source_name | String | R | Display name (e.g., "HPD Online Violations"). |
| producing_agency | String | R | The agency or organization that produces this data. |
| legal_authority | String | O | The statute or regulation under which the data is produced. |
| data_url | String | O | URL of the source dataset or API. |
| retrieval_date | Date | R | Date Watchline last retrieved data from this source. |
| coverage_start | Date | O | Earliest date covered by the source. |
| coverage_end | Date | O | Latest date covered, if not ongoing. |
| description | String | R | Plain-language description of what this source contains and what it is legally empowered to assert. |

---

### Observation

Represents a single record as ingested from a source, before any transformation or interpretation.

| Property | Type | Req | Description |
|---|---|---|---|
| observation_id | String | R | Watchline-assigned identifier. Format: OBS-[uuid]. |
| source_id | String | R | Foreign key to Source. |
| raw_content | JSON | R | The complete source record, stored verbatim and never modified. |
| ingested_at | DateTime | R | Timestamp of ingestion. |
| source_record_id | String | O | The identifier assigned to this record by the source system. |

**Edges out:**
- `ORIGINATES_IN` to `Source`

**Edges in:**
- `DERIVED_FROM` from `Evidence`

---

### Evidence

Represents one or more Observations that together support a Claim or Relationship.

| Property | Type | Req | Description |
|---|---|---|---|
| evidence_id | String | R | Watchline-assigned identifier. Format: EVI-[uuid]. |
| summary | String | R | Plain-language summary of what this Evidence shows. |
| created_at | DateTime | R | Timestamp of record creation. |

**Edges out:**
- `DERIVED_FROM` to `Observation` (one or more)

**Edges in:**
- `SUPPORTED_BY` from `Claim`
- `SUPPORTED_BY` from `Relationship`

---

### Claim

Represents a statement the system asserts about the world.

| Property | Type | Req | Description |
|---|---|---|---|
| claim_id | String | R | Watchline-assigned identifier. Format: CLM-[uuid]. |
| claim_text | String | R | Plain-language statement of the claim. |
| interpretive_status | String | R | Controlled vocabulary: Observed, Derived, Estimated, Inferred, Stipulated, Disputed |
| subject_type | String | R | The type of entity the claim is about: Building, Actor, Relationship, Portfolio |
| subject_id | String | R | The canonical_id or BBL of the entity the claim is about. |
| valid_from | Date | O | The date from which the claim is asserted to be true. |
| valid_to | Date | O | The date after which the claim is no longer asserted. Null if current. |
| created_at | DateTime | R | Timestamp when this claim was generated. |
| superseded_by | String | O | claim_id of the Claim that replaces this one, if this claim has been revised. |

**Edges out:**
- `SUPPORTED_BY` to `Evidence` (one or more)
- `PRODUCED_BY` to `Rule`

---

## Layer 3: Identity Nodes

### IdentityObservation

Represents a specific appearance of a name, identifier, or descriptor in a source record.

| Property | Type | Req | Description |
|---|---|---|---|
| iobs_id | String | R | Watchline-assigned identifier. Format: IOBS-[uuid]. |
| raw_name | String | R | The name or identifier exactly as it appears in the source. |
| source_id | String | R | Foreign key to Source. |
| observation_id | String | R | Foreign key to the Observation in which this appearance occurs. |
| context | String | O | The role this name plays in the source record (e.g., Head Officer, Registered Agent, Grantee). |
| ingested_at | DateTime | R | Timestamp of ingestion. |

---

### IdentityAssertion

Represents a reasoned judgment that two or more IdentityObservations refer to the same real-world entity.

| Property | Type | Req | Description |
|---|---|---|---|
| iassertion_id | String | R | Watchline-assigned identifier. Format: IAS-[uuid]. |
| interpretive_status | String | R | Controlled vocabulary: Observed, Inferred, Estimated |
| confidence | String | R | Controlled vocabulary: High, Medium, Low |
| rationale | String | R | Plain-language explanation of why these observations were judged to refer to the same entity. |
| created_at | DateTime | R | Timestamp of assertion. |
| created_by | String | R | The pipeline, algorithm, or person that made this assertion. |

**Edges out:**
- `ASSERTS_IDENTITY_OF` to `IdentityObservation` (two or more)
- `RESOLVES_TO` to `Actor`
- `PRODUCED_BY` to `Rule` (required; see Constraints and Invariants #10)

**Notes:** Prior to 2026-07-20 this node carried a `resolution_method_id` string
property intended as a foreign key to `ResolutionMethod`. In practice it was always
populated with a `Rule.rule_id` (no `ResolutionMethod` node was ever created), so it
functioned as an unenforced, mislabeled alias for the relationship declared above.
`PRODUCED_BY` replaces it, using the same edge `Claim` and `Relationship` already use
to reference the `Rule` that produced them. See `notes/RESOLUTIONMETHOD-amendment.md`.

---

### ResolutionMethod

Represents a named, versioned procedure for making Identity Assertions, operationalized
by one or more `Rule`s via `APPLIES_METHOD`. Kept as a node type distinct from `Rule` so
that a resolution technique (for example, a trained Splink model) can be versioned
independently of any single `Rule`'s thresholds, and so more than one `Rule` can apply
the same method at different thresholds (e.g., a high-confidence threshold feeding
Claims and a looser threshold feeding Leads).

| Property | Type | Req | Description |
|---|---|---|---|
| method_id | String | R | Watchline-assigned identifier. Format: MTH-[uuid]. Deliberately distinct from `Rule.name` short codes (e.g. RMT-003) -- that prefix collision is what originally caused `IdentityAssertion.resolution_method_id` to be populated with a Rule ID instead of a real ResolutionMethod reference. |
| name | String | R | Short name (e.g., ExactBBLMatch, SharedRegisteredAgent). |
| version | String | R | Version number. |
| description | String | R | Plain-language description of the method. |
| expected_confidence | String | R | Controlled vocabulary: High, Medium, Low. The confidence level this method typically produces. |
| effective_date | Date | R | Date from which this version applies. |

**Edges in:**
- `APPLIES_METHOD` from `Rule`

---

## Layer 4: Interpretation Nodes

### Rule

Represents a named, versioned procedure for producing a Claim from Evidence. Rules are first-class ontological objects.

| Property | Type | Req | Description |
|---|---|---|---|
| rule_id | String | R | Watchline-assigned identifier. Format: RUL-[uuid]. |
| name | String | R | Short code (e.g., PHC-001). |
| title | String | R | Plain-language title. |
| version | String | R | Version number. Increment on every substantive change. |
| author | String | R | Person or team who defined the Rule. |
| authority | String | R | Source of authority for the Rule's definition. |
| interpretive_concept | String | R | The Interpretive Concept this Rule produces (e.g., PersistentHazardousConditions). |
| input_types | Array[String] | R | The Event types, Relationship types, or other node types this Rule consumes. |
| threshold_description | String | R | Plain-language description of the threshold that must be satisfied. |
| threshold_logic | String | R | Formal expression of the threshold (pseudocode or structured logic). |
| output_interpretive_status | String | R | The Interpretive Status that Claims produced by this Rule will carry. |
| effective_date | Date | R | Date from which this version applies. |
| expiry_date | Date | O | Date after which this version no longer applies. |
| explanation_template | String | R | Template for the plain-language explanation presented to users. Uses placeholders for variable values. |
| falsification_conditions | String | R | Description of evidence that would cause the Rule to produce a negative or Disputed result. |
| amendment_notes | String | O | Record of what changed from the previous version and why. |
| deprecated | Boolean | R | True if this Rule version has been superseded. Deprecated Rules are never deleted. |

**Edges out:**
- `SUPERSEDED_BY` to `Rule` (if deprecated)
- `APPLIES_METHOD` to `ResolutionMethod` (optional; when this Rule operationalizes a
  distinct, independently-versioned resolution technique)

**Edges in:**
- `PRODUCED_BY` from `Claim`
- `PRODUCED_BY` from `Relationship` (if Inferred)
- `PRODUCED_BY` from `IdentityAssertion`

### Worked Example: Rule PHC-001

```json
{
  "rule_id": "RUL-00001",
  "name": "PHC-001",
  "title": "Persistent Hazardous Conditions",
  "version": "1.0",
  "author": "Watchline NYC project team",
  "authority": "HPD violation classification standards (Class C: immediately hazardous). Threshold values reflect Watchline editorial judgment based on review of HPD enforcement practice; they are not derived from a statutory definition.",
  "interpretive_concept": "PersistentHazardousConditions",
  "input_types": ["Violation"],
  "threshold_description": "Three or more Class C violations are currently open, the oldest has been open for more than 180 days, and no active remediation order is in effect.",
  "threshold_logic": "COUNT(violations WHERE class='C' AND status='Open') >= 3 AND MAX(days_open WHERE class='C' AND status='Open') > 180 AND NOT EXISTS(remediation_order WHERE status='Active')",
  "output_interpretive_status": "Inferred",
  "effective_date": "2026-06-01",
  "expiry_date": null,
  "explanation_template": "This building satisfies Watchline Rule PHC-001 for Persistent Hazardous Conditions. It has {open_c_count} open Class C violations, the oldest of which has been open for {oldest_days} days. There is no active remediation order on record. This conclusion is based on HPD violation data retrieved on {retrieval_date}. Class C violations are classified by HPD as immediately hazardous. The 180-day threshold and the minimum count of three violations reflect Watchline editorial judgment, not a statutory definition. A different threshold would produce a different result.",
  "falsification_conditions": "Fewer than three Class C violations are open; or the oldest open Class C violation has been open for 180 days or fewer; or an active remediation order is in effect. Produces Disputed status if any open violation is under active contest in Housing Court.",
  "amendment_notes": "Initial version. No prior version exists.",
  "deprecated": false
}
```

---

## Layer 5: Investigation Nodes

### InvestigativeIntent

Represents the category of question a user is asking. Used by the AI agent to select appropriate Rules and traversal patterns.

| Property | Type | Req | Description |
|---|---|---|---|
| intent_id | String | R | Watchline-assigned identifier. Format: INT-[uuid]. |
| name | String | R | Short name (e.g., BeneficialOwnership, EnforcementHistory). |
| description | String | R | Plain-language description of the investigative question this Intent covers. |
| applicable_rules | Array[String] | R | rule_ids of Rules typically invoked for this Intent. |
| canonical_question_ids | Array[String] | R | IDs of CanonicalQuestion templates associated with this Intent. |

### CanonicalQuestion

Represents a reusable template for a class of user questions.

| Property | Type | Req | Description |
|---|---|---|---|
| cq_id | String | R | Watchline-assigned identifier. Format: CQ-[uuid]. |
| intent_id | String | R | Foreign key to InvestigativeIntent. |
| question_template | String | R | Natural-language template with placeholders (e.g., "Who owns {building} and what is the ownership history?"). |
| traversal_description | String | R | Plain-language description of the graph traversal required to answer this question. |
| required_node_types | Array[String] | R | Node types that must be present for this question to be answerable. |
| applicable_rule_ids | Array[String] | O | Rules that are typically applied when answering this question. |

---

## Edge Type Summary

| Edge | From | To | Description |
|---|---|---|---|
| HAS_EVENT | Building | Event | A building has an associated event. |
| INVOLVES_BUILDING | Relationship | Building | A relationship concerns this building. Symmetric to INVOLVES_ACTOR for the asset side. |
| SUBJECT_OF | Building, Actor | Claim | An entity is the subject of a claim. Declared in schema using shared WatchlineNode implied label. |
| PARTY_TO | Actor | Event | An actor is a named party in an event. |
| RESOLVED_FROM | Actor | IdentityObservation | A canonical actor was resolved from this observation. Not used for OwnershipNetwork actors. |
| INVOLVES_ACTOR | Relationship | Actor | A relationship involves this actor. |
| ORIGINATES_IN | Event, Observation | Source | An event or observation comes from this source. Declared in schema using shared WatchlineNode implied label. |
| SUPPORTED_BY | Claim, Relationship | Evidence | A claim or relationship is supported by this evidence. Declared in schema using shared WatchlineNode implied label. |
| PRODUCED_BY | Claim, Relationship, IdentityAssertion | Rule | A claim, relationship, or identity assertion was produced by this rule. Declared in schema using shared WatchlineNode implied label. |
| APPLIES_METHOD | Rule | ResolutionMethod | A rule operationalizes this resolution method. Reach a method from an IdentityAssertion by traversing PRODUCED_BY then APPLIES_METHOD. |
| DERIVED_FROM | Evidence | Observation | Evidence is derived from these observations. Used when Evidence links directly to raw source records. |
| AGGREGATES | Evidence | IdentityAssertion | Evidence aggregates one or more IdentityAssertions. Used by the portfolio pipeline when Evidence is built from Identity layer outputs rather than raw Observations. |
| ASSERTS_IDENTITY_OF | IdentityAssertion | IdentityObservation | An assertion links two or more observations. |
| RESOLVES_TO | IdentityAssertion | Actor | An assertion resolves observations to a canonical actor. Used for OwnershipNetwork actors. |
| SUPERSEDED_BY | Rule | Rule | A deprecated rule was replaced by this rule. |
| MERGED_INTO | Actor | Actor | An OwnershipNetwork actor superseded by a merge points to the surviving actor. |
| SPLIT_INTO | Actor | Actor | An OwnershipNetwork actor that fragmented points to each resulting sub-community actor. |

---

## Constraints and Invariants

The following constraints must be enforced by ingestion pipelines and must be validated before any Claim is surfaced to a user.

1. Every Claim must have at least one SUPPORTED_BY edge to an Evidence node.
2. Every Claim with interpretive_status of Inferred, Derived, or Estimated must have a PRODUCED_BY edge to a Rule node.
3. Every Evidence node must have at least one DERIVED_FROM edge to an Observation node.
4. Every Observation node must have an ORIGINATES_IN edge to a Source node.
5. Every IdentityAssertion must have at least two ASSERTS_IDENTITY_OF edges.
6. Every Actor node of type other than OwnershipNetwork must have at least one RESOLVED_FROM edge to an IdentityObservation. Every Actor node of type OwnershipNetwork must have at least one inbound RESOLVES_TO edge from an IdentityAssertion.
7. No Rule node with deprecated=true may have PRODUCED_BY edges from active Claims. Deprecated Rules may only be referenced for historical audit purposes.
8. Every Relationship with interpretive_status of Inferred must have a PRODUCED_BY edge to a Rule.
9. Every OwnershipNetwork Actor must carry a run_id property matching the pipeline run that created or last updated it.
10. Every IdentityAssertion must have a PRODUCED_BY edge to a Rule node. (Added 2026-07-20; replaces the removed resolution_method_id property.)

---

## Versioning and Amendment

This document is versioned. Changes to node types, edge types, required properties, or controlled vocabulary values constitute substantive amendments and must be documented with the date, author, and rationale. Optional properties may be added with a note but do not require a full amendment.

Changes that affect the output of existing Rules (for example, adding a property that a Rule depends on) must trigger a review of affected Rules before the change is deployed.

---

*This document should be read alongside the Watchline Founding Charter and the Conceptual Ontology Specification.*
