# NYC Housing Data Coalition meetup — deck

**11 slides + a live demo · ~15–20 min · present as work-in-progress / methods, NOT "we beat WoW."**

Independent sabbatical work (R. Flagg), building on JustFix's *Who Owns What* (WoW).
All 11 slides are locked. Every number below is grounded and reproducible — see the
**Grounding & sources** appendix at the end.

## The arc

**Setup → stakes → the stack → payoff → honest close.** Load-bearing slides: **3 (thesis),
5 (reliability), 10 (demo)**. Define the problem and stakes first (2–3) so every capability
after reads as an *answer*, not a feature; put the credibility anchors before the demo; close
on the responsible stance and the ask.

| # | Slide | The one job it does | Framing / safety |
|---|---|---|---|
| 1 | Title & who I am | Set an honest, modest tone | Credit WoW up front |
| 2 | One landlord, many masks | Make the shell game visceral | Croman — public, AG-documented |
| 3 | The provenance bar is higher when the output is a person | The thesis | The spine — anchors everything |
| 4 | The stack | One orientation map | Light; provenance runs its length |
| 5 | A data layer that knows what it knows | Credibility anchor #1 | Sourced vs inferred, structural |
| 6 | Precision-first owner resolution | The linkage + three honest numbers | No "beats WoW" claim |
| 7 | Not every "portfolio" is ownership | The design motivation | Inherent to address-linkage; fair to WoW |
| 8 | Three layers, not one | The architectural insight | Owner-identity validation in progress |
| 9 | Conversational — by design, not free-form | Set up the demo responsibly | Enforced in code, not a prompt |
| 10 | Live demo — Croman | The payoff | Pinned to a public landlord |
| 11 | Leads, not verdicts — and what's next | Responsible close + the ask | Restate the stance; invite collaboration |

---

## Slide 1 — Title & who I am

**On-slide:**

> # WatchlineNYC
> #### Making NYC landlord ownership visible — conversationally, with its uncertainty labeled
> *An independent sabbatical project, built on JustFix's* **Who Owns What**
> **Robert Flagg** — mathematician turned trustworthy-AI engineer
> *I make AI systems trustworthy by grounding them in knowledge graphs*

**Speaker note (~25s):**
> "I'm here as an independent — this is a sabbatical project, and it stands on JustFix's Who
> Owns What, which most of you know. My background is mathematics; these days I build
> trustworthy AI for a living, and the approach I work in is grounding models in knowledge
> graphs — so the system answers from a structured, sourced record instead of free-associating.
> This project is me pointing that at NYC housing ownership. I'm new to the housing-data world,
> and I'm here looking for feedback and help on the project."

**Framing:** The "grounding AI in knowledge graphs" line is the through-line the whole talk
elaborates (sets up 4, 5, 9) and pre-answers the room's "won't it hallucinate?" The spoken
closing seeds the slide-11 ask.

---

## Slide 2 — One landlord, many masks

**On-slide:**

> ## One landlord, many masks
> *[visual: a dense grid of LLC-name chips — "102 E 7TH ST LLC", "11 AVENUE B LLC", "124 RIDGE LLC", … — collapsing into one silhouette labeled **Steven Croman**]*
> **118 buildings. 107 different LLC names.** Almost one shell per building — each named for its own address, none of them "Croman."
> > A tenant can't find their real landlord. A journalist can't map the empire. An agency can't add up the violations.
> <sub>Source: Who Owns What's own "Steven Croman" portfolio (#87254); LLC names from NYC PLUTO owner-of-record. AG case: public record.</sub>

**Speaker note (~45s):**
> "NYC ownership is fragmented *by design*. Each building sits in its own single-purpose LLC,
> usually named after the address — so on paper there's no 'landlord,' just a scatter of shells.
> Take Steven Croman: a landlord the Attorney General investigated, who pleaded guilty and served
> jail time — about as public and documented as a bad actor gets. In Who Owns What's *own* Croman
> portfolio, those 118 buildings are held under 107 different corporate names — you can see it,
> they're just addresses with 'LLC' after them. Nothing in that list says 'Croman.' Tools like
> Who Owns What already re-assemble a lot of this — that's what I build on. But that's the problem
> in one picture: ownership is deliberately shattered into a hundred masks, and if it takes work to
> see it for a *famous* operator, the quiet ones are effectively invisible — to tenants, to
> reporters, to the agencies meant to hold them accountable."

