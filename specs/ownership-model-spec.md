# Ownership model & inference specification — for critique (v4)

*(Formerly `three-layer-case.md`; renamed when it grew from a decomposition argument into this
data-model + inference spec. History predating the rename is under the old name in git.)*

**Date:** 2026-09-07 · **Status:** proposal, revised after three rounds of review · **Audience:** someone
who knows [JustFix / Who Owns What](https://www.justfix.org/en/) well.

The decomposition (sourced records vs. analytical views) is accepted in review. v3's remaining flaw —
"no cross-mechanism semantic transitivity" is contradicted by a connected-components construction — is
**confirmed against the code**: [`owner_groups.py`](../watchline/discovery/ingest/portfolio/owner_groups.py)
builds the owner partition as a single union-find over the union of `CONNECTED_BY_SPLINK`
(Fellegi-Sunter + registered-llc + curated) **and** `CONNECTED_BY_DEED`. So this revision replaces the
informal pipeline description with a data-model + inference spec, and marks every element
**[implemented] / [proposed] / [open]**. Figures are from the live graph as of the date above.

### Changelog v4 (after review of v3)

- Confirmed and conceded the transitivity contradiction against the code; reframed around the reviewer's
  **three levels** (source claims → identity resolution → substantive relationships).
- **Corrected v3's mechanism table**: the owner layer uses **no name/address edges** (verified in code);
  shared-address/shared-name are *registration-network* signals, not common-control signals.
- Recast the empirical distribution as *observed topology*, not a risk bound.
- Added a **composition algebra** (§3), **projection/unit** rules (§5), a **visibility-and-propagation**
  matrix (§8), **eval decision rules** (§9), and an **implemented/proposed/open** ledger (§11).

## 1. Starting claim (contestable)

WoW's `portfolio` conflates *who operates / manages / owns* — claims of different kind and evidentiary
weight. Whether users actually read it three ways, and whether task-specific record presentation alone
would fix it, are open questions the evaluation (§9), not this document, must decide.

## 2. Data model: three levels [proposed], vs. what exists today [implemented]

**Today [implemented].** `OwnerGroup` = union-find (connected components) over
`CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED`, with pre-clustering edge vetoes (`cluster_gated`: first-name
disagreement; common-name + differing address), co-op/condo group exclusion, and `MAX_SIZE=300`
(unused — max observed component is 37). No name/address glue. **This is one unified clustering over
heterogeneous edges — the construction under review.**

**Target [proposed].** Separate three levels the current pipeline collapses:

1. **Source-reference claims** — *Record X names string/identifier S in role R w.r.t. B, dated.*
2. **Identity-resolution assertions** — *two references probably denote the same entity.* This is where
   `registered-llc` (exact legal entity), `curated` (human), and `fellegi-sunter` (probabilistic
   same-person) belong. Identity is transitive *within the resolved model* (with the existing vetoes).
3. **Typed substantive relationships between resolved entities** — e.g. `co-title` (from a deed),
   `common-principal`. These are **not** identity and are **not** freely transitive.

"Common control" is then a **conclusion from an explicit inference rule over compatible evidence**,
never a by-product of graph connectivity.

## 3. Composition algebra — what may chain [proposed]

- **Identity edges compose** (same-entity is transitive; vetoes already guard common-name bridges).
- **A substantive relationship does not compose with identity edges, or with another relationship, into
  "same owner."** A–(deed co-title)–B then B–(identity)–C yields at most "A co-titled with the entity
  also known as C," never "A = C" or "A controls C."
- **No cross-type chaining into a common-control conclusion.** Such a conclusion requires an explicit
  rule (e.g. co-title **+** single-purpose-successor **+** temporal overlap — the linked-successor gate),
  not connectivity.
- **Step 3 of the rollout exposes typed evidence *paths*, not unified groups** (§10).

Design options considered (and the one chosen): separate per-mechanism components / a restricted
composition algebra / a multiplex typed-path graph / "components are navigation aids only." **Chosen:
multiplex typed paths now; canonical groups only via an explicit admissibility rule, post-eval.**

## 4. Mechanism semantics, corrected [proposed]

The owner layer's mechanisms are the four below — **not** shared address or shared name (those build the
registration network). Each asserts a *different* proposition; some establish association or identity,
not control:

| Mechanism | Level | Asserts (precisely) | Toward *control* |
|---|---|---|---|
| `registered-llc` | identity | the *same legal entity* was reported in an ownership-bearing role (needs role **and** identity established) | strong |
| `curated` | identity | a human judged the references the same owner — **requires** standard, date, reviewer, scope | strong, but auditable, not axiomatic |
| `fellegi-sunter` | identity | two references *probably denote the same party* (probabilistic) | identity only, not a relationship |
| `acris-deed` (co-conveyance) | relationship | parties appeared together in a conveyance in roles — **not** necessarily equal co-title, continuing ownership, or control | signal only with the successor/restructuring + temporal gate |

The data may ultimately support **several typed relations** (co-title, common-principal, associated-via-conveyance)
rather than one "common control"; the evaluation should test whether collapsing them is valid at all.

## 5. Unit of clustering & projection [proposed; currently under-specified]

The current `Landlord` node conflates *party reference* and *resolved owner*. The target model states
explicitly: which nodes exist; which receive identity resolution (party references); which carry
substantive-relationship edges (resolved entities); how a **building** joins a group (party → `bbls`
projection); that a building **may belong to multiple groups** (joint ownership = multiple party
relationships, never a node merge); and that a projected building cluster must not discard the party/edge
structure that justifies it. *(This is the least-specified area today and a priority for the redesign.)*

