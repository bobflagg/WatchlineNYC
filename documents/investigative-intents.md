# Investigative Intents

Watchline is organized around a set of **investigative intents** — the core questions that journalists, tenant advocates, and enforcement agencies bring to housing accountability work. Each intent maps to a distinct query pattern against the knowledge graph and defines what a defensible, evidence-based answer looks like.

These intents are the product. The ontology, the pipeline, and the rules exist to serve them.

---

## Audience Key

| Symbol | Audience |
|--------|----------|
| **T** | Tenant / Tenant Advocate |
| **J** | Journalist |
| **E** | Enforcement Agency |

---

## The Intents

### 1. Portfolio Identification
**Who actually controls this building?**

Trace from a single address to the ownership network behind it, cutting through LLC layering to the probable beneficial controller. This is the foundational query that almost every other intent depends on.

`Audience: T · J · E`

---

### 2. Portfolio Condition Assessment
**How bad is this landlord's record across all their buildings?**

Aggregate violation severity, PHC flags, and open Class C counts across an entire inferred portfolio. A tenant cares about their building; a journalist or enforcement agency cares about the pattern.

`Audience: J · E`

---

### 3. Recidivism
**Has this landlord let hazardous conditions persist repeatedly, across multiple buildings and over time?**

Look for chronic PHC patterns — not just current open violations but historical ones that were slow to close or never resolved. Distinguishes a landlord who occasionally falls behind from one who systematically neglects tenants.

`Audience: J · E`

---

### 4. Worst-First Prioritization
**Which buildings or landlords should be investigated or inspected first?**

Rank actors or buildings by violation severity, persistence, and portfolio scale. Designed explicitly for enforcement agencies allocating limited inspection resources.

`Audience: E`

---

### 5. Concealment Detection
**Is someone using LLCs or name variations to obscure their identity across registrations?**

Look for actors who appear under multiple names or entities that resolve to the same beneficial controller, especially where the connection is visible only through shared addresses rather than shared names — a stronger signal of deliberate obscuration.

`Audience: J · E`

---

### 6. Deterioration Trajectory
**Is this building getting worse over time?**

Track whether violation counts are increasing, whether old violations are accumulating rather than being resolved, and whether court filings are escalating. A tenant uses this to understand their situation; an advocate uses it to build a case.

`Audience: T · J · E`

---

### 7. Enforcement Accountability
**Is HPD actually following up on violations at this building?**

Look for long-open violations that have not generated court action, or patterns of violations being marked closed without evidence of correction. This intent is about the agency, not the landlord — it can surface enforcement gaps and systemic failures.

`Audience: J · E`

---

### 8. Geographic Concentration
**Is there a cluster of troubled buildings in a particular neighborhood?**

Identify spatial patterns — blocks or zip codes with disproportionate PHC buildings — that may indicate systemic neglect or a specific bad actor operating in a defined area.

`Audience: J · E`

---

### 9. Ownership Change Monitoring
**Did conditions change after this building was sold?**

Compare violation trajectory before and after a change in HPD registration to assess whether new ownership improved or worsened conditions. Useful for identifying predatory acquisition patterns.

`Audience: J · E`

---

### 10. Building-Level Due Diligence
**What is the full record on this specific building?**

A comprehensive single-building report: violations by class and status, ownership history, court filings, and any active PHC claim. The most likely entry point for a tenant who has just found Watchline and needs to understand their situation.

`Audience: T · J`

---

### 11. Rent Stabilization
**Is this building losing rent-stabilized units, and how fast?**

Track changes in rent-stabilized unit counts over time to identify buildings where deregulation is accelerating. Useful for tenants at risk of displacement and journalists covering the broader loss of affordable housing stock across the city.

`Audience: T · J · E`

---

### 12. Fine Evasion
**Does this landlord have outstanding ECB fines, and are they paying them?**

Identify actors with large or growing unpaid OATH/ECB judgment balances — a signal that fines are being treated as a cost of doing business rather than a deterrent. Particularly relevant for enforcement agencies evaluating whether the current penalty structure is functioning as intended.

`Audience: J · E`

---

## Notes on Viability

An intent is viable only if two conditions are met: someone in the target audience genuinely needs to answer it, and the data and rules in the system can produce a defensible answer. These can come apart.

A few intents warrant particular attention:

- **Intent 7 (Enforcement Accountability)** is politically sensitive but potentially the most valuable to investigative journalists. It requires confidence in data completeness — if HPD's own records are incomplete, false negatives could be misleading.

- **Intent 9 (Ownership Change)** depends on the graph capturing historical registration snapshots rather than only current state. Data availability should be confirmed before this intent is formally supported.

- **Intent 11 (Rent Stabilization)** requires reliable time-series data on stabilized unit counts. The NYC DHCR registration data can support this but needs to be incorporated into the pipeline before this intent is formally supported.

- **Intent 12 (Fine Evasion)** depends on ECB outstanding balance data being current. Stale balance figures could produce false positives for landlords who have paid but whose records haven't been updated.

- **Intents 1 and 10** are the most important for early adoption. They are what a first-time user needs before they trust the system enough to engage with the more analytical intents.