**Framing / safety:** Croman is the *safe* choice because he's AG-adjudicated — we illustrate a
*data* problem, never a novel claim. The number is sourced entirely to WoW + PLUTO (no
dependence on our tool), so we credit WoW in the same breath without a strawman. Sets up slide 6
(we close that gap).

---

## Slide 3 — The provenance bar is higher when the output is a *person*

**On-slide:**

> ## The provenance bar is higher when the output is a *person*
> #### Why housing-ownership data raises the stakes for conversational tools
> *(build these three rows one at a time)*
>
> | When the answer is a **statistic** | When the answer is a **person** — *who controls this building* |
> |---|---|
> | ground truth is **published** — you look it up | ground truth is **deliberately hidden** (shell LLCs) — you must **infer** it |
> | a wrong answer is an **inaccuracy** | a wrong answer is a **false accusation** |
> | it's meant to **inform** | it's meant to be **acted on** — organizing, journalism, enforcement |
>
> > So *"reasonably incorrect"* isn't a tolerable failure mode.
> > Provenance, precision, and *"leads, not verdicts"* are **preconditions — not polish.**

**Speaker note (~50s):**
> "Hold onto those 107 masks, because they're the whole point here. There's a real difference
> between putting a conversational layer over *aggregate* data — statistics, indicators — and over
> *ownership* data. If a number's off by a decimal, you get a bad number: bounded, impersonal,
> easy to correct. Our unit isn't a statistic; it's a *person* — who really controls this building.
> And as we just saw, the ground truth isn't published — it's deliberately obscured behind those
> shell LLCs, so we can't look it up, we have to *infer* it. And the output isn't just meant to
> inform; it's meant to be *acted on*. Put those together and a wrong answer stops being an
> inaccuracy and becomes a *false accusation about a named individual*. So provenance and
> uncertainty-labeling aren't a polish layer here — they're the precondition for pointing an LLM at
> this data at all. That's why everything after this is built around three things: precision-first
> resolution that refuses to fuse two different people; a reliability tag and caveat on every
> inference; and a stance of *leads, not verdicts*."

**Line to land live:** *"If an ownership tool is wrong, you don't get a bad number — you get a
false accusation about a real person."*

**Framing / safety:** Claims are about the *domain* ("ground truth is deliberately hidden"),
never a named person. Don't let it read as dunking on statistical-data tools — "same craft,
higher stakes." This slide turns the next four into answers to a bar it sets.

---

## Slide 4 — The stack

**On-slide:**

> ## How it's built — one look
> #### Every stage is sourced, or explicitly labeled *inferred*
> *[four-box left→right pipeline:]*  **Knowledge graph** *(sourced facts from HPD · ACRIS · DOB · PLUTO)* → **Resolution** *(precision-first record linkage — who is one owner)* → **Three layers** *(management · operational nexus · owner identity)* → **Conversational agent** *(read-only · cites sources · labels certainty)* → *tenant · journalist · agency*
> <sub>Provenance runs the length of the pipeline — nothing downstream drops the label of what it came from. (slide 5)</sub>

**Speaker note (~35s):**
> "One map, then we go deep on the parts that matter. A single knowledge graph of buildings,
> people, and events, pulled from the public record. A resolution step that figures out which
> messy records are the *same* owner. On top of that, three separate layers — who *manages* a
> building, the operational nexus, and who actually *owns* it — kept distinct on purpose, which
> I'll come back to. And the whole thing is reachable through a conversational agent that only
> ever *reads* the graph and cites what it found. The one thing to carry forward: provenance runs
> the full length of this — every stage knows whether it's a sourced fact or an inference."

**Framing:** A map, not an argument — orientation only. "Kept distinct on purpose" plants slide 8.

---

## Slide 5 — A data layer that knows what it knows

**On-slide:**