## 6. Empirical topology — evidence, not a risk bound [implemented data]

6,540 groups; 78% pairs; ~98% ≤5; **max 37**; 90 groups (1.4%) span ≥3 surnames. This describes the
*observed topology under current thresholds/caps* — it does **not** prove risk is bounded (small
components may reflect sparse data or caps; two wrongly-joined pairs can be worse than one correct
20-node cluster; shared surnames neither cause nor exclude false bridges). The only bounded claim: a
single bridge's blast radius is capped by existing component sizes. **Risk is established by §9, not by
this distribution.** The 11–37 tail and the 90 heterogeneous groups are the cluster-level review target.

## 7. Temporal model [proposed; only latest-deed staleness implemented]

Four times: **valid** (true in the world), **record** (filed), **system** (ingested), **query** (now vs.
historical). Combination rules, stated safely: a later deed creates a **candidate successor state**
(depending on parties, roles, interests, doc type, lot coverage, chronology) — it does **not**
automatically terminate a prior title assertion; distinguish "no longer current under our rule" from
"terminated in the world." Principal-overlap supports common control **only if** the valid-time
intervals are reliable; where filings are snapshots, carry-forward is a *named assumption with its own
confidence*, not a fact.

## 8. Safety: visibility **and** propagation [proposed]

Governing principle: **confidence governs whether a link is *shown*; consequence governs what may be
*done* with it — including computational propagation.** A link hidden from users but used in group
statistics can harm more than a visible one, so the matrix governs both. Consequence tiers, each with its
own admissibility bar: stored → returned in search → shown on a detail page → used to expand a network →
used as a bridge in group construction → used to transfer allegations/statistics → exported → search-indexed
→ exposed via API. Committed controls: visible **evidence-path** view; **no violation/harassment
attribution across inferred links by default**; publication bar strictly above the research bar (maps to
the `public`/`vetted` trust axis); cluster-size & bridge-edge risk checks + human review for high-impact
public claims; correction/appeal with propagation to caches and exports; versioned reproducible
snapshots; **living individuals handled more conservatively than entities**; monitoring of false-positive
complaints and downstream reuse.

## 9. Evaluation decision rules [proposed]

> These rules now **live in** [`eval-protocol.md`](eval-protocol.md) §8 (preregistered decision rules)
> and §9 (cluster-level validity & ablation) — the single operational source. The summary below is the
> rationale; edit the protocol, not this section, when the rules change.

Measurement categories (record/linkage validity by mechanism on adversarial strata; cluster validity —
false-merge/split, purity/completeness, bridge failures, by size, robustness to edge removal, direct vs.
transitive; user usefulness via the WoW / sourced / +registration / +both **ablation**; harm/calibration)
are necessary but not sufficient. **Preregister the decision rules**: primary metrics; minimum precision
**by consequence tier**; maximum tolerable *severe* false-attribution rate; `INDETERMINATE` handling in
headline numbers; sampling weights/population estimates; minimum reviewer agreement; whether adjudicators
see mechanism; the independent ground-truth definition; stopping/rollback criteria; per-stage thresholds.
State the **feasible recall proxy** (curated-benchmark recall, discovery yield among known cases, or
estimated missed-link rate from sampled disconnected pairs) — full recall is undefined for unknown
common-control. Aggregate precision is inadequate for public attribution: weight by consequence and by
whether errors implicate living people or bridge large groups.

## 10. Staged rollout [proposed]

1. Typed, temporal **source assertions**.
2. **Registration-linked view** with explicit derivation rules (also evaluated, §3/§9 — it too is a
   construction, not a fact).
3. **Common-control evidence *paths*** for research use (vetted) — typed paths, **no** unified groups,
   rankings, or propagated attributes.
4. **Validate** usefulness (ablation) and cluster-level harm.
5. Only then decide whether the evidence justifies **publicly named** common-control groups, via an
   explicit admissibility model — not connectivity.

A formal cluster-confidence model is **not** required before step 3 *if* step 3 exposes only typed paths;
it **is** required (or a stricter admissibility model) before any canonical named group.

## 11. Implemented / proposed / open

- **Implemented:** the `OwnerGroup` union-find + edge vetoes; deed staleness / hub-cap / linked-successor
  gates; co-op/condo exclusion; `MANAGED_BY` management layer; the registration `Portfolio`.
- **Proposed (this doc):** the three-level split; identity-resolution beneath the relationship graph; the
  composition algebra; typed evidence paths; the temporal combination rules; the visibility-and-propagation
  matrix; the eval decision rules.
- **Open research:** a cluster-confidence model; the admissibility rule for named groups; the
  party/building projection & joint-ownership representation; the choice of recall proxy; whether "common
  control" should be one relation or several typed relations.

## 12. What this is not / questions for the reviewer

- **Not** a WoW replacement, a legal ownership claim, or "clusters as facts."
- Questions: Is the **multiplex-typed-paths-now, named-groups-only-post-admissibility** choice (§3/§10) the
  right resolution of the transitivity problem? Is the identity/relationship split (§2) sufficient, or must
  `fellegi-sunter` identity resolution be fully materialized as resolved-entity nodes *before* any
  relationship graph is built? And is a consequence-tiered admissibility model (§8) a credible substitute
  for a formal cluster-confidence model at step 3?
