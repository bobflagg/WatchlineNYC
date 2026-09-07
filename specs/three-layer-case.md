# Decomposing "landlord portfolio": a typed-assertion model and a staged common-control view — for critique (v3)

**Date:** 2026-09-07 · **Status:** proposal, revised after two rounds of review · **Audience:** someone
who knows [JustFix / Who Owns What](https://www.justfix.org/en/) well.

The decomposition spine (sourced records vs. analytical views) is now accepted in review. This revision
concentrates, per that review, on **specifying** the model — assertion semantics, the graph-to-cluster
procedure, temporal rules, controls on transitive inference, consequence-sensitive publication, and the
evaluation — rather than re-defending the decomposition. All figures are from the live `wow` data /
discovery graph as of the date above; re-check vintage before relying on any number.

### Changelog v3 (after review of v2)

- Corrected "reassigns to their **real owners**" → *associates into separately inferred common-control
  groups*; terminology is consistently **possible common-control view**, never "ownership view."
- Added **§4 edges→clusters** (the crux): the graph-to-cluster procedure, the live cluster
  distribution, and the rule that **membership ≠ a pairwise control claim**.
- Added **§5 per-mechanism semantics** (association vs. control), **§6 temporal reasoning**, **§7 an
  operational safety policy**, and a **§9 staged rollout** that defers *publicly named* groups.
- Reified sourced records as dated claims (§2); applied **symmetric scrutiny** to the registration
  network (§3) — its connected component is also an analytical construction, not a "true fact."
- Renamed "uncontested" → **Starting claim** (§1).

## 1. Starting claim (contestable)

WoW's `portfolio` is a single cluster read, by different users, as *who operates / manages / owns* a
building — claims of different kinds and evidentiary weight. Contestable premises a critic may dispute:
whether ordinary users really read it all three ways; whether that is induced by the interface or
imported by users; and whether task-specific presentation of the source records alone would resolve it
without a second network. The evaluation (§8) is meant to decide these, not this document.

## 2. Sourced records as reified, dated claims

The primary objects are **claims**, not roles asserted as fact:

> Record *X* states that party *P* held role *R* with respect to building/entity *B*, effective *D*
> (recorded *D′*, ingested *D″*).

The source's **native role** is preserved (HPD "HeadOfficer," "Agent," ACRIS "grantee," …). Any
normalization — e.g. treating several HPD roles as "responsible party," or a grantee as "title holder"
— is a **documented transformation over claims**, never a relabeling that hides the source role. A
business address is an attribute *reported in a record*, not a durable property of the entity.

## 3. Two analytical views — both constructions, scrutinized symmetrically

Both networks are *derived views*, not real-world entities, and both depend on analytical choices
(which fields count, normalization, whether name+address must co-occur, transitive closure,
service-provider suppression, alias/typo handling):

- **Registration-linked network** (WoW's portfolio). Its *edges* are sourced/derived assertions; its
  *connected component* is an analytical construction — a hypothesis about a shared operation, not proof
  of one. (v2's "true fact about registration adjacency" over-protected it; retracted.)
- **Possible common-control network** — independently built from ownership-bearing mechanisms.

The evaluation (§8) assesses **both** networks, not only common control.

## 4. From edges to clusters — the crux

Edge-level confidence does **not** compose into cluster confidence, and heterogeneous edges must not
chain into one control claim. The procedure and its guards, stated explicitly:

**Procedure.** Per-mechanism edges → **precision vetoes** (`cluster_gated`: drop first-name-disagreement
edges; drop common-name edges whose normalized addresses differ) → **connected components at a
threshold** (owner groups; the registration view adds Louvain communities) → **size cap**
(`MAX_SIZE`), **deed-hub cap** (drop grantees on >20 deeds), **aggregator-address masking**.

**Live distribution (why the closure blow-up is bounded in practice).** 6,540 owner groups; **78% are
pairs**, ~98% ≤5 landlords, **max size 37**, and only **90 groups (1.4%)** span ≥3 distinct surnames.
So the transitive explosion a single bad bridge could cause is empirically rare — but the size-11-to-37
tail and those 90 heterogeneous groups are precisely the bridge risk, and are the **cluster-level
review target**.

**Commitments this forces:**

- **Membership ≠ a pairwise control claim.** Belonging to a group does not assert that every pair in it
  shares control.
- **No cross-mechanism semantic transitivity.** A–(deed)–B, B–(address)–C, C–(principal)–D does **not**
  license "A and D under common control."
- **Cluster confidence is derived**, not inherited from the strongest edge; large/heterogeneous groups
  and single-bridge structures are flagged and down-weighted or held for review.
- **Evidence paths are first-class** — a user can see *why* two buildings are grouped (the path and its
  mechanisms), not just the membership.
- **Conservative default:** expose an **evidence network with bounded path claims** ("possibly connected
  via this path"); reserve **named** common-control groups for stronger structures and post-evaluation
  (§9).

## 5. Per-mechanism semantics — what each edge actually asserts

"Common control" is not one relation; each mechanism asserts a different proposition, and some establish
only **association**:

| Mechanism | Asserts | Strength toward *control* |
|---|---|---|
| Exact shared registered entity (`registered-llc`) | same legal owner entity | strong |
| Co-conveyance deed (`acris-deed`, held) | co-title at the conveyance date | strong (with successor/restructuring gate) |
| Curated (human) | verified same owner | strongest (manual) |
| Shared principal | a common principal | moderate — needs temporal overlap (§6) |
| Probabilistic identity (`fellegi-sunter`) | same-person hypothesis | moderate/weak |
| Shared business address | association | **weak — often an aggregator, not control** |

The system may ultimately support **several typed relations** (co-title, common-principal, associated-via-address)
rather than one "common control" — the evaluation should test whether collapsing them is even valid.

## 6. Temporal reasoning, not just dated fields

Dates are necessary but insufficient; the system needs **combination rules** and a four-way time model:
**valid** (when true in the world), **record** (when filed), **system** (when ingested), **query**
(now vs. a historical period). Rules to specify: principal relationships must **overlap in time** to
support common control; a deed transfer **terminates** the prior title assertion; supersession is
field-scoped, not whole-filing; missing/conflicting effective dates are handled explicitly; permitted
lag between real-world change, recording, and ingestion is bounded. *Current state:* only a latest-deed
staleness rule exists; the rest is committed work, not yet built.

## 7. Operational safety policy (behavioral, not caveats)

Caveats do not travel with names, charts, screenshots, or exports, so controls live in product
behavior. Governing principle: **confidence governs whether a link is *shown*; consequence governs what
the product lets users *do* with it.** Committed controls:

- a visible **evidence-path** view for every inferred association;
- **no violation/harassment attribution across inferred links by default**;
- a **publication bar strictly higher** than the internal-research bar (maps onto the existing
  `public` vs `vetted` trust axis);
- **cluster-size and bridge-edge risk checks**; human review for high-impact public claims;
- a **correction/appeal** mechanism, with propagation to cached pages and exports;
- **versioned, reproducible snapshots** of every published decision;
- **living individuals treated more conservatively than entities**;
- monitoring of false-positive complaints and downstream reuse.

## 8. Evaluation — the validation (extends `eval-protocol.md`)

Divergence counts (479 subdivided / 157 crossing portfolios; ~67k managed buildings; common-control
enriching 28% of controlled buildings) show the views *differ*, not that they are *right or useful*.
The blind, preregistered evaluation is a **precondition**, and must test four separate things — and
report an **INDETERMINATE** class rather than forcing correct/incorrect:

1. **Record & linkage validity** — precision/recall **by mechanism**, on **adversarial strata** (common
   surnames, shared professional addresses, relatives, large managers, reused LLC addresses, high-degree
   nodes), not random sampling alone.
2. **Cluster validity** — false-merge/false-split, purity/completeness, bridge-edge failures, results
   **by cluster size**, robustness to removing one inferred edge, direct evidence vs. transitive
   membership.
3. **User usefulness** — task studies per audience, with an **ablation**: (a) WoW, (b) sourced records
   only, (c) + registration network, (d) + both — to isolate whether common-control adds value *beyond
   clearer source-record presentation*; plus caveat retention and how often users convert "possible
   association" into "owner."
4. **Harm & calibration** — displayed confidence vs. observed correctness; behavior of exports,
   snippets, screenshots; correction latency and residual propagation.

Launch criteria are set **separately** for private research, limited beta, and public attribution.

## 9. Staged rollout (adopted from review)

1. Build and expose **typed, temporal source assertions**.
2. Reconstruct the **registration-linked view** with explicit derivation rules.
3. Add **common-control evidence *paths*** for research use (vetted).
4. **Validate** task usefulness and cluster-level harm (§8).
5. Only then decide whether the evidence justifies **publicly named** common-control groups.

This separates the (weaker) case for storing and analyzing inferred connections from the (stronger)
case required to publish a cluster as a coherent named group.

## 10. What this is not / still open

- **Not** a WoW replacement, **not** a legal ownership claim, **not** "clusters as facts."
- Open questions for the reviewer: is even *two* analytical networks one too many for tenant-facing
  use? Are the §4 controls sufficient against bridge/heterogeneity errors, or is a formal
  cluster-confidence model required before step 3? Is per-mechanism typing (§5) enough, or must the
  single "common-control" relation be split into several typed relations before any grouping?
