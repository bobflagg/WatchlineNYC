# A case for decomposing "landlord portfolio" into three layers — for critique

**Date:** 2026-09-07 · **Status:** proposal, seeking critique · **Audience:** someone who knows
JustFix / Who Owns What well.

This is a proposal, not a verdict. I'd especially like you to attack §5 (the counter-arguments) and
tell me where this would mislead a tenant or a reporter. All figures are from the live `wow` data /
discovery graph as of the date above; re-check vintage before relying on any number.

## 1. The claim

WoW's `portfolio` is a single cluster built from shared HPD registration contacts (head-officer name
+ business address). It is asked to answer three questions that have **different answers and
different evidentiary weight**:

- **Operational nexus** — which buildings are run through one operation? *(what registration actually
  measures)*
- **Management** — who is the managing agent a tenant should contact? *(self-disclosed in HPD)*
- **Beneficial ownership** — who actually owns and profits? *(not directly recorded anywhere)*

The proposal is to keep the operational nexus (WoW's portfolio, essentially unchanged) and add two
purpose-built layers beside it: a **disclosed-management** layer and an **inferred-ownership** layer —
each independently verifiable and each carrying its own confidence level.

## 2. Why this isn't just relabeling

A single cluster built from *registration adjacency* is, by construction, **neither ownership nor
management cleanly** — and it fails in both directions at once:

- **Over-merges** where a shared *manager* routes different owners through one office (the Orsid /
  Rosedale shape): one portfolio, many owners.
- **Under-merges** where one owner spreads across differently-named LLCs / officers (the Croman
  shape): one owner, many portfolios.

These aren't edge cases invented for the argument; they're the two failure modes a registration graph
*must* have, because registration contact ≠ owner and ≠ (only) manager. A tenant reading a WoW
portfolio as "my landlord" and a reporter reading it as "who owns this" are each getting a partly-right
answer at a confidence the single label can't express.

## 3. Evidence the layers are non-redundant (not academic)

On the live graph the three layers genuinely disagree — if they collapsed back together, this wouldn't
happen:

- **479** portfolios contain **more than one** distinct owner (management/operational nexus ≠ ownership).
- **157** owners span **more than one** portfolio (ownership crosses the registration clusters).
- **1,461** managers operate **across** portfolios (management is its own axis).
- Management is real and large: **~67k** buildings carry a disclosed managing agent (**~28k** managers).
- The ownership layer is a **specialist rollup, not a land-grab**: it sits *above* the existing control
  signal, enriching **28%** of controlled buildings (the multi-LLC owners) and reaching **zero**
  buildings the base layer doesn't already cover. It only ever *merges*; it never splits a WoW cluster.

Worked example (verified against WoW's live output): the landlord name **"Ramon Escobar"** resolves to
two *different* real owners. For the Bronx one, WoW emits two portfolios (24 + 2 buildings) with the
*identical* landlord name and address, split by a one-character address typo (`GRAND CONCOURSE` vs
`GRAND COURSE`); we merge all 26. For the second (an Escobar/Espinal partnership), WoW again splits
(8 + 4) — this time because the same principals register under two business addresses; we merge all 12.
And we keep the two unrelated Escobars **apart**. Same name, two recall wins by two different failure
mechanisms, plus a precision win — see `case-escobar.md`.

## 4. The accountability argument (the real reason)

The layers have **different evidentiary weight**, and a single label forces one confidence onto facts
that don't share one:

- **Management is disclosed** (the landlord names its agent in an HPD filing) — high confidence, a
  directly-sourced fact.
- **Ownership is inferred** (from linkage across LLCs, deeds, shared principals) — a *lead*, not a
  legal determination.

Collapsing disclosed management and inferred ownership into one "portfolio" means either overstating
the inferred part or understating the disclosed part. Separating them lets the system say plainly
"this is disclosed" vs. "this is our inference — here's the evidence," which is the honest posture for
accountability infrastructure and the one least likely to get a tenant or reporter into trouble.

## 5. The strongest objections (please push on these)

1. **"Simplicity is a feature. One portfolio is legible; three layers is cognitive overhead for
   tenants."** — Fair. Counter: the *default* view can still be one answer (the operational nexus);
   the other two layers are progressive disclosure for the questions that need them. But is that
   real, or will three labels just confuse? This is my biggest uncertainty.
2. **"Ownership inference is exactly the overreach WoW deliberately avoids by staying at
   registration."** — The sharpest objection. Counter: we type every inferred link as a lead with
   attached caveats, the ownership layer only merges (never splits a safe WoW cluster), and it's a
   sparse specialist signal for the obscured minority. But "we labeled it a lead" is not a complete
   defense — where would a false merge still do harm?
3. **"Most buildings are singletons; the extra machinery serves a minority."** — True: the ownership
   rollup touches ~28% of controlled buildings. Is a minority of the hardest, most-obscured cases —
   the sophisticated shell games WoW *can't* reach — worth the added surface area? I think yes for
   accountability's core mission, but it's a judgment call.
4. **"Your divergence counts just reflect your own clustering choices, not ground truth."** — Partly
   fair, which is why there's a blind, preregistered human evaluation in progress (`eval-protocol.md`)
   with a paired head-to-head against WoW; the counts above are descriptive, not the validation.

## 6. What this is *not*

- **Not** a replacement for or competitor to WoW. The operational-nexus layer *is* WoW's contribution,
  kept; the additions are contributable back where they aren't Watchline-specific inference.
- **Not** a claim of legal ownership. Every inferred element is a lead with a caveat, never a verdict.
- **Not** a wholesale re-clustering. The ownership layer is additive (edges only merge) and specialist;
  it does not touch the 72% of controlled buildings that are singletons.

## 7. What I'm asking you to critique

- Is the three-question framing (§1) actually how tenants / advocates / reporters use WoW, or a
  distinction that matters more to us than to them?
- Is the disclosed (Type I) vs. inferred (Type II) split (§4) the right and sufficient way to keep the
  inference honest — or does surfacing an inferred owner at all cross a line WoW is right to hold?
- Given §5.3 (a 28% minority), is the added complexity worth it — and if so, is there a *simpler*
  decomposition that captures most of the value?
