# Watchline NYC: Ontology Specification
## Conceptual Level

**Version 1.0 -- Draft for discussion. June 2026.**

---

## Purpose of This Document

This document defines the conceptual model that underlies the Watchline NYC system. It names the kinds of things the system recognizes, the relationships between them, and the principles that govern how they are structured.

This is not a database schema. It does not specify field names, data types, storage formats, or query languages. Those decisions belong to the implementation layer. What this document specifies is what exists in Watchline's world, how those things relate to each other, and why the model is structured the way it is.

Every component of the system, including the knowledge graph, the ingestion pipelines, the entity resolution engine, and the AI agent, should be understood as an implementation of this conceptual model. When implementation decisions conflict with the model, the model governs. When the model needs to change, it should be amended here first.

This document should be read alongside the [Watchline Founding Charter](https://github.com/bobflagg/WatchlineNYC/blob/main/documents/charter.md), which governs the purposes and principles of the system. The Charter answers why. This document answers what.

---

## The Five Layers

The conceptual model is organized into five layers. Each layer builds on the one below it.

```
Layer 5: Investigation   What users are trying to discover
Layer 4: Interpretation  Rules that transform evidence into claims
Layer 3: Identity        How observations become canonical entities
Layer 2: Evidence        What the system knows and how it knows it
Layer 1: Domain          Things that exist in the world
```

These layers are not independent silos. A single user question will typically traverse all five. The layers exist to keep concerns separated so that each can be improved without breaking the others.

---

## Layer 1: Domain

The Domain layer describes the things that exist in the world that Watchline reasons about. These are the objects that appear in source datasets and that users ask questions about.

### Core Concepts

**Asset**
A physical or legal property unit subject to regulation. In NYC housing enforcement, the primary asset type is a building, but the model also accommodates lots, parcels, and units where source data requires it. An Asset is identified by a canonical identifier (the BBL in NYC) and has a physical address and a regulatory history.

**Actor**
Any person, organization, or agency that plays a role in relation to an Asset. Actors include natural persons, limited liability companies, corporations, partnerships, government agencies, and courts. The same real-world Actor may appear under many different names and identifiers across source datasets; resolving these appearances into canonical Actors is the work of the Identity layer.

**Event**
A discrete occurrence that is recorded in a source dataset and that is associated with an Asset, an Actor, or both. Events include inspections, violations, complaints, permits, deed transfers, court filings, hearings, judgments, and enforcement actions. Every Event has a date, a source, and a legal or administrative status.

**Relationship**
A documented or inferred connection between two Actors, or between an Actor and an Asset. Relationship types include ownership, management, control, beneficial ownership, legal representation, and agency. Relationships have effective dates and may be historical as well as current. The distinction between documented and inferred Relationships is governed by the Evidence and Interpretation layers.

### What the Domain Layer Does Not Include

The Domain layer describes things that exist in the world. It does not describe what the system knows about those things, how confident it is, or what conclusions it has drawn. Those concerns belong to the layers above.

---

## Layer 2: Evidence

The Evidence layer describes how the system knows what it knows. It is the foundation for Watchline's commitment to transparency and defensibility.

### Core Concepts

**Observation**
A single record as it appears in a source dataset, before any interpretation or transformation. An Observation is the atomic unit of evidence. It represents exactly what a source said, nothing more. Observations are never modified after ingestion; they are the permanent record of what was received.

**Source**
The dataset or document from which an Observation originates. Each Source carries the identity of the producing agency, the legal authority under which it was produced, the date of production or retrieval, and a description of what the source is legally empowered to assert. HPD registration data, DOB violation records, ACRIS deed filings, and DHCR rent stabilization records are all distinct Sources with different legal standing.

**Evidence**
One or more Observations that, taken together, support a Claim. Evidence is the link between raw data and reasoned conclusions. A single Observation may contribute to multiple pieces of Evidence; a single piece of Evidence may draw on Observations from multiple Sources.

**Claim**
A statement that the system asserts about the world. Claims are the outputs that users see. Every Claim is supported by Evidence and produced by a Rule (see Layer 4). Claims are not observations; they are conclusions. The system must always be able to show the chain from Claim back through Evidence to Observations.

**Interpretive Status**
Every Claim carries an Interpretive Status that characterizes the epistemic basis for the assertion. The permitted values are:

- **Observed**: the Claim directly reflects what a source record states, with no inference required.
- **Derived**: the Claim is calculated from observations using a defined formula or aggregation.
- **Estimated**: the Claim involves approximation where exact data is unavailable.
- **Inferred**: the Claim results from applying a defined reasoning rule to a body of evidence.
- **Stipulated**: the Claim reflects a legal finding or official determination by an authority with jurisdiction.
- **Disputed**: the Claim is contested by evidence or by an Actor named in it.

Interpretive Status is not a confidence score. It characterizes the kind of knowledge, not the probability that it is correct.

### The Evidence Chain

Every Claim produced by Watchline must be traceable through the following chain:

```
Claim
  produced by Rule (Layer 4)
  supported by Evidence
    derived from Observations
      originating in Source records
```

If any link in this chain cannot be established, the Claim must not be made.

---

## Layer 3: Identity

The Identity layer addresses one of the hardest problems in NYC housing data: the same real-world person, company, or building may appear under dozens of different names and identifiers across different source datasets. Identity resolution is the process of determining when different appearances refer to the same real-world entity.

### Core Concepts

**Observation (Identity)**
In the Identity layer, an Observation is a specific appearance of a name, address, identifier, or other descriptor in a source dataset. "123 Main LLC," "123 Main, LLC," and "123 Main LLC C/O XYZ Management" are three distinct Identity Observations. They are not immediately collapsed into a single entity; the uncertainty about whether they refer to the same real-world Actor lives here.

**Identity Assertion**
A reasoned judgment that two or more Identity Observations refer to the same real-world entity. Identity Assertions are produced by defined resolution methods and carry their own Interpretive Status. An Identity Assertion based on exact match of a state registration number is Observed. An Identity Assertion based on shared registered agent and overlapping officer names is Inferred.

**Canonical Entity**
The unified representation of a real-world Actor or Asset, created by accepting one or more Identity Assertions. A Canonical Entity is the node in the knowledge graph that other nodes connect to. It carries a record of all Identity Observations that were resolved into it, the Identity Assertions that justified the resolution, and the confidence of those assertions.

**Resolution Method**
The defined process by which Identity Assertions are made. Resolution Methods are named, versioned, and documented. Examples include exact identifier match (BBL, EIN, state registration number), probabilistic name matching, shared registered agent, shared business address, and overlapping officer or principal listings.

### Why Identity Is a First-Class Layer

Many knowledge graph systems treat entity resolution as a preprocessing step that happens before the graph is built. Watchline treats it as a first-class layer because the uncertainty in identity resolution is material to the conclusions the system draws. A Claim about who owns a building is only as strong as the Identity Assertions that established the ownership chain. Making Identity explicit allows the system to represent and communicate that uncertainty honestly.

---

## Layer 4: Interpretation

The Interpretation layer is where Evidence becomes Claims. It contains the Rules that the system applies to transform bodies of evidence into conclusions about the world.

### Core Concepts

**Rule**
A named, versioned, documented procedure for producing a Claim from Evidence. Rules are first-class objects in the ontology, not implementation details buried in code. Every inference the system makes must be traceable to a specific Rule. See the Rules section below for the full specification of a Rule and a worked example.

**Threshold**
The quantitative or qualitative criterion that a body of Evidence must meet for a Rule to produce a positive Claim. Thresholds are explicit, inspectable, and part of the Rule record. A user who disagrees with a conclusion can inspect the Threshold and argue that it should be set differently.

**Interpretive Concept**
A higher-level concept that a Rule produces, which does not exist in any source dataset but is defined by Watchline for investigative purposes. Examples include Persistent Hazardous Conditions, Probable Common Beneficial Control, and Portfolio Concentration. These concepts are normative: they apply a standard, not merely a label. Each Interpretive Concept must be defined with precision, and the Rules that produce it must be explicit about what that standard is.

### Rules as Constitutional Objects

Rules occupy a special position in the Watchline model. They are the mechanism that makes the system's reasoning transparent, the instrument that makes conclusions defensible, and the record that allows conclusions to be challenged and revised. A system that makes inferences without explicit Rules is a system whose reasoning cannot be inspected.

The governance of Rules is specified in the Watchline Founding Charter (Principles 11 and 15). Rules may be added, amended, or deprecated, but never silently modified. Every change to a Rule must be documented, and the version history of every Rule must be retained.

### Worked Example: Persistent Hazardous Conditions

See the worked example in the Rules section below.

---

## Layer 5: Investigation

The Investigation layer describes the kinds of questions users bring to Watchline and the investigative concepts that organize them. This layer is what makes Watchline more than a data integration platform: it models not just what exists, but what users are trying to find out.

### Core Concepts

**Investigative Intent**
The category of question a user is asking. The AI agent uses Investigative Intent to select the appropriate Rules, graph traversal paths, and evidence chains to assemble an answer. Investigative Intents are not a fixed taxonomy; they should be extended as the system learns from real use.

Initial Investigative Intent categories include:

- **Ownership**: who owns or controls an asset, currently or historically
- **Beneficial Ownership**: who ultimately controls an asset behind a chain of legal entities
- **Portfolio**: what other assets does an Actor control, and what is the pattern across them
- **Enforcement History**: what violations, complaints, and enforcement actions are associated with an asset or Actor
- **Accountability**: who was responsible for an asset during a period when conditions deteriorated
- **Recidivism**: whether an Actor has a pattern of repeated violations across assets or over time
- **Concealment**: whether ownership structures suggest deliberate obscuring of control
- **Neighborhood Pattern**: how conditions at an asset compare to similar assets in the same area

**Canonical Question**
A reusable template for a class of questions that maps to a defined graph traversal and a set of applicable Rules. Canonical Questions are the bridge between natural language and structured graph queries. They are not rigid query templates; they are patterns that the AI agent instantiates with specific entities and parameters drawn from the user's question.

### The Role of the AI Agent in This Layer

The AI agent operates primarily in the Investigation layer. Its job is to identify the user's Investigative Intent, select the appropriate Canonical Questions and Rules, retrieve the relevant Evidence from the graph, and present the resulting Claims in plain language with explicit links to the supporting evidence.

The AI agent does not reason independently about what is true. It orchestrates the system's defined reasoning machinery. The quality of the system's answers depends primarily on the quality of the Rules and the ontology, not on the capabilities of the language model.

---

## Rules: Full Specification

Every Rule in the Watchline system must carry the following fields.

| Field | Description |
|---|---|
| Name | A short, unique identifier for the Rule (e.g., PHC-001) |
| Title | A plain-language name for the Rule |
| Version | A version number, incremented on every substantive change |
| Author | The person or team who defined the Rule |
| Authority | The source of authority for the Rule's definition (e.g., HPD classification standards, FinCEN beneficial ownership guidelines, Watchline editorial judgment) |
| Layer | The Interpretation layer concept the Rule produces |
| Inputs | The Evidence types and Observations the Rule consumes |
| Threshold | The explicit criterion that must be satisfied for the Rule to produce a positive Claim |
| Interpretive Status | The Interpretive Status that Claims produced by this Rule will carry |
| Effective Date | The date from which this version of the Rule applies |
| Expiry Date | If applicable, the date after which this version no longer applies |
| Explanation | A plain-language explanation of the Rule suitable for presentation to a user |
| Falsification | What evidence would cause the Rule to produce a negative or Disputed Claim |
| Amendment Notes | A record of what changed from the previous version and why |

### Worked Example: Rule PHC-001

**Name:** PHC-001

**Title:** Persistent Hazardous Conditions

**Version:** 1.0

**Author:** Watchline NYC project team

**Authority:** HPD violation classification standards (Class C: immediately hazardous). Threshold values reflect Watchline editorial judgment based on review of HPD enforcement practice; they are not derived from a statutory definition.

**Layer:** Interpretive Concept produced: Persistent Hazardous Conditions

**Inputs:**
- HPD violation records for the subject building (Source: HPD Online)
- Violation class (A, B, or C)
- Violation open date
- Violation status (open, closed, dismissed)
- Presence of active remediation orders

**Threshold:** All of the following must be true:
1. Three or more Class C (immediately hazardous) violations are currently open.
2. The oldest open Class C violation has been open for more than 180 days.
3. No active remediation order is in effect for the building.

**Interpretive Status:** Inferred

**Effective Date:** June 2026

**Expiry Date:** None (current version)

**Explanation presented to user:** This building satisfies Watchline Rule PHC-001 for Persistent Hazardous Conditions. It has [N] open Class C violations, the oldest of which has been open for [X] days. There is no active remediation order on record. This conclusion is based on HPD violation data retrieved on [date]. Class C violations are classified by HPD as immediately hazardous. The 180-day threshold and the minimum count of three violations reflect Watchline's editorial judgment, not a statutory definition. A different threshold would produce a different result.

**Falsification:** The Rule produces a negative result if: fewer than three Class C violations are open, or the oldest open Class C violation has been open for 180 days or fewer, or an active remediation order is in effect. The Rule produces a Disputed result if any open violation is under active contest in Housing Court.

**Amendment Notes:** Initial version. No prior version exists.

---

## Relationship to the Founding Charter

This Ontology Specification implements the conceptual commitments made in the Founding Charter. The following table maps Charter principles to the ontology layer where they are primarily expressed.

| Charter Principle | Ontology Layer |
|---|---|
| Defensibility (7) | Evidence, Interpretation |
| Full Exposure of Justification (8) | Evidence chain |
| Distinction between Observation, Inference, and Claim (9) | Evidence, Identity |
| Interpretive Status over Statistical Confidence (10) | Evidence |
| Rules as First-Class Objects (11) | Interpretation |
| Reversibility (12) | Evidence, Identity |
| Productive Disagreement (13) | Interpretation (Threshold) |
| Scope of Jurisdiction (16) | Evidence (Source) |

---

*This document should be read alongside the Watchline Founding Charter and the Implementable Ontology Specification.*
