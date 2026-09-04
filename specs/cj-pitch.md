# C+J Talk Pitch

Journalist-facing pitch for the Computation + Journalism Symposium — shorter and less
method-jargon than [`paper-abstract.md`](paper-abstract.md), because the room is data journalists
and computational-journalism researchers who already know and rely on JustFix's *Who Owns What*.

---

**Title:** Piercing the LLC Veil: Who Really Owns NYC's Buildings

**Format:** 15-minute talk + live demo of the conversational query tool (works as a talk or a
demo-session).

## Pitch (~235 words)

Reporters covering housing lean on JustFix's *Who Owns What* to turn one troubled building into a
landlord's full portfolio. It's indispensable — and for most landlords it works well. But it has a
structural blind spot on the sophisticated ones. WoW clusters buildings by shared registration —
name, address, managing agent — so a landlord who obscures all three slips through: buy buildings
together, then re-deed each into its own single-purpose LLC under a different registered agent, and
WoW sees unrelated buildings.

We'll show a system that (1) separates the three questions a single "portfolio" blurs — who
*operates* a building, who *manages* it, who *owns* it — into separately checkable layers, and (2)
resolves ownership with a ladder of signals ending in a name-free **veil-pierce**: ACRIS
co-conveyance deeds prove differently-named LLCs are one owner, even when the owner later split them
into separate shells.

A verified example: two rent-stabilized Queens apartment buildings, bought together on one 2018
deed, then moved into "BBGT Property LLC" and "Cherry 168 LLC." WoW places them in *separate*
portfolios — a reporter pulling one would never find the other. Our deed layer reunites them. On the
live graph the layers measurably disagree: **479** portfolios hide more than one owner; **157**
owners cross portfolios.

Honest scope: WoW already handles landlords who register consistently; the veil-pierce reaches the
hidden minority it can't. Everything is framed as **investigative leads, not legal determinations** —
the distinction reporters live and die by. We'll demo the tool live and discuss an evaluation, built
toward a collaboration with JustFix, for measuring what the layered graph adds.

## What the audience leaves with

- A concrete way to separate *operator / manager / owner* in public housing records — and why
  conflating them misleads a story.
- The deed **veil-pierce** with linked-successor recovery: catching the owner who restructured into
  per-building shells to hide, exactly where name-matching can't.
- A **verified before/after** reporters can re-check on WoW themselves: two Queens buildings WoW
  splits, the deed layer unifies.
- An honest **reliability model** (leads vs. verdicts) for accountability work with real libel
  exposure — including honest scope: a specialist signal, not a wholesale win over WoW.

---

**Notes for the submitter.**
- JustFix collaboration is framed as aspirational ("toward a collaboration") — keep it that way
  unless something is confirmed; they may be in the room.
- Divergence counts (479 / 157) and the Queens example are from the rebuilt `entity-linking-prototype`
  snapshot; the example was verified against WoW's *live* site (both buildings still resolve to
  separate portfolios there) — spot-check again before submitting, as WoW's data updates.
- Companion materials: [`paper-abstract.md`](paper-abstract.md) (fuller writeup),
  [`eval-protocol.md`](eval-protocol.md) (the evaluation referenced in the closing line),
  [`ownership-layer-decision.md`](ownership-layer-decision.md) (the design rationale).