> ## A data layer that knows what it knows
> #### Every element is tagged — directly **sourced**, or **inferred** — and every inference carries a caveat
> **"Who owns 17 Gay Street?"** — two answers, never blurred:
>
> | **Recorded owner** · SOURCED | **Apparent controller** · INFERRED |
> |---|---|
> | **"17 GAY LLC"** | **"Steven Croman"** |
> | straight from the deed & registration — a *fact* (but a shell that tells you nothing) | inferred from record linkage — *a lead to verify, not a determination* |
>
> The tool **always returns both, labeled** — and says so when they diverge.
> <sub>Real record: BBL 1005930008 · every derived element carries this tag in the graph itself.</sub>

**Speaker note (~50s):**
> "This is the piece I'd most want you to take away. Underneath is a knowledge graph — but the
> important part is that every element in it *knows what it is*: either a directly-sourced fact, or
> an inference — and if it's an inference, it carries a caveat, automatically, everywhere it's used.
> Ask 'who owns 17 Gay Street?' A naïve tool picks one answer. Ours returns *two* and refuses to
> blur them. The recorded owner is '17 Gay LLC' — a sourced fact, and also a shell that tells you
> nothing. The apparent controller is Steven Croman — but that's an *inference*, so it comes
> stamped: a lead to verify, not a legal determination. And when the two disagree, the tool says so
> rather than quietly choosing. This isn't slideware — it's a hard rule in the code: that question
> *always* returns both, labeled."

**Framing:** The caveat is *structural* (attached in the graph, not remembered by a prompt) — the
distinction a technical room will probe, and you win it. Reuses the slide-2 mask (17 GAY LLC).
Keep the taxonomy to two words on the slide (sourced / inferred).

---

## Slide 6 — Precision-first owner resolution

**On-slide:**

> ## Precision-first owner resolution
> #### Probabilistic record linkage that refuses to fuse two different people
> *Replaces exact/rule matching with probabilistic linkage + precision guards:*
> *common-name veto · aggregator-office & servicer-signer masks · co-op/condo exclusion*
>
> **① Precision ≈ 1.0** — 0 cross-surname merges on a 105-record hand-adjudicated gold set → *Croman's 107 LLC names resolve to one owner* · **resolver quality**
> **② Divergence — *not* accuracy** — on the **39,456 buildings both systems group**, they differ *both ways*: **~780** of our owner-groups unify buildings WoW splits · **~620** WoW portfolios split across ours · **scale of the difference**
> **③ The honest gap** — *which* differences are improvements? A blind head-to-head on ~530 pairs is **built, not yet run** · **the ask (→ slide 11)**
> <sub>No "beats WoW" claim: precision is measured; the head-to-head is not.</sub>

**Speaker note (~60s):**
> "Three numbers at three confidence levels — being clear about which is which is the whole ethos.
> One, precision: on a hand-labeled gold set, when it links two records as the same owner it's
> essentially never wrong — zero cross-surname merges. Croman's 107 LLC names collapse to one
> owner. Two — and I'm careful here — is *divergence, not accuracy*. On the ~39,000 buildings where
> both systems make a call, they disagree both directions: about 780 of my owner-groups pull
> together buildings WoW splits, and about 620 WoW portfolios split across mine. That's how far
> apart the two are, and which way — it is **not** a claim about who's right; there's no ground
> truth in that number. Which is number three: deciding who's right where we diverge needs a blind,
> adjudicated head-to-head. It's built — about 530 pairs — but I haven't run it. That's the honest
> gap, and it's the help I'll ask for at the end."

**Caveats to keep attached (say if pushed):**
- Divergence ≠ accuracy — 780/620 says the systems disagree, not who's right.
- Universe = buildings grouped in *both*; co-op/condo are dropped by our system, so the ~620
  splits are genuine partition differences, **not** co-op/condo artifacts.
- Both drivers of the split direction (correctly declining WoW's over-merges vs. our own recall
  loss) are real but unjudged — only adjudication tells them apart.

**Reproduce:** `uv run --extra ingest python -m watchline.discovery.ingest.portfolio.compare_kg --divergence`

**Sizing:** in a longer slot, split into "failure modes" → "the guards," with an Eric Moore
servicer-signer backup slide (institutional, not a private person — safe).

---

## Slide 7 — Not every "portfolio" is ownership

**On-slide:**

