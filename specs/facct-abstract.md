# FAccT / COMPASS Variant — Abstract, Contributions & Dual-Use Reflection

Scholarly variant of [`paper-abstract.md`](paper-abstract.md), reframed through the
fairness/accountability lens: beneficial-ownership resolution as a consequential algorithmic
determination about identifiable people, where the responsible move is to *type* the inference and
keep it contestable — not merely to be accurate. Primary target FAccT; COMPASS tuning noted below.

---

**Title:** Leads, Not Verdicts: Reliability-Typed Beneficial-Ownership Resolution for Housing Accountability

## Abstract (~240 words)

Housing-accountability infrastructure increasingly answers a consequential question about
identifiable parties: *who is behind a building?* We study this as an algorithmic-accountability
problem. The de facto standard — JustFix's *Who Owns What* — clusters buildings into landlord
portfolios from shared registration records via name-and-address matching. Two properties invite
revisiting it from a fairness standpoint. First, it collapses three claims of different evidentiary
weight — operation, management, and ownership — into one undifferentiated "portfolio," so an
*inference* about ownership is presented with the authority of a directly-sourced *fact*. Second,
its errors are asymmetric in their harms: a false merge over-attributes buildings to a party (a
wrongful-targeting/defamation risk), while a false split lets a real owner evade accountability (a
harm borne by tenants).

We present a system that (i) decomposes the portfolio into three separately-verifiable layers —
operational nexus, disclosed management, beneficial-owner identity — each carrying an explicit
reliability type (directly-sourced vs. inferred); (ii) resolves ownership through an auditable
ladder of signals, including a name-free "veil-pierce" from co-conveyance deeds — with a
linked-successor guard that reaches owners who restructured their buildings into per-building shells,
the case no name/address method can see; and (iii) attaches standardized caveats so every derived
claim reads as an investigative lead, not a legal determination — a transparency-and-contestability
mechanism, not a disclaimer. We treat the merge-vs-split (recall-vs-precision) tradeoff as an
explicit, documented design decision rather than a hidden threshold, and exclude structures the
resolution should not touch (co-ops/condos are owned by shareholders, not a landlord). On the live
NYC graph the layers measurably diverge (479 portfolios hide >1 owner; 157 owners cross portfolios). We contribute an evaluation protocol with an INDETERMINATE
class and a paired comparison to registration clustering that refuses to claim ownership the public
record cannot support, and reflect on the dual-use tension of infrastructure that names people —
arguing that typed provenance and contestability, not accuracy alone, are what make such systems
responsible.

## Contributions

1. **A reframing** of beneficial-ownership resolution as an algorithmic-accountability problem with
   *asymmetric, oppositely-distributed* harms: false merge → over-attribution/defamation; false
   split → accountability evasion borne by tenants.
2. **A reliability-typed provenance model** that makes each claim's epistemic status explicit and
   separates inference from directly-sourced fact — operationalizing "leads, not verdicts" as a
   transparency/contestability mechanism, not a disclaimer.
3. **The three-layer decomposition as accountability design** — holding operation, management, and
   ownership to distinct evidentiary standards instead of laundering an inference as a fact.
4. **An auditable, recall-biased resolution ladder with documented precision guards** — the
   merge/split tradeoff as an explicit design decision — including the name-free deed veil-pierce
   with its linked-successor guard, and precision hygiene (aggregator-address masking, co-op/condo
   exclusion) that removes management artifacts a naive ownership inference would mint.
5. **An evaluation methodology for accountability inference**: stratified adjudication with an
   INDETERMINATE class, a circularity control, a data-vintage control, and a paired head-to-head vs.
   registration clustering — honest about what public record can and cannot establish.
6. **A dual-use reflection** on public accountability infrastructure grounded entirely in
   already-public records: who it empowers, who it could harm, and why contestability is the
   safeguard (drafted below).

## Venue tuning

- **FAccT** (primary): lead with the harms-asymmetry and typed-provenance framing; foreground the
  dual-use reflection; frame the WoW comparison as *"making the inference explicit and
  contestable,"* never *"beating it."* Name the sociotechnical loop — journalists, advocates,
  agencies as the humans who act on the leads, keeping accountability with a person, not the graph.
- **COMPASS**: nudge toward *sustainable communities / tenant benefit and deployment*. Lead with the
  housing-justice stakes and that this is a **deployed conversational tool** advocates and reporters
  use; keep the systems + evaluation emphasis and trim the pure-ethics theory. `paper-abstract.md`
  is already ~80% of the COMPASS version — add a deployment/impact sentence and soften the
  FAccT-specific framing.

