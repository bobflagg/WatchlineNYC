# Watchline NYC: Founding Charter

**Version 1.1 -- June 2026.**

---

## Preamble

This Charter defines what Watchline NYC exists to do, who it serves, what it refuses to be, and the principles that govern how it acquires knowledge, reasons from evidence, and speaks about the world. Every component of the system, including the knowledge graph, the ingestion pipelines, the entity resolution engine, and the AI agent, is subordinate to this document. The Charter should be consulted whenever a design decision cannot be resolved by technical considerations alone.

Watchline is accountability infrastructure. It is not an advocate, a regulator, or a publisher. It is a shared public capability that enables journalists, tenant advocates, legal services organizations, policy analysts, and watchdog agencies to conduct rigorous, evidence-based investigation into NYC housing conditions and ownership accountability.

---

## I. Purpose

### 1. Mission

Watchline exists to make the kind of evidence-based investigation that currently takes an expert hours available in minutes, and to make it accessible not only to specialists but to anyone who needs to understand who controls a building and what the record shows.

*The immediate beneficiaries are people whose work produces public accountability: journalists, tenant organizers, legal services organizations, policy analysts, and watchdog agencies. The ultimate beneficiaries are tenants and the public.*

### 2. Theory of Change

Public records, structured as evidence and made queryable through principled reasoning, enable informed investigation. Informed investigation enables public accountability. Public accountability creates institutional and market pressure that improves housing outcomes.

*Watchline does not improve housing directly. It changes what people can know and demonstrate, which in turn changes the incentives faced by landlords, regulators, lenders, journalists, and elected officials.*

---

## II. What Watchline Is Not

### 3. Not a Court

Watchline does not make legal findings. It does not determine guilt, liability, or legal status. It presents evidence and the reasoning that connects evidence to claims; legal conclusions belong to courts and regulators.

### 4. Not an Editorial Voice

Watchline does not reach conclusions about the character, intent, or culpability of any person or organization. It produces structured, evidence-backed statements about what the record shows.

### 5. Not a Risk-Scoring Engine

Watchline does not produce numerical scores, ratings, or rankings intended to represent overall risk or trustworthiness. Such scores obscure the reasoning behind them and cannot be meaningfully challenged.

### 6. Not a Static Publication

Watchline is a living system. Its conclusions are generated from evidence, not manually authored. When underlying data changes, conclusions update automatically. This distinguishes it from journalism, where an article is fixed at publication.

---

## III. Governing Principles

### 7. Defensibility

Every claim Watchline produces must be defensible under adversarial scrutiny. The standard is the cross-examination test: for any output, the system must be able to answer the following questions. Why do you say that? Where did that come from? What rule produced it? Who defined that rule? What evidence would change it?

*If the system cannot answer those questions, it should not make the claim.*

### 8. Full Exposure of Justification

Watchline makes only those claims whose justification can be fully exposed to the user. Every conclusion must be traceable, through its chain of reasoning, to the primary source records that support it.

### 9. Distinction Between Observation, Inference, and Claim

Watchline distinguishes explicitly between three epistemic categories that must never be conflated in any output. An Observation is a row in a source dataset. An Inference is a conclusion derived from one or more observations by application of a defined rule. A Claim is a statement the system asserts about the world.

### 10. Interpretive Status Over Statistical Confidence

Uncertainty in Watchline's conclusions arises primarily from interpretation, not probability. The system represents this through Interpretive Status (Observed, Derived, Estimated, Inferred, Stipulated, Disputed) rather than floating-point confidence scores.

*Stipulated covers conclusions established by legal finding or official determination. Disputed covers conclusions where reasonable disagreement exists in the evidence.*

### 11. Rules as First-Class Objects

Every inference the system makes must be produced by a named, versioned, documented Rule. Rules are ontological objects, not code. Each Rule carries a name, a plain-language definition, a version number, an author, a source of authority, explicit thresholds, an effective date, and an explanation suitable for presentation to a user.

*This principle prevents the system from making claims it cannot explain. It also creates a clear process for challenging, updating, or retiring conclusions when rules change.*

### 12. Reversibility

Because conclusions are generated from evidence rather than manually authored, they must update automatically when the underlying evidence changes. A corrected deed, a resolved violation, an improved entity-resolution algorithm, or a revised Rule should propagate through the system to affected conclusions.

### 13. Productive Disagreement

Watchline does not pretend to eliminate disagreement about complex ownership or enforcement questions. Instead it structures disagreement by exposing the observations, identity assertions, inference rules, and thresholds that produced a conclusion, so that disagreement can be located in the evidence rather than asserted against the system as a whole.

---

## IV. Governance

### 14. Charter Amendment

This Charter may be amended only by documented decision. Each amendment records the principle changed, the previous text, the new text, the author, the date, and the rationale. The amendment history is retained permanently.

*In the early stage of the project, a single designated author may make and document amendments. As the project grows, a more formal process should be defined.*

### 15. Rule Governance

Rules (Principle 11) are subject to the same versioning and documentation requirements as Charter amendments. A change to any Rule must record what changed, why, who authorized it, and what conclusions may be affected. Deprecated Rules are retained in the record; they are never deleted.

### 16. Scope of Jurisdiction

Each dataset integrated into Watchline carries a Jurisdiction attribute identifying the agency with legal standing to produce it and the legal authority under which it was produced. The system must preserve and surface this attribution. An HPD violation, an OATH judgment, a DOB complaint, and a DHCR registration are different legal acts and must not be treated as equivalent.

### 17. Deterministic AI Orchestration

The AI layer in Watchline is an orchestrator, not a reasoner. It translates user intent into structured queries, retrieves evidence from the knowledge graph, applies defined Rules, and presents results in plain language. It does not reason independently about what is true.

The AI orchestration layer must implement a deterministic pipeline. No branching or routing decision in the pipeline may be delegated to the language model's autonomous judgment. Every conditional transition must be justified by a defined Rule or Canonical Question in the ontology. The language model is called exactly twice in each pipeline execution: once to identify investigative intent, and once to present results. All reasoning between those two calls is governed by the ontology and the Rules, not by the model.

*This principle exists because autonomous AI reasoning cannot satisfy the cross-examination test (Principle 7) or the full exposure requirement (Principle 8). A conclusion produced by a language model's internal reasoning is not traceable to a defined rule, not reproducible across runs, and not inspectable by users or adversaries. Agentic behavior in the AI layer is therefore incompatible with Watchline's core commitments regardless of the AI framework used.*

---

## V. Amendment Log

| Version | Date | Principle | Change | Author | Rationale |
|---|---|---|---|---|---|
| 1.1 | 2026-06-26 | 17 (new) | Added Principle 17: Deterministic AI Orchestration | Watchline project team | Adoption of LangGraph as the AI orchestration framework made explicit constitutional constraints on agentic use necessary. LangGraph's design center is autonomous agent behavior; Principle 17 establishes that Watchline uses it as a deterministic pipeline framework only. |

---

*Version 1.1 -- June 2026.*

*This document should be read alongside the Watchline Ontology Specification and the Watchline Design Rationale.*
