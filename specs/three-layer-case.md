# Decomposing "landlord portfolio": sourced records vs. analytical views — for critique (v2)

**Date:** 2026-09-07 · **Status:** proposal, revised after review · **Audience:** someone who knows
[JustFix / Who Owns What](https://www.justfix.org/en/) well.

All figures are from the live `wow` data / discovery graph as of the date above; re-check vintage
before relying on any number.

### What changed in v2 (after a round of review)

- **Reframed** around *typed, dated, sourced assertions* from which views are generated — clusters are
  views, not entities. This replaces "three coequal layers."
- **Corrected a factual error.** v1 said the ownership layer "only ever merges / never splits a WoW
  cluster." That was wrong — it described a *different* mechanism. The common-control view is built
  independently and **subdivides (479) and crosses (157)** WoW portfolios (§3).
- **Renamed** "operational nexus" → *registration-linked network* (a hypothesis, not an observed fact).
- **Management** reframed as a *sourced, dated* assertion (source confidence ≠ present truth).
- **Ownership** target narrowed to a *common-control hypothesis*, typed per mechanism.
- **Added:** time as a first-class dimension; harm controls in product behavior; the evaluation as a
  precondition, not a footnote.

## 1. The core claim (uncontested)

WoW's `portfolio` is a single cluster built from shared HPD registration contacts. It is read, by
different users, as three incompatible things — *who operates* a building, *who manages* it, *who owns*
it — that have different answers and different evidentiary weight. The fix is to separate **what
records state** from **what we infer**, and to type, date, and source every assertion.

## 2. The model: sourced records → analytical views

The primary objects are **typed, dated, sourced assertions**, not layers:

- **Registered owner / responsible party** (HPD) — dated, sourced.
- **Disclosed managing agent** (HPD, `MANAGED_BY`) — dated, sourced.
- **Deed / title holder** (ACRIS) — dated, sourced.
- **Officers, principals, business addresses** (HPD/ACRIS) — dated, sourced.

Two **analytical networks** are *derived* from those records (and are views, not real-world entities):

- **Registration-linked network** — WoW's portfolio: buildings tied by shared registration contacts. A
  reasonable *hypothesis* about a shared operation; not proof of one (shared filing services, law
  firms, managing offices, relatives, and stale registrations all create adjacency without unified
  control).
- **Possible common-control network** — an independent clustering across LLCs from deeds, shared
  registered entities, and shared principals. Its target is **common control**, explicitly *not*
  proven beneficial ownership or economic benefit.

So it is really **sourced records + two analytical views** — with disclosed management being a *sourced
relationship surfaced directly*, not an inference. That is the honest shape; "three coequal layers"
overstated it.

## 3. The common-control view crosses *and* subdivides WoW portfolios (the v1 correction)

The important structural point, and where v1 was wrong. The common-control view is **not** a merge-only
rollup of WoW's clusters. On the live graph:

- **479** WoW portfolios are **subdivided** — their landlords fall into ≥2 distinct common-control
  groups (the Orsid/Rosedale over-merge, corrected in the ownership *view*).
- **157** common-control groups **cross** WoW portfolios — spanning ≥2 (the Croman under-merge).

The registration cluster itself is left intact — it is a true fact about registration adjacency — while
the ownership *view* reassigns its buildings to their real owners. (That is "a split of the portfolio
in the ownership view," not an edit to the registration cluster.) A separate, monotone mechanism does
exist — the edges added to WoW's *registration* graph to improve portfolio recall only merge — but that
is the registration view's business, not the ownership view's, and v1 wrongly attributed it to the
latter.

## 4. Evidentiary weight: provenance is not present truth

Separating sourced from inferred is the point — but "sourced" means *faithfully reproduced from a
record*, which is a claim about **provenance, not current correctness**:

- A **disclosed managing agent** is strong evidence that a party *was listed as agent in registration X,
  effective date Y*. It is **not** evidence that the party currently manages the building, is reachable,
  has authority over a given problem, or covers every building in a cluster. Source confidence and
  real-world correctness are different axes; a perfectly-reproduced filing can be stale or wrong.
- A **common-control** link is an inference whose strength depends on **which mechanism** produced it
  (a co-conveyance deed, an exact shared registered entity, a shared principal, or a probabilistic
  match). Each link should name its mechanism and date, not collapse into one blended score.

## 5. Harm controls belong in product behavior, not caveats

A false merge harms even when every building was already in the base data: it can associate a person
with violations or harassment they had no part in, inflate a supposed owner's portfolio and violation
rate, misdirect tenant pressure, expose unrelated people who share a name or address, and contaminate
downstream rankings and aggregates. **Caveats do not travel** with names, charts, screenshots, or
exports. So the controls must be behavioral: inferred links are held out of exports, aggregate
statistics, rankings, and public profiles unless above a mechanism-specific confidence bar; the
mechanism and dates travel *with* the claim; conservative defaults everywhere.

## 6. Time is a first-class dimension

Registrations, agents, deeds, addresses, and principals change independently, so a system that ignores
time can connect facts that were never simultaneously true. Every displayed relationship should carry:
source, filing/effective date, retrieval date, supersession status, the building/entity it applies to,
and (for inferences) the mechanism. This is a real current gap, not just a display nicety — the deed
signal already uses a latest-deed staleness rule, but the model is not yet temporally typed end to end.

## 7. Default to the user's question, not one privileged cluster

There is no universally-primary view. A tenant asking "who is my landlord?" needs a small, action-
oriented set — responsible/registered party, currently-disclosed managing agent, title owner if
available, and the broader control network clearly secondary. A reporter often wants the control
network first; an advocate wants both. The interface should translate the *question* into the
underlying evidence, not make any one analytical view universally default.

## 8. What the numbers do and don't show (the evaluation is the validation)

The divergence counts — **479** portfolios subdivided, **157** groups crossing, **~67k** buildings with
a disclosed manager (**~28k** managers), the common-control view enriching **28%** of controlled
buildings — establish that the views *differ*. They do **not** establish that the differences match
ground truth, that users need them, or that false merges are acceptably rare; and "28% of buildings"
needs denominators (buildings vs. portfolios vs. owners vs. actual searches) before it means anything.
So the blind, preregistered evaluation ([`eval-protocol.md`](eval-protocol.md)) is **a precondition of
this case, not a supporting detail** — and it must report precision/recall **by mechanism**
(owner-name, address, deed, principal), cluster-size distributions, and error *severity*, not aggregate
accuracy. The Escobar example ([`case-escobar.md`](case-escobar.md)) is an illustration of both a recall
and a precision win, not evidence of rates.

## 9. Counterarguments still open (please push on these)

1. **Complexity vs. legibility.** Task-oriented views (§7) are the proposed answer to overhead, but do
   they genuinely reduce it, or just relocate it? My biggest open question.
2. **Inference overreach.** Typing, per-mechanism confidence, and behavioral harm controls (§4–§5) are
   the safeguards — but is surfacing an inferred controller *at all* a line WoW is right to hold?
3. **Is the minority worth it?** The common-control view meaningfully changes a minority of cases (the
   obscured shell games). I believe those are disproportionately important for accountability — but
   §8's evaluation, not this document, has to prove it.

## 10. What this is not

- **Not** a WoW replacement. The registration-linked network *is* WoW's contribution, kept; the
  additions are contributable back where they aren't Watchline-specific inference.
- **Not** a legal ownership claim. The target is a *common-control hypothesis* with cited mechanism,
  never a verdict.
- **Not** "clusters as facts." Every cluster is a view over dated, sourced assertions.

## 11. What I'm asking you to critique

- Is the **sourced-records / analytical-views** split (with management as a sourced relationship, not a
  layer) the right spine — or is even two analytical networks one too many?
- Are the **behavioral harm controls** (§5) and **temporal typing** (§6) sufficient to make an inferred
  common-control view safe to surface — and if not, what's missing?
- Given §8, what would a **critique-proof evaluation** of usefulness (not just divergence) have to
  show before this decomposition is worth its complexity?