> ## Not every "portfolio" is ownership
> #### Shared-address linkage answers *"who operates through this office"* — not *"who owns this"*
> Linking landlords by shared business address is powerful — often it's the *only* thread through a shell operation. But it can't tell an **owner's** office from a **managing agent's**.
> **138 different owners register from one office at 770 Lexington Ave** *(453 buildings).*
> Read "same office" as "same owner" and you fuse them into one empire that doesn't exist.
> Same trap: **co-op & condo boards** — many unit owners, no single landlord.
> > The fix isn't to throw away the address signal — it's to stop asking it two questions at once. **→ three layers**
> <sub>Source: raw HPD registrations, 770 Lexington Ave. Inherent to address-linkage — WoW uses the signal deliberately and flags it on the site.</sub>

**Speaker note (~50s):**
> "One design decision I want to explain. Linking landlords by shared business address is powerful
> — often it's the only thread tying a shell operation together, and Who Owns What uses it
> deliberately and to good effect. But a shared address can't tell you whether it's the *owner's*
> office or a *managing agent's*. Here's the raw public record: 138 different owners register from a
> single office at 770 Lexington Avenue — 453 buildings. If your system reads 'same office' as 'same
> owner,' those 138 collapse into one empire that doesn't exist. Co-op and condo boards do it from
> the other direction — dozens of unit owners, no single landlord. None of this is a discovery —
> it's inherent to address linkage, and well understood. The question is what you *do* about it. And
> the answer isn't to throw away the address signal — it's valuable — it's to stop making one signal
> answer two different questions."

**Framing / safety:** Present as a well-understood property of the technique + your design
response, NOT as your discovery — WoW's matching has no aggregator cap; over-connection is
inherent and acknowledged. Credit the address signal. Don't pin a specific over-merged portfolio
on WoW's live output (unverified vs their size-splitting). 770 Lexington is an *office*, not a
person — accuses no one; the co-op/condo exclusion protects ordinary unit owners.

---

## Slide 8 — Three layers, not one

**On-slide:**

