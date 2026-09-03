# C+J Talk Pitch

Journalist-facing pitch for the Computation + Journalism Symposium — shorter and less
method-jargon than [`paper-abstract.md`](paper-abstract.md), because the room is data journalists
and computational-journalism researchers who already know and rely on JustFix's *Who Owns What*.

---

**Title:** Piercing the LLC Veil: Who Really Owns NYC's Buildings

**Format:** 15-minute talk + live demo of the conversational query tool (works as a talk or a
demo-session).

## Pitch (~230 words)

Reporters covering housing lean on JustFix's *Who Owns What* to turn one troubled building into a
landlord's full portfolio. It's indispensable — and it has a structural blind spot. It clusters
buildings by shared registration, so a single "portfolio" blurs three different questions — who
*operates* a building, who *manages* it, and who *owns* it — and its name-and-address matching
breaks in both directions at once. It fuses hundreds of unrelated owners who merely share a
management office, and it splits a single owner hiding behind differently-named LLCs.

We'll show a system that pulls those three questions into separate, separately-checkable layers, and
resolves ownership through a ladder of signals — probabilistic record linkage, shared-entity links,
and a name-free "veil-pierce" that uses ACRIS co-conveyance deeds to prove differently-named LLCs
are one owner.

Two real cases make the stakes concrete. It de-aggregates a **216-owner cluster** that was really
just clients of one management firm, FirstService Residential — owners a reporter might otherwise
chase as a single empire. And it reunites a genuine operator that the standard tool splits across
two portfolios. On the live NYC graph the layers measurably disagree: **508** portfolios hide more
than one owner; **103** owners cross portfolios.

Everything is framed as **investigative leads, not legal determinations** — the distinction
reporters live and die by. We'll demo the tool live and discuss an evaluation, built with JustFix,
for measuring when a layered ownership graph beats registration clustering.

## What the audience leaves with

- A concrete way to separate *operator / manager / owner* in public housing records — and why
  conflating them misleads a story.
- The deed **veil-pierce**: using co-conveyance to link shell LLCs by name-free evidence, not fuzzy
  name-matching.
- Two named, inspectable before/after corrections — one over-merge, one under-merge.
- An honest **reliability model** (leads vs. verdicts) built for accountability work with real libel
  exposure.

---

**Notes for the submitter.**
- The closing line names a JustFix collaboration as aspirational — if nothing is confirmed, soften
  to "toward a collaboration with JustFix" so you don't overstate in a room where they may be
  present.
- Divergence counts (508 / 103) are from the current `entity-linking-prototype` snapshot; refresh
  before submitting if the pipeline is rebuilt.
- Companion materials: [`paper-abstract.md`](paper-abstract.md) (fuller writeup),
  [`eval-protocol.md`](eval-protocol.md) (the evaluation referenced in the closing line),
  [`ownership-layer-decision.md`](ownership-layer-decision.md) (the design rationale).