---

## Dual-Use and Contestability (reflection section — draft)

**The valence, and why it is reshaped rather than removed.** Most identification systems draw
scrutiny because they expose ordinary or vulnerable people to powerful actors. This system largely
runs the other way: it exposes actors who *deliberately* obscure ownership behind single-purpose
LLCs to the tenants, journalists, and regulators with a legitimate interest in reaching them.
Beneficial-ownership transparency is an established public good — the premise of the U.S. Corporate
Transparency Act, FATF anti-money-laundering norms, and a decade of ownership-transparency
journalism. The system also exists to correct a specific power asymmetry: owners can hide across
jurisdictions and shell entities, while the tenant harmed by a building cannot easily find who is
accountable for it. That asymmetry is the fairness argument *for* building the tool. But a
pro-accountability valence reshapes the risk; it does not dissolve it.

**Who can be harmed, concretely.** The sharpest harm is misidentification. A false merge attributes
buildings to a party who does not own them — reputational damage, misdirected enforcement,
harassment — and while the parties named are often powerful, the error does not fall on them
uniformly. A common-name collision or a management signatory (in our data, a registration officer
whose name a clustering method spread across hundreds of unrelated buildings) can pull in a
low-level employee or an unrelated namesake; the cost of misidentification lands hardest on the
*least* powerful person caught in the net. Two further harms follow from aggregation rather than any
single record: small landlords often list a **home address** as their business address, so an
ownership graph can surface a residence — a doxxing vector — and the **composite profile** (LLCs,
addresses, deeds, and a name linked into one object) carries exposure its individually-public
sources do not (the "mosaic effect"). Finally, the identification tooling is itself dual-use: the
same machinery could be repurposed against tenant-side actors or folded into discriminatory
screening. "Already public" is a necessary but insufficient defense.

**What the design does about it.** Four choices are load-bearing, and we distinguish what is
implemented from what is aspirational. (1) The system is grounded **entirely in already-public
record** and acquires no private data; it surfaces and organizes, it does not collect. (2) **Typed
provenance and "leads, not verdicts"** are implemented as first-class mechanisms: every inferred
element is labeled as inferred and carries a standardized caveat, and the system never emits a legal
determination of ownership or control — the primary structural guard against misidentification,
because it keeps a human adjudicator in the loop and marks each claim as challengeable. (3) The
**merge-vs-split tradeoff is documented, not hidden**, so downstream users can calibrate trust to
the error profile rather than to an implied certainty. (4) **Capability is governed**: the deepest,
open-ended investigative tier is gated behind a trust level and is not available to anonymous public
use, so the most powerful profiling is not a one-click public affordance. (5) **Structural exclusion
of management artifacts** directly attacks the misidentification vector above: co-op/condo buildings
(owned by shareholders/unit-owners, not a landlord) are excluded from the ownership layer and
co-op/condo-dominated groups are dropped, so a management company's registration signatory that would
otherwise resolve to a large phantom "owner" — in our data, a signatory who resolved to a 231-building
group that was 99% co-op/condo — is dropped rather than named. This is the safeguard working on the
exact harm we identified, not a hypothetical.

**The honest residual, and the thesis.** These safeguards are partial. We do not yet offer a formal
**contestation and redress channel** by which a named party can see the basis of an inference and
challenge it; the caveat framework signals contestability but does not operationalize it, and
closing that gap is the most important future work for responsible deployment. We do not specifically
mitigate **home-address exposure**, and the mosaic effect is only blunted, not answered, by public
grounding. We take the responsible-design answer to be neither *"do not build it"* — tenant access
to accountability is a real and unequally-distributed good, and ownership transparency is a
legally-endorsed public aim — nor *"accuracy resolves the ethics,"* since a highly accurate system
that presents inferences as verdicts is arguably *more* dangerous than a hedged one. The claim we
defend is narrower and, we think, more durable: for accountability infrastructure that names people,
**typed provenance, honest evaluation, capability governance, and — the standing gap — contestability
are what make the system responsible, not accuracy alone.**

---

*Divergence counts (479 / 157) and design details reflect the rebuilt `entity-linking-prototype`
snapshot (co-op/condo excluded; linked-successor deed guard applied). The capability-gating claim
refers to the trust-level control on the deep investigative tier; the contestation channel is future
work, stated as such.*
