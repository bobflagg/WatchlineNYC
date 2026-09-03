# Paper — Abstract & Contribution List (draft)

Draft spine for a systems/method writeup of the three-layer ownership pipeline. Faithful to the
working system as of this branch, except the formal WoW head-to-head numbers, left as `[…]`
placeholders to fill once the ground-truth eval in [`eval-protocol.md`](eval-protocol.md) runs.
Submittable as a design/experience paper today; archival once contribution 6 is measured.

Candidate venues: Computation + Journalism Symposium (C+J), NICAR (talk), ACM COMPASS (short
paper), FAccT (the reliability-class / "inference vs. determination" angle).

---

## Abstract

Public accountability for NYC housing rests on knowing who is behind a building. JustFix's *Who
Owns What* (WoW), the field standard, clusters buildings into landlord portfolios from shared HPD
registration contacts via name-and-address matching. But a single "portfolio" conflates three
distinct facts — who *operates* a building, who *manages* it, and who *owns* it — and
string-matching errs in both directions: it **over-merges** unrelated owners who share a management
office, and **under-merges** one owner's differently-named shell LLCs. We present a system that
decomposes the portfolio into three purpose-built, independently verifiable layers — operational
nexus, disclosed management, and beneficial-owner identity — and resolves owner identity through a
ladder of complementary signals: probabilistic record linkage (Fellegi–Sunter), deterministic
shared-entity links, curated overrides, corporate co-owner feedback, and a name-free "veil-pierce"
derived from ACRIS multi-parcel co-conveyance deeds, guarded by a latest-deed staleness rule and a
co-investor hub cap. We add precision-safe aggregator masking that neutralizes management-megaoffice
addresses mistaken for shared ownership. On the live graph the layers are provably non-redundant:
**508** portfolios contain more than one owner, **103** owners span more than one portfolio, and
**1,461** managers cross portfolios — distinctions a single layer cannot express. Against WoW on
adjudicated ground truth, the approach corrects both error directions `[precision X vs. Y;
split-precision …; McNemar p = …]`, illustrated by de-aggregating a 216-owner management megaoffice
and unifying a validated operator split across two portfolios. Throughout, a reliability-typed
provenance model treats every derived link as an investigative lead, not a legal determination. We
release `[the adjudicated benchmark and]` the layered model and evaluation protocol.

*(~230 words. For a talk abstract — C+J / NICAR — drop the `[bracketed]` eval clause and the
release sentence; the divergence counts and the two cases carry it.)*

---

## Contributions

1. **A three-layer decomposition of "landlord portfolio"** into *operational nexus*, *disclosed
   management*, and *beneficial-owner identity* — each with a distinct reliability class — and a
   divergence measurement (508 / 103 / 1,461) demonstrating the layers are non-redundant on real
   data. *(realized)*

2. **A multi-signal ownership-resolution ladder** composing probabilistic record linkage with
   deterministic same-entity links, curated overrides, and corporate co-owner feedback, with
   name-anchored blocking and first-name/common-name vetoes for full-population precision.
   *(realized)*

3. **A name-free deed veil-pierce** (`CONNECTED_BY_DEED`): multi-parcel co-conveyance as evidence of
   shared ownership across differently-named LLCs — the one signal that pierces the shell game —
   with a **latest-deed staleness guard** (co-ownership counts only while the shared deed is a
   building's most recent conveyance) and a **hub cap** on serial co-investors. Both guards are
   transferable beyond this domain. *(realized)*

4. **Precision-safe aggregator masking**: degree-based detection of management-megaoffice addresses,
   masked on either endpoint, that string-matching mistakes for co-ownership — the mechanism behind
   the de-aggregation results. *(realized)*

5. **A reliability-typed provenance framework** ("leads, not verdicts") that labels each element as
   directly-sourced vs. inferred and attaches standardized caveats — an accountability/ethics
   contribution on not overstating algorithmic ownership determinations. *(realized)*

6. **A ground-truth evaluation protocol and released benchmark** for landlord beneficial-ownership
   resolution: stratified adjudication with an explicit evidence hierarchy, a circularity control,
   an INDETERMINATE class, and a paired head-to-head against WoW with a data-vintage control.
   *(protocol realized; benchmark + head-to-head numbers pending — see [`eval-protocol.md`](eval-protocol.md))*

---

**Status.** Contributions 1–5 are fully backed by the working system; contribution 6 is specified
but not yet run. A submission today is a design/experience paper citing the protocol; the archival
version waits on the eval numbers. Keep the "leads, not verdicts" framing — it is both the correct
ethical stance and the credible one for reviewers and for JustFix. Ideal next step: run the minimal
eval, preferably with a JustFix co-adjudicator on the gold set.