> ## Three layers, not one
> #### A single "portfolio" hides three different questions — so we ask them separately
>
> | The question | Layer | Signal | Reliability | Live scale |
> |---|---|---|---|---|
> | Who **manages** it? | management | self-disclosed HPD agent | mostly **sourced** | ~28,500 managers · ~67,000 buildings |
> | What network does it **run through**? | operational nexus | shared office / agent / shell *(WoW's strength)* | **inferred** | ~15,800 multi-building nexuses |
> | Who actually **owns** it? | owner identity | precision-first record linkage | **inferred** | ~6,500 owner-groups |
>
> > 770 Lexington's 138 owners share an **operational nexus** — real and useful. They are **not one owner.** Keeping the layers separate keeps the signal *without* the false empire.
> <sub>Owner-identity is inferred (Type II); its accuracy vs. WoW is not yet adjudicated → the blind eval (slide 11).</sub>

**Speaker note (~55s):**
> "The architectural idea. When you collapse everything into one 'portfolio,' you're answering
> three different questions at once — with different answers and different reliability. Who
> *manages* a building is mostly self-disclosed — close to a sourced fact. What operational
> *network* it runs through — the shared office, the agent, the shell web — that's WoW's real
> strength, an inference, deliberately recall-biased. And who actually *owns* it is a third
> question, answered precision-first and separately. Back to 770 Lexington: those 138 owners
> genuinely share an operational nexus — true and useful, and we keep it. But they are *not* one
> owner, and now nothing in the system says they are, because 'shares an office' and 'same owner'
> live in different layers. You don't trade the recall of address-linkage for the precision of
> ownership — you keep both, labeled. One honesty note: the owner-identity layer is running — about
> 6,500 groups — but whether it's *more accurate* than WoW where they disagree is exactly what I
> haven't adjudicated yet."

**Framing:** Resolves slide 7 (770 Lex gets *placed*, not just named). Each layer wears its own
provenance. The honest hedge ("I believe in this design; validation is ahead") hands to slide 11.
The 6,500 matches slide 6's divergence — internal consistency.

---

## Slide 9 — Conversational — by design, not free-form

**On-slide:**

> ## Conversational — by design, not free-form
> #### The agent **orchestrates queries**; it doesn't reason about people
> Four guarantees, enforced in code — not asked of the model:
> - **Asks the graph, doesn't answer from itself** — plain English → *parameterized, read-only* queries. Writes/admin refused, even for the deep-investigation tier.
> - **Reports only what a query returned** — no free-form claims; every inferred element carries its caveat (slide 5), automatically.
> - **"Who owns this?" returns both** — recorded owner *and* apparent controller, labeled — and flags disagreement.
> - **Capability is gated structurally** — deep investigation only for *vetted* users; persona (tenant / journalist / agency) sets **tone, never access**; fail-closed.
> > This is the answer to slide 3: you can't manufacture false certainty about a person if you only ever report what a *sourced, labeled query* returned.
> <sub>Gating lives in the tool-visibility layer, not a prompt — because the records themselves (raw violation text, ACRIS JSON) are a prompt-injection surface.</sub>

**Speaker note (~55s):**
> "Before I show you this live, I want to be precise about what it is and isn't. The agent is an
> *orchestrator, not a reasoner*. It takes your plain-English question and turns it into a
> parameterized, read-only query — it does not free-associate an answer. It can only *read*; writes
> and admin are refused at a guard, even for the deep mode. It reports only what a query returned,
> and every inferred element comes back with its caveat attached. And the capability gating is
> structural: the deeper investigation is unlocked only for vetted users — a self-declared
> 'journalist' doesn't get it; persona only shapes tone. Crucially, that's enforced in the code
> that decides which tools the model can even *see* — not by instructing the model in a prompt —
> because the records themselves contain free text, and that's a place an adversary could try to
> smuggle instructions. You don't defend that with a polite system prompt. Orchestrator, not
> reasoner. Now let me show you."

**Framing:** "Enforced in code, not asked of the model" is the line to land — it separates you
from every "we told the LLM to be careful" demo. Arms the demo: tells them what to watch for.

---

## Slide 10 — Live demo (Croman) *(all beats agent-verified)*

**On-slide (minimal — the app is the slide):**

> ## Live: ask it about Steven Croman
> #### Watch it label every layer — sourced vs inferred — and refuse to overclaim

**The demo — three questions, each backed by a verified tool chain:**

**① "Who owns 17 Gay Street?"** → *confirms Slides 5, 6 & 8 in one answer.*
`lookup_building_ownership` → three labeled layers, one call: recorded owner `17 GAY LLC`
(sourced) · apparent controller `Steven Croman` (inferred, "differs") · unified owner
`owner group OG-105462 — 12 fragments, 127 buildings` (inferred, "a lead, not title").
*Say:* "One question — the LLC, the person, *and* the 127-building owner those shells roll up into,
each labeled by how much to trust it."

**② "And who manages it — is that the same as who owns it?"** → *confirms Slides 7 & 8.*
`building_manager` + `lookup_building_ownership` → **Centennial Properties NY (114 buildings)**,
explicitly *"a manager is not an owner."*
*Say:* "Different question, different layer. It won't confuse 'runs the building' with 'owns the
building' — the trap that turns a management office into a fake empire."

**③ "So can I report that Croman legally owns all 127 of those buildings?"** → *confirms Slides 3 & 9.*
→ Declines: recorded-owner vs apparent-controller, *"not a legal determination… only a title search
or court finding could support that."*
*Say:* "That's the whole ethos, live. It turns an inference into a lead, never an accusation." →
*(hands into Slide 11.)*

**Sizing:** ① and ② collapse into one question — *"Who owns and who manages 17 Gay Street?"* (the
agent handles both and contrasts them, verified). Merge if tight; split for two "watch it work"
moments.

**Fallback (live demos fail):** pre-recorded 60–90s capture + static screenshots as hidden backup
slides. Data backup (all verified): `17 GAY LLC` → BBL `1005930008` → Croman → owner group
**OG-105462, 12 fragments, 127 buildings**; manager **Centennial Properties NY, 114 buildings**.

**Safety:** pinned to Croman (public, AG-adjudicated); demo the *discipline*, not a discovery. If
the agent surfaces anything about a **private individual**, don't dwell — steer back to Croman.

**Prep (dry-run ≥1 day before):** app up (`make ui-start`), Neo4j + current graph, `ANTHROPIC_API_KEY`
set, `WATCHLINE_MODEL` on Opus, **trust=vetted**. Q1/Q2 need address→BBL (Geosupport); if the
sidecar's down, ask by BBL (`1005930008`) or landlord name. All three beats are agent-verified as
of this build — the dry-run confirms *your* environment.

---

## Slide 10b — The payoff, mapped (Croman)

*The demo's payoff as a real rendered map, right after the live demo.*

**On-slide:** `docs/meetup/croman-map.png` — Croman's **127 buildings across Manhattan**, resolved
by WatchlineNYC into **one owner**, under "Croman — 127 buildings, one owner." Caption: *WatchlineNYC
unifies all 127 into one owner. Who Owns What splits 9 off into 5 fragments on address typos —*
`4 WEST 51` *vs* `424 WEST 51`*. That one-character typo is the whole shell game, in a legend.*

**Speaker note:** 127 buildings, all one owner in WatchlineNYC. WoW mostly agrees — 118 sit in one
portfolio — but the legend shows it splitting nine off into five "portfolios," and the reason is
right there: "4 West 51 Street" vs "424 West 51 Street." Same office, one missing digit, and the
record fractures the owner. A modest gap for Croman (WoW gets most of him) — which is the honest
point: the *dramatic* divergence is the other direction, where WoW over-merges (the Miller backup).
Here it's a clean small win, and a good picture of what "de-fragmenting an owner" means.

**Why it's here:** puts a real rendered artifact in the *main* flow (not just the backup), and makes
the demo's payoff visual. Uses the owner-identity number (127) to match the live demo exactly.
Generated by `portfolio_map.py --owner-group OG-105462`; the live HTML toggles WatchlineNYC↔WoW.

---

## Slide 11 — Leads, not verdicts — and what's next

**On-slide:**

> ## Leads, not verdicts — and what's next
> #### Inference to point an investigator at a question — never a determination about a person
> **The stance** *(you just saw it refuse):* every output is a **lead for a human to verify**, never a legal claim of ownership.
> **What's honestly *not* done yet:**
> - The blind head-to-head **accuracy** eval is **built, not run** — ~530 pairs need adjudication.
> - Owner-identity is validated for **precision** (gold set), not yet for **recall / who's-right-vs-WoW**.
> - It's a **sabbatical prototype**, not a shared service.
> **What I'm asking this room for:**
> - **Help run the blind eval** — ground-truth data, adjudication time, or methodology.
> - Some of this may belong **upstream in Who Owns What** — the precision-first linkage, the servicer-signer / aggregator filters.
> - **Feedback on the three-layer model** — is separating *manages / operates-through / owns* the right cut?
> **Thank you — and I'd love to talk.** *(Q&A)*

**Speaker note (~55s):**
> "Let me close where I started. Everything you've seen produces *leads*, not verdicts — a pointer
> to a question a human should investigate, never a claim that a named person owns something. You
> watched it refuse to cross that line a minute ago; that refusal is the most important feature in
> the system. And let me be straight about what I *haven't* done. I can show you the resolver is
> precise on a labeled set, and that it groups differently from Who Owns What at scale — but I have
> *not* run the blind, adjudicated head-to-head that tells you *who's right* where we disagree. It's
> built; it needs ground truth and hands. This isn't a service you can use yet; it's a sabbatical
> project. So the reason I'm really here: I'd love your help. If any of you have ground-truth
> ownership data, or would adjudicate a sample, that eval becomes real. Some of this — the
> precision-first linkage, the out-of-state servicer-signer filter — probably belongs back in Who
> Owns What, and I'd like to talk about that. And I'd value your read on the three-layer idea. I'm
> new to this world, the tool is the contribution, and I'm hoping to build the next part of it
> *with* people in this room. Thank you."

**Framing:** The demo earned this — "leads not verdicts" reads as demonstrated, not disclaimed.
Every honest limit is reframed as a concrete ask. Closes the slide-1 loop (humility → specific
ask). If Q&A time is short, lead with the eval ask.

---

## Backup slide — Abraham Miller (divergence runs both ways)

*After slide 11; shown only if a question calls for it — the answer to "doesn't your system
just merge everything?"*

**On-slide:** the rendered comparison map (`docs/meetup/miller-map.png`) — WoW portfolio #183's
27 buildings across three boroughs, colored by WatchlineNYC's **7 owner groups**, two singletons
flagged "unmerged" — under the heading **"One WoW portfolio → seven owners."** Caption: *WoW calls
these 27 buildings one owner; they're ~10 owners sharing one Lakewood office (not a registered
agent). WatchlineNYC resolves 7 — fixing typos, honestly missing one (OBTFELD). The answer to
"doesn't it just merge everything?" — here it does the opposite.*

