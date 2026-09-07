# Paper — Abstract & Contribution List (draft)

Draft spine for a systems/method writeup of the three-layer ownership pipeline. Faithful to the
working, rebuilt system as of this branch; the only placeholders are the formal WoW head-to-head
precision/recall numbers, pending the ground-truth eval in [`eval-protocol.md`](eval-protocol.md).
A worked example below is verified against WoW's live output. Submittable as a design/experience
paper today; archival once the eval numbers land.

A second, fully-worked flagship example — Ramon Escobar (recall *and* precision on one name, two WoW
splits by two different mechanisms, the edge-reliability ranking, and both live views) is in
[`case-escobar.md`](case-escobar.md).

Candidate venues: Computation + Journalism Symposium (C+J), NICAR (talk), ACM COMPASS (short
paper), FAccT (the reliability-class / "inference vs. determination" angle).

---

## Abstract

Public accountability for NYC housing rests on knowing who is behind a building. JustFix's *Who Owns
What* (WoW), the field standard, clusters buildings into landlord portfolios from shared HPD
registration contacts via name-and-address matching. A single "portfolio" conflates three facts of
different evidentiary weight — who *operates* a building, who *manages* it, and who *owns* it. We
decompose it into three purpose-built, independently verifiable layers — operational nexus, disclosed
management, and beneficial-owner identity — and resolve owner identity through a ladder of
complementary signals: probabilistic record linkage (Fellegi–Sunter), deterministic shared-entity
links, curated overrides, corporate co-owner feedback, and a name-free "veil-pierce" from ACRIS
co-conveyance deeds. The deed signal targets the case string-matching *cannot* reach — the
sophisticated shell game: an owner buys buildings together, then re-deeds each into its own
single-purpose LLC under a different registered officer, obscuring name, address, and officer at
once. We recover these with a **linked-successor guard** — a superseded joint deed still proves
co-ownership when its grantee is the *grantor* of each parcel's later single-purpose-LLC deed
(restructuring, not an arms-length sale). Precision is held by a latest-deed staleness rule, a
co-investor hub cap, aggregator-address masking, and co-op/condo exclusion. On the live graph the
layers are provably non-redundant: **479** portfolios hold more than one owner, **157** owners span
more than one portfolio, **1,461** managers cross portfolios. Worked, WoW-verified example: two
rent-stabilized Queens buildings co-bought in 2018, then split into `BBGT` / `CHERRY 168 LLC` — WoW
places them in separate portfolios; our deed guard unifies them. A formal head-to-head on adjudicated
ground truth is `[precision/recall pending]`. Throughout, a reliability-typed provenance model treats
every derived link as an investigative lead, not a legal determination.

*(~250 words. For a talk abstract — C+J / NICAR — drop the `[bracketed]` clause; the divergence
counts and the worked example carry it.)*

---

## Contributions

1. **A three-layer decomposition of "landlord portfolio"** into *operational nexus*, *disclosed
   management*, and *beneficial-owner identity* — each with a distinct reliability class — and a
   divergence measurement (**479 / 157 / 1,461**) showing the layers are non-redundant on real data.
   *(realized)*

2. **A multi-signal ownership-resolution ladder** composing probabilistic record linkage with
   deterministic same-entity links, curated overrides, and corporate co-owner feedback, with
   name-anchored blocking and first-name/common-name vetoes for full-population precision. *(realized)*

3. **A name-free deed veil-pierce with a linked-successor guard** (`CONNECTED_BY_DEED`). Co-conveyance
   proves shared ownership across differently-named LLCs; the **linked-successor guard** (grantor-chain
   restructuring signal) recovers the shell game's signature move — buy together, then re-deed each
   parcel into its own single-purpose LLC — which a plain latest-deed rule drops. A **specialist**
   signal by design: WoW already merges anything with a consistent name/address/officer; this reaches
   only the fully-obscured minority it cannot. Guarded by latest-deed staleness + a co-investor hub
   cap. WoW-verified on the Queens example above. *(realized)*

4. **Precision hygiene for the operational and ownership layers**: degree-based **aggregator-address
   masking** (management megaoffices mistaken for co-ownership) and **co-op/condo exclusion** (co-ops
   and condos are owned by shareholders/unit-owners, not a landlord, and their shared managing agent
   otherwise fabricates phantom "owners"). Both materially change the layers — e.g. a management
   signatory that resolves to a 231-building "owner" is 99% co-op/condo and correctly dropped.
   *(realized)*

5. **A reliability-typed provenance framework** ("leads, not verdicts") that labels each element as
   directly-sourced vs. inferred and attaches standardized caveats — an accountability/ethics
   contribution on not overstating algorithmic ownership determinations. *(realized)*

6. **A ground-truth evaluation protocol and released benchmark** for landlord beneficial-ownership
   resolution: stratified adjudication with an explicit evidence hierarchy, a circularity control, an
   INDETERMINATE class, and a paired head-to-head against WoW with a data-vintage control.
   *(protocol realized; benchmark + head-to-head numbers pending — see [`eval-protocol.md`](eval-protocol.md))*

---

**Status.** Contributions 1–5 are backed by the working, rebuilt system and one WoW-verified example;
contribution 6 is specified but not yet run. A submission today is a design/experience paper citing
the protocol; the archival version waits on the eval numbers. Keep the "leads, not verdicts" framing
and the honest scope on the deed signal (specialist, not a wholesale WoW-beater) — both are the
correct *and* the credible stance for reviewers and for JustFix. Ideal next step: run the minimal
eval, preferably with a JustFix co-adjudicator on the gold set.