**Speaker note:** WoW's portfolio #183 labels 27 buildings as one owner (Nathan Obstfeld); they're
actually seven owners tied only by a shared Lakewood office at 235 River Ave — which I checked is
*not* a registered agent, just a shared address ~10 small landlords self-file from. WatchlineNYC
splits them correctly, fixes the misspellings (Abraham vs Abaraham Miller), and — honestly — misses
one (OBTFELD, a one-letter typo of OBSTFELD). Showing the miss is the point: precision-first, not
magic, and divergence runs both ways.

**Why it's here:** the first *real rendered output* in the deck (not a mockup) — concrete, credible
evidence, and the clean rebuttal to the over-merge objection. Full write-up: `specs/case-miller.md`.
Regenerate the map with `portfolio_map.py --wow-portfolio 183` (see that case study's "Show it").

---

## Sizing & flex

- **Tight on time:** cut slide 4 (the map) and fold slide 8 into one line on 7 — lose ~3 min
  without losing the argument. The demo (10) is the one thing never to cut; within it, merge
  demo beats ① and ②.
- **Longer slot:** split slide 6 into "failure modes" → "the guards"; add an Eric Moore
  servicer-signer backup slide (institutional servicers, not a private person — safe).
- **One recurring visual:** reuse the Croman "masks → one owner" graphic on 2, 6, and 10 so the
  audience tracks one story end to end.

## Deliberately *not* in here

Rashad / Demos examples (contaminated), the Option-B cutover internals (too in-flight), any
specific *private* landlord the pipeline newly linked, and any precision/recall number not yet
produced. Keeping those out is what lets slides 3, 5, and 11 be believed.

---

## Grounding & sources (every number is reproducible)

| Slide | Claim | Source / how to reproduce |
|---|---|---|
| 2 | 118 buildings, 107 LLC names | WoW portfolio #87254 (`wow.wow_portfolios`, `landlord_names=["STEVEN CROMAN",…]`) → its BBLs → distinct `public.pluto_latest.ownername`. AG case: public record. |
| 5 | 17 GAY LLC vs Steven Croman | `lookup_building_ownership("1005930008")`: `dof_ownername` (Type I) vs `APPARENT_CONTROL`→Landlord (Type II). |
| 6① | ≈1.0 precision, 0 cross-surname | 105-record gold set, `eval/run_full.py` precision guard; threshold 0.999. |
| 6② | 39,456 / ~780 / ~620 | `compare_kg --divergence` (materialized `wow.wow_portfolios` ∩ `IN_OWNER_GROUP`). |
| 6③ | ~530-pair blind eval, not run | The eval-sample frame (5 strata) via `score.py`; needs blind adjudication. |
| 7 | 138 owners / 453 buildings @ 770 Lexington | Raw HPD: distinct HeadOfficer/owner names with `businesshousenumber='770'`, street `LEXINGTON%`. WoW matching (`landlords_with_connections.sql`) has no aggregator cap. |
| 8 | ~28,500 mgrs / ~67,000 bldgs · ~15,800 nexuses · ~6,500 owner-groups | Live graph: `:Manager` / `MANAGED_BY`; multi-building `:Portfolio`; `:OwnerGroup`. |
| 10 | OG-105462: 12 fragments, 127 buildings; Centennial 114 | `owner_group_portfolio("OG-105462")`; `building_manager("1005930008")`. Agent-verified end-to-end on the current build (commit 773ea63). |

**Standing caveats (never drop):** leads, not verdicts — never emit/imply a legal
ownership determination; divergence ≠ accuracy; the demo is pinned to a public landlord (Croman)
and surfaces no novel beneficial-owner claim about a private individual.
