# Option B migration — Phase 2 findings (parallel build)

**Date:** 2026-09-07 · **Status:** findings from building `ResolvedEntityV2` alongside legacy; **F1
needs a C3 refinement decision before the resolver is run for the cutover.** The C3 resolver
(`resolved_entity.resolve`) is committed as the **signed-off** spec and is **not** changed here.

## F1 — C3 person-attribute cannot-links wrongly split entity-level (`registered-llc`) merges

**What the parallel build showed** (read-only, live graph, snapshot 2026-09-07): running `resolve_graph`
over the identity edges and comparing to legacy identity-only union-find:

| | components (multi-member) |
|---|---|
| legacy identity-only (no C3 constraints) | 6,690 |
| C3 as signed off | **6,498** (+ extra singletons; 7,311 total) |

C3 **dropped 859 edges — all `registered-llc-name`**: 847 on the **surname** constraint, 12 on
**entity_type**. **Zero** `splink-fellegi-sunter` edges were dropped; **zero** `curated` adjudications.
Of 16,034 references, 16,017 classify as `person`.

**Root cause.** `registered-llc` links landlord nodes whose buildings share a DOF owner **entity**, so it
deliberately connects **differently-surnamed person references** (co-officers of one LLC) — "links by
owner entity, spans surnames by design." C3's `surname` and `entity_type` cannot-links are
**person-identity** properties; applying them to an **owner-entity** assertion splits legitimate merges.
The rest of the pipeline already treats this asymmetrically — `verify_splink` scopes its hard
cross-surname gate to **model edges only**, and `cluster_gated` keeps `fellegi-sunter` edges
surname-clean **upstream** (hence 0 fellegi drops here).

**Why this is the parallel build doing its job:** the gap surfaced read-only, before any cutover, with a
faithful implementation of the signed-off contract. No silent fix.

### Proposed C3 refinement (for review — pick one)

- **R1 — scope person-attribute constraints to person-identity edges.** `surname` / `entity_type`
  cannot-link apply only when the *merging edge* is `fellegi-sunter`; `registered-llc-*` and `curated`
  (owner-level) impose only the **conflicting-identifier** constraint. *Con:* constraints become
  edge-method-scoped, not clean component-summary properties (a component can then hold mixed surnames via
  an llc edge, which is correct but complicates the invariant).
- **R2 (recommended) — drop person-attribute cannot-links from C3; keep conflicting-identifier + an
  institution guard.** Rationale: `fellegi` surname-cleanliness is already enforced upstream
  (`cluster_gated`), and `registered-llc`/`curated` are owner-level (surname/type-agnostic), so the
  universal `surname`/`entity_type` cannot-links are **redundant for fellegi and wrong for llc**. Retain
  the **conflicting stable identifier** hard constraint (universal, correct; a no-op until DOS ids exist)
  and a coarse **institution guard** (institutions are already excluded from ownership, so don't fold one
  into an owner component). *Effect:* C3 matches legacy identity-only on the 859 owner-entity merges while
  keeping the adjudication path for identifier conflicts.

**Recommendation: R2.** It aligns with the existing architecture (cross-surname is a model-edge concern,
handled upstream), keeps C3's constrained-union-find clean, and preserves the invariant the reviewer cared
about (deterministic conflicts → adjudication). The permutation-invariance and allowlist properties are
unchanged. If chosen, C3/§C3 and `resolve` update together, with the surname/entity-type tests replaced by
identifier-conflict + institution-guard tests.

**Blocking:** the resolver should not be run *for the cutover comparison* until R1/R2 is decided — the
current output over-splits 859 real owner merges. Everything else in Phase 2 (graph read, party-reference
keying, parallel materialization) can proceed.

### F1 RESOLUTION — R3 (neither R1 nor R2), 2026-09-07

Review rejected both R1 and R2 and diagnosed the real error: **`registered-llc` was misclassified as an
identity edge.** It links **co-officers — distinct people — of one LLC**, i.e. an owner *association*, not
aliases of one party. Merging them into `ResolvedEntityV2` violates the invariant regardless of constraint
scope. The 859 "over-splits" were the C3 constraints *correctly* preventing distinct people from being
collapsed. **The fix is the edge taxonomy, not the constraints.**

**R3 (adopted):**
- **Remove owner-level `registered-llc` (name-only) from identity resolution** → it joins the substantive
  relationship layer (C4), alongside deeds, as an owner-association.
- **`registered-llc-id`** stays deterministic identity **only for LLC-reference ↔ LLC-reference** (same
  legal entity by jurisdiction + id), **never person↔person** (not present in the graph yet).
- **Audit `curated-same-owner`** by endpoint semantics: keep as identity only where a seed means "these two
  references are the **same person / legal entity**"; a "same owner / shared control" seed is a
  *relationship*, not identity. *(Action: review `CURATED_OWNERS` — Croman/Rashad = same-person fragments ✓;
  confirm Kadden is same-person, not co-owners.)*
- **Retain** C3's person and entity-type cannot-links (they were correct).

**Re-diagnostic after R3 (live, read-only):** identity edges = 10,933 (`splink-fellegi-sunter` 10,744 +
`curated-same-owner` 189); `registered-llc` (2,270) excluded → relationship layer. **ResolvedEntityV2 =
5,886 components, 0 adjudications, 0 dropped** (the cannot-links now have only clean same-party input, so
they fire zero times — correct defense-in-depth). 3 components have a deterministic core (durable-`entity_id`
eligible) — the curated seeds; the rest are probabilistic (`resolution_id` only) until a DOS-id join
activates `registered-llc-id`.

**Takeaway (reviewer):** the parallel build proved the "identity-only" legacy input still carried
owner-association edges. Correct response = fix the taxonomy, not loosen identity. Implemented in
`resolved_entity.py` (identity methods = fellegi + curated only; `registered-llc`/deed rejected fail-closed);
contracts C2/C4 updated accordingly.

## F2 — Shadow comparison confirms v2 is a strict refinement of legacy

`shadow_compare.py` (read-only), v2 vs legacy `OwnerGroup` (also reproduced against the materialized run
`REV2-20260907T230254Z`): **`v2_entities_spanning_legacy_groups = 0`** — the refinement invariant holds
(v2 never merges what legacy split; v2 edges ⊆ legacy edges). 79 legacy groups split in v2 (held only by
registered-llc/deed among shared members); 2,449 nodes correctly leave identity (association-only). One
finding: `v2_only = 428` because **legacy folds the co-op/condo ownership-exclusion into the grouping**,
whereas v2 keeps identity clean and applies co-op/condo at the C5 projection — another conflation the
layered model separates. **Action:** apply co-op/condo exclusion at the v2 C5 projection, not in identity.

## F3 — C0 residual collision risk is small, bounded, and human-sampled (not auto-detectable)

`c0_lineage.py`: the Level-0 collapse population is **349 collapses / 726 nodes / 2,645 buildings (0.31%)**.
A collapse is same-key by construction (only normalized-away formatting differs), so it carries no
attribute contradiction to auto-detect; the genuine same-name/same-address different-person risk sits
*inside* one reference and is **not decidable from HPD fields** (no discriminating identifier). So C0 =
**retain lineage** (`read_contact_lineage`, demonstrated) + bound the population + **human-sample** the
residual ambiguity via the eval `§8.1` C0 protected stratum. Absence of a contradiction ≠ same identity.

## F4 — Adjudication surfaces the Option-B recall cost: a same-legal-entity split only a deed proves

Surfaced while adjudicating the cutover frame (pair **CUT-0001**, St. Nicks Alliance / Brooklyn
Neighborhood HDFC). The two node groups anchor on different individuals (Frank Lang vs. Michael Rochford),
but **both** carry the same two GP officers (roles swapped between the groups) **and** the same
`CorporateOwner` of record, `BROOKLYN NEIGHBORHOOD HDFC`, at 2 Kingsland Ave. Ground truth is **SAME**,
proved at T1 by a single deed: **doc `2013070700015001`** (CRFN `2013000371119`, 2013) co-conveys
`3030310013/14/15` (18/20/22 Stagg St — entity A) **and** `3028350002` (512 Morgan Ave — entity B) to one
grantee, *Brooklyn Neighborhood Housing Dev Fund Corporation*. One corporation holds title across both
groups — not distinct per-project HDFCs under a shared sponsor.

**Why this matters for the cutover.** The signal that proves SAME is a **deed co-conveyance** — which
Option B (correctly) classifies as a **relationship**, not identity. So v2's identity-only layer **splits**
this pair while legacy `OwnerGroup` (which unions `CONNECTED_BY_DEED` into identity) **merges** it. This is
therefore an **S1 split where v2 is wrong and legacy was right** → it scores as a **v2 false-split** (S1 +
gold SAME ⇒ v2 takes the `FS` penalty) against the §8.1 noninferiority test. The admissible path for v2 to
recover the merge is **`registered-llc-id`** (same DOS-registered corporation as owner of record — the
"same legal entity" identity meaning we allow), which **is not built yet** (only `registered-llc-name`,
demoted by R3). See F1 → R3 above.

**Two implications, both to weigh when reading the gate result:**
1. **Concrete argument to prioritize the `registered-llc-id` / DOS-entity-id join** — it recovers
   legitimate same-legal-entity merges like this one *without* reintroducing the co-officer conflation R3
   removed. The count of SAME calls of this shape in the 449-pair frame measures how much recall the join
   buys back — i.e. how much of any noninferiority gap is attributable to a not-yet-built admissible method
   rather than to the Option-B design.
2. **Weigh against exclusion.** These are nonprofit HDFC affordable-housing buildings that are flagged /
   excluded at the C5 projection anyway (F2). So the *downstream* cost of v2 splitting them may be small
   even though it registers as a false-split in the raw gate. When interpreting the noninferiority result,
   separate recall loss on **excludable nonprofits/HDFCs** from recall loss on **real accountability
   targets** — the gate's paired loss does not make that distinction on its own.

**Action:** when adjudication completes, tally S1-split SAME calls of this shape (shared HDFC/entity
owner-of-record, split by individual keying, bridged only by a deed) and report them separately in the
gate write-up; treat the tally as the sizing input for the `registered-llc-id` decision.

## F5 — Projection layer excludes only co-op/condo; nonprofit/HDFC/institutional is an unfilled gap

Surfaced alongside F4. The C5 projection (`resolved_projection.py`) applies exactly **one** exclusion —
co-op/condo — via `Building.coop_condo`, producing `building_count` (rental-only) and the
`coop_condo_dominated` flag (>50%). There is **no** nonprofit / HDFC / institutional exclusion, even though
we have repeatedly found that contamination axis:

- **HDFC** — nonprofit affordable-housing owner of record (F4: Brooklyn Neighborhood HDFC / St. Nicks).
- **Institutional** — e.g. a large cluster that resolved to Columbia University.
- **Nonprofit** — e.g. MHANY / affordable-housing sponsors.

These are **valid resolved entities** — identity must keep them (dropping would re-conflate "is this one
entity?" with "should we surface it?", the F2 mistake). But they are **not private-landlord accountability
targets**, so presenting them as big "landlord portfolios" misleads the tool's consumers exactly as a
co-op/condo board would.

**Proposed fix (not yet built):** an additive **`institutional_dominated`** flag on `:ResolvedEntityV2`
(and/or a rental-style attribution split), same shape as `coop_condo_dominated` — **flag, don't drop**,
computed at C5 over an owner/`Building`-level classifier. Detection is partly deterministic (owner-of-record
name patterns: `HDFC` / `HOUSING DEVELOPMENT FUND`, `CITY OF NEW YORK`, `NYCHA`, named universities) and
partly a small curated nonprofit list; scope it precisely so it flags mission owners without catching a
private LLC that merely uses a charitable-sounding name. This keeps the identity layer clean and puts the
"who counts as an accountability target" policy where it belongs — at projection, reversible and auditable.

**Nuance — separate a *financier/agency signal* from a *mission owner*, and neither from a private operator**
(sharpened adjudicating CUT-0002/CUT-0003). Two different jobs get conflated under one "institutional" label:

- **Governmental financier / agency as a co-occurrence *signal*** — e.g. `NYC HOUSING DEVELOPMENT CORP`
  (HDC) appearing as PLUTO owner, or `NEW YORK CITY` / `COMMISSIONER OF FINANCE` as an *in rem* deed grantee.
  These attach to a huge, unrelated swath of financed/foreclosed buildings, so they generate **spurious
  cross-entity links** (they were the *only* A–B tie in CUT-0002's 1983 in rem deed and CUT-0003's shared
  HDC PLUTO owner — both DIFFERENT). The classifier must **discount these as identity/ownership signals**
  (never merge on them), independent of the exclusion flag.
- **Nonprofit / mission owner as an accountability *target*** — e.g. St. Nicks / Brooklyn Neighborhood HDFC.
  A valid entity; **flag it out** of accountability attribution (the `institutional_dominated` flag above).
- **Private affordable-housing operator — do NOT exclude.** A private LIHTC developer (CUT-0003 B: Ryan
  Webler / WMW Realty Management, project LLCs like Bedford Courts III LIHTC at 3092 Hull Ave) is a
  **legitimate accountability target** even though its buildings are HDC-financed and affordable. "Appears
  under HDC financing / is affordable housing" is **not** grounds to exclude — otherwise the flag drops real
  private operators. Exclusion must key on *who the owner is* (agency/nonprofit), not on the presence of a
  financing or affordability marker.

So the fix is really two mechanisms: **(a)** an agency/financier **signal denylist** (HDC, City, in rem
grantees) that never contributes to identity or ownership attribution, and **(b)** the
`institutional_dominated` **target-exclusion flag** for agency/nonprofit *owners* — with private LIHTC
operators explicitly kept.

**Instance (CUT-0005) — a City *program* node in the graph.** Adjudication surfaced an entity literally
named `CITY OF NY DAMP/TIL` (the City's Division of Alternative Management Programs / Tenant Interim Lease),
plus TPT-program intermediary HDFCs (Neighborhood Restore, Restoring Communities, Neighborhood Renewal,
Preserving City Neighborhoods — the City's asset-management pipeline for ex-*in rem* buildings). These are
governmental/program nodes, not owners; the `institutional_dominated` classifier's deterministic list must
include program markers (`DAMP`, `TIL`, `NEIGHBORHOOD RESTORE`, and the TPT-HDFC family) — a node whose own
name is a City program is the easiest possible exclusion.

**Status:** logged as a follow-up; **not a cutover blocker** (co-op/condo exclusion already covers the
largest axis, and the flag is additive/presentation-time), but it should land before any outward-facing
attribution surfaces these entities as landlords. Relates to F2 (exclusion belongs at projection) and F4
(the HDFC that triggered it).

## F6 — The aggregator problem also comes through shared *officers*, not just shared addresses

The pipeline masks aggregator *addresses* (a business address shared by many unrelated owners, degree > 25 —
`aggregator_audit.py` / the `MAX_ADDR_DEGREE` mask) because they over-merge distinct parties into one
`Portfolio`/node. **CUT-0005 shows the same failure through a shared *officer*.** Entity A = `SALVATORE
D'AVOLA` is a single HPD HeadOfficer glued across **27 buildings owned by ~15 different parties** — five
different program HDFCs (Restoring Communities, Neighborhood Renewal, Neighborhood Restore, Preserving City
Neighborhoods), the City, two LLCs, and ~13 individual homeowners. Davola is a nonprofit/TPT-program
signatory (an *agent*), not an operator, so the node is not one owner — it is an aggregator officer.

**Contrast with the coherent-operator cases** (CUT-0002/0003): Frank Lang, Michael Weiss, Ryan Webler were
also one-officer-across-N-buildings, but their buildings resolved to a *single* operator each (St. Nicks,
WMW), so the node was legitimate. The discriminator is exactly the **per-side owner-of-record spread**: a
coherent operator's buildings share one (or few) owners of record; an aggregator officer's span many. (The
owner-review panel now shows this directly via per-side building-share on shared names — a shared owner that
is a *minority* on a large side, like Restoring Communities HDFC at 5/27, is the tell.)

**Implication for node construction (Track A identity layer).** Identity/`ResolvedEntityV2` is built from
`CONNECTED_BY_SPLINK` over `landlords_with_connections`, whose nodes are keyed off HPD contacts — so a
professional/program officer like Davola can seed a node spanning many unrelated owners, the officer analogue
of the aggregator address. The fix mirrors the address mask: detect an **aggregator officer** (an
individual/officer who is the registered head officer across N buildings resolving to many distinct owners of
record) and mask it from node construction, or split such a node by owner of record. **Not yet built, and
not a cutover blocker** (these program nodes are also caught by the F5 institutional exclusion at
projection), but it is a genuine identity-layer node-quality gap distinct from the address mask. Measure the
population before deciding scope: count officers whose HPD head-officer footprint spans > K distinct owners of
record.

**Second instance (CUT-0007) — a larger, private-side aggregator officer.** `LARRY HIRSCHFIELD` is HeadOfficer
on **105 of 106** buildings across the pair (types: 105 HeadOfficer, 4 Officer, 1 Agent, 1 IndividualOwner —
so he is formally the *head officer*, functionally a managing agent) spanning **~24+ distinct owners of record**
(Pacific Village LP, 27 Bed Stuy / Vision / FT Greene TB / Nia Homes / Mount Morris HDFCs, plus market LLCs and
trusts), from one office at 1675 Broadway. Confirms the pattern is not limited to City-program signatories
(Davola): it also arises for private managing agents/operators over mixed affordable + market stock. Reinforces
that the aggregator-officer mask should key on **owner-of-record spread**, not on institutional/nonprofit
content (Hirschfield's footprint is mixed).

**Critical caveat — the mask must NOT fire on a shell-LLC owner (the veil-pierce win itself).** CUT-0008 is
the trap: `SAM WURTZBERGER` (107) / `SAM WURZBERGER` (21) is one person (a one-letter typo), HeadOfficer +
Agent on **all 128** buildings from one office (381 South Fifth St) — footprint spanning **58 distinct owners
of record over 59 deeded buildings**. A naive "officer spans > K distinct owners" rule would flag him as an
aggregator officer — but those 58 "owners" are his **own single-purpose shell LLCs** (address-named: 224
Moffat LLC, 256 Jefferson YMJ LLC, 1200 Decatur Street LLC, …) plus a family member (Miriam Wurzberger). He is
a **real 128-building Williamsburg owner using shells** — the Croman/Escobar veil-pierce pattern the resolver
exists to consolidate. Masking him would destroy the flagship win. So the detector **cannot key on
distinct-owner count alone**: it must distinguish *"many single-purpose shells of one owner"* (KEEP — the
owning LLCs themselves collapse to one owner-group / share the officer as their only principal / are
address-named single-purpose) from *"many independently-identified owners"* (MASK — the owning entities have
their own distinct identities, e.g. named HDFCs/LPs like Hirschfield's). This is exactly the operator-vs-
aggregator test `aggregator_audit.py` already applies to high-degree **addresses** (filers resolving to ≤2
owner-groups = operator → keep; spanning many = aggregator → mask); the officer mask needs the identical
second-order check. **Without it, F6 would mask the resolution's best cases** — so the discriminator, not the
count, is the finding.

**Combined instance + a negative result on count-based flagging (CUT-0009).** CUT-0009 pairs
`JACQUELINE TOM` (35, an aggregator officer — HeadOfficer across ~16 *independent* nonprofit HDFCs: NSA,
Newset, 1415 Wythe, Cluster II, 68-19 Woodhaven, 644 Riverside, Brookset, New Hull St, St. John's Place, …)
with `EMILY LEHMAN` (2, St. John's Place Family Center only) — glued by a **shared nonprofit-services office
(247 West 37th St)**, a shared managing agent (Urban Resource Institute), and one overlapping HDFC
(St. John's Place, a minority 1/35 on A vs 2/2 on B). It stacks all three exclusion axes: aggregator address
+ aggregator officer + nonprofit — the hardest confusion for a reviewer, because the overlap panel fires on
both a shared owner name and a shared address, yet the truth is DIFFERENT. Attempting an **aggregator-address
degree flag** for the owner-review panel, a count-based rule was measured and **rejected — it cannot
discriminate**: distinct owners-of-record at 247 W 37th (shared office) = 27, but the Wurtzberger shell
office (CUT-0008, one owner) = **46** and St. Nicks' HQ (CUT-0001, a **SAME** case) = 38; distinct
head-officer *people* = 247→**4** (one pro heads most, so it *under*-counts the real shared office), St.
Nicks→12, Wurtzberger→3. So a "many owners → aggregator" address flag would misfire on the shell-LLC owner
**and would have flagged CUT-0001's 2 Kingsland, wrongly pushing a correct SAME toward DIFFERENT**; a "many
people" flag misses 247 and flags St. Nicks. Separating a shared office from a one-owner-shell office by
counting is the same impossibility as the officer mask above — it needs owner-group resolution the standalone
owner-review tool lacks. **Resolution:** no count-based address flag in the tool; a static caveat instead
(*a shared address is ownership evidence only when the owners also match*), leaning on the owner overlap +
per-side building-shares as the real discriminator (owner-review commit `57ad1a8`). Consequence for the mask
in the pipeline (which *does* have the KG): the address-degree mask must stay owner-**group**-based
(`aggregator_audit.py`), never a raw name/person count — the counts above are the proof.

## F7 — Adjudication labels can't express "same party, but a non-owner agent to exclude"

CUT-0007 also exposed a gap in the **adjudication frame itself** (not the pipeline). Entities A/B are
`LARRY HIRSCHFIELD` (79) and `LARRY HIRSCFIELD` (27) — the **same person split by a one-letter name typo**
(same office, HeadOfficer role, overlapping managed entities). So the correct *identity* call is **SAME** (a
textbook typo-heal the resolver should make, and v2 merging them is a correct decision). **But** that party is
an aggregator officer (F6), so the node should be **excluded from ownership attribution**. The tool's three
labels — `SAME` / `DIFFERENT` / `INDETERMINATE` — cannot carry both facts at once:
- `DIFFERENT` is **wrong** (they are the same person) and would score a *correct* v2 typo-merge as a false
  merge, corrupting the gate.
- `INDETERMINATE` loses the (certain) identity signal and also under-credits a correct v2 decision.
- `SAME` is right for identity but silently treats an agent as an owner unless the exclusion is captured
  elsewhere (currently only free-text rationale).

**Implication.** The adjudication frame needs an **agent/exclude disposition orthogonal to the identity
label** — e.g. an `exclude_reason ∈ {agent, institutional, coop_condo, …}` flag recorded alongside
`SAME`/`DIFFERENT`, so "same party **and** exclude from ownership" is expressible without forcing the reviewer
to encode role as an identity vote. Until then: **record such pairs `SAME` with the agent/exclusion noted in
the rationale** (do not vote `DIFFERENT`), and treat the exclusion as an F5/F6 projection concern at scoring.
Scoring should also be aware that some `SAME` pairs are agent nodes destined for exclusion, so their identity
correctness and their ownership-attribution exclusion are counted separately. Not a cutover blocker, but it
should be resolved before the frame is scored so agent typo-heals aren't mislabeled.

## F8 — Cross-mechanism transitive over-merge validated live (OG-110); + a correlated-pairs scoring caveat

Tracing why CUT-0011 (`ALEX LASZLO` 19 / `EPHRAIM FRUCHTHANDLER` 14) was in the frame despite an **empty
records panel** (no shared deed, owner-of-record, officer, or address) surfaced the cleanest Option-B
validation so far. Both nodes sit in one legacy **`OwnerGroup` OG-110** — a 14-member blob spanning six
unrelated surnames (Feldman, Laszlo, Fruchthandler, Morgenstern, Bharat, Yu). The connecting path is a
**cross-mechanism chain through a third party**:

> `ALEX LASZLO` —[CONNECTED_BY_SPLINK `registered-llc`]→ `SONNY BHARAT` —[CONNECTED_BY_DEED `acris-deed`]→ `EPHRAIM FRUCHTHANDLER`

Both hops are **relationship** (association) edges — Laszlo/Bharat co-own a registered LLC (co-owners =
distinct people, the F1/R3 case), Bharat/Fruchthandler co-conveyed a deed — neither is same-party identity.
Legacy `OwnerGroup` unions `CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED`, so it chained two *different* association
mechanisms through the bridge node Bharat into one 14-way group: the `deed_bridged` cross-mechanism
transitivity risk, caught live.

**v2 breaks it cleanly** (materialized run `REV2-20260907T230254Z`): Laszlo → `RE-3378` (4 members),
Fruchthandler → `RE-34289` (2 members, a *different* entity), and **Sonny Bharat → no `ResolvedEntityV2` at
all** (his only edges were relationship edges, so he forms no identity entity with anyone). Option B (identity
= fellegi + audited-curated only; `registered-llc-name` and deed demoted to the relationship layer per R3)
removes both hops from identity → the chain collapses → the unrelated owners separate and the bridge dissolves.
**v2 correct, legacy wrong** — a substantive precision gain, exactly what the cutover gate should credit. This
confirms the S1 split stratum is catching *real* legacy over-merges (cross-mechanism transitive chains), not
only typos/nonprofits. It also explains the empty panel: the bridge is a *third party* (Bharat) not in the
pair, so the A↔B records overlap is genuinely nil — the tool is correct; the connection lives in the graph.

**Second blob confirms the class (OG-1073, CUT-0013).** `ERIC MOORE` (13 nodes) / `KARLA BALLARD` (6) sit in
one legacy `OwnerGroup` OG-1073 — a 37-member / 12-surname common-name blob (Khair, Smith, Graham, Torres,
Johnson, Ross, …; the "Eric Moore" common-name over-merge from the vetting notes). The Moore↔Ballard path is
a **registered-llc-only** variant of the same pattern: `ERIC MOORE` —[`registered-llc`]→ `SIDNEI JOHNSON`
—[`registered-llc`]→ `KARLA BALLARD` (with `splink-fellegi-sunter` holding each name's own nodes together).
Both bridge hops are co-ownership (relationship) edges through the intermediary Johnson; v2 keeps the identity
(`splink`) edges and drops the `registered-llc` hops → Moore → `RE-34571`, Ballard → `RE-63177` (separate).
So it is the *class* of relationship-edge transitivity that legacy over-merges, not any single mechanism
(OG-110 = registered-llc + deed; OG-1073 = registered-llc ×2). Note the shared conveyance deeds here were
**pure noise** (30 historical 2,200–2,437-parcel assemblage deeds, Great Eastern / Tidewater) — never the
linkage; see F9.

**Correlated-pairs scoring caveat (for `score.py`), measured across the 449-pair frame.** OG-110 generates
**three** pairs — CUT-0010 (Laszlo–Morgenstern), CUT-0011 (Laszlo–Fruchthandler), CUT-0012
(Morgenstern–Fruchthandler, linked by a $141.5M bulk co-investment deed) — but it is not special. Counting
the key's `owner_group_id` over all **109 S1 pairs**: they come from **79 split owner-groups** (the census),
of which **15 groups contribute 3 pairs each** (the frame's `max_pairs=3` per-group cap) and **64 contribute
1 pair each** — so **45 / 109 S1 pairs (41%) are correlated** within a multi-pair group, only 64 independent
singletons. These pairs nearly form the complete graph over a few members of each such blob — the hallmark of
pairs drawn within one cluster — so they are **not independent observations**. **S2 is clean**: the 340
retained-merge pairs come from **340 distinct v2 entities (one pair each)** — fully independent, no clustering
needed. **Consequence:** the §8.1 paired bootstrap must **cluster-bootstrap the S1 stratum at the split-group
level (resample the 79 groups, not the 109 pairs)** — otherwise the 15 triple-pair blobs are counted as 45
independent observations instead of 15 clusters, shrinking S1 variance artificially; **S2 may resample at the
pair level**. It also argues for reporting S1 per split-group (79 rows), not pooled over 109 pairs.

## F9 — The blinded review panel must MIRROR the pipeline's deed exclusions, or it over-signals

The standalone owner-review panel computes its own records overlay (owner/officer/address/deed) directly from
justfixwow — it has no access to the KG's edge logic. So it can **display as "signal" exactly the records the
pipeline already excludes**. CUT-0013 is the clean example: Moore↔Ballard "share" **~30 conveyance deeds**,
*all* 1916–1924 historical land assemblages ($0, 2,200–2,437 parcels each, Great Eastern Waterfront /
Tidewater). The pipeline's `deed_edges.py` caps co-conveyance at **2–25 parcels**, so none of these ever
created a `CONNECTED_BY_DEED` edge — but the panel rendered them as **substantive** shared deeds (the grantees
aren't financiers, and the panel had no parcel-count signal), over-signaling SAME on pure noise.

**Fix (owner-review `7972dbf`):** fetch `n_parcels` per deed and discount any deed over `MEGA_PARCEL_MAX = 25`
as bulk/assemblage — the panel now mirrors the pipeline's own cap. This is the second instance of the same
class as the F6 **negative result on count-based address flags**: a blinded standalone tool must not
*re-derive* KG-based judgments (owner-group resolution), but it **must replicate the pipeline's deterministic
exclusions** (2–25 parcel deed cap; institutional/financier grantees; aggregator-address mask where a global
degree is available). **Parity principle:** any deterministic filter the pipeline applies before forming an
edge should be applied by the panel before showing that record as a signal — otherwise the panel and the
system disagree about what counts, and the reviewer is handed noise the system already ignored. Not a cutover
blocker (the pipeline was always correct; only the panel over-showed), but worth a parity pass over the other
edge builders before the frame is adjudicated at scale.

## F10 — Frame-QA triage: the whole frame characterized; 27 pairs need real judgment, 0 anomalies

Built a **lead-facing** triage (`eval/frame_qa.py`, 9 hermetic tests) that classifies every one of the 449
pairs from `cutover_key.jsonl` + `review_queue.jsonl` + the graph — automating the OG-110/OG-1073 traces done
by hand. **Blinding boundary:** it derives from v2's own decision, so it is WatchlineNYC-side and emits
`eval_out/cutover/frame_qa.jsonl` — it must **never** be imported into owner-review or consulted while
adjudicating (that would make the gate circular; the artifact is not committed for the same reason). Live run:

| bucket | n | reading |
|---|---|---|
| `name_similar_split` | **27** | S1 splits of same/typo-surname nodes — false-**split** candidates (recall misses) |
| `review_merge` | **24** | S2 large non-curated merges — false-**merge** candidates (the FM surface) |
| `routine_blob_split` | 82 | S1 dissimilar-surname transitive/relationship splits — expected DIFFERENT |
| `routine_merge` | 316 | S2 surname-consistent identity merges (≤4 members, or curated) — expected SAME |
| `RED_FLAG_*` | **0** | no invariant breach anywhere in the frame |

So **51 pairs (27 + 24) need careful judgment**, symmetric on both error directions; the other 398 are
routine and 0 are anomalies. Three results worth keeping:
- **0 red flags** extends the one-shot structural invariant test (`verify_membership_identity_only`) to a
  **per-pair check across the whole frame**: no v2 entity in any of the 449 pairs is held together by a
  non-identity edge, and no uncurated entity spans surnames. Strong standing confirmation of the Option-B
  invariant on the actual eval population.
- **The 27 `name_similar_split` pairs are the concrete F4 sizing set** — the split decisions that *might* be
  same-owner recall misses (typos like Hirschfield/Hirscfield [CUT-0007], Wurtzberger/Wurzberger [0008],
  Valiotis [0022], Manocherian [0100]; identical-name splits the common-name veto produced — CUT-0043/0079/
  0096/0099/0106; and same-surname/different-first-name family cases — Zachariadis [0004], Franciosa [0045]).
  Each is either a real recall miss or a correct split of distinct same-surname people (→ credits the
  first-name/common-name veto). **The recall misses split by *mechanism*, and the fix differs:** a **typo
  miss** (same person, mis-spelled name) is a resolver/blocking-tuning fix, *not* the `registered-llc-id`
  join; a **same-legal-entity miss** (differently-named parties, one owning corp) is the F4 DOS-id case. Size
  them separately. **Adjudicated tally (running):** confirmed same-owner **typo recall misses** — CUT-0022
  `EFSTATHIOS`/`EFSTAHIOS VALIOTIS` (a 2-bldg fragment split off the 64-bldg Alma Realty node; same office
  31-10 37th Ave, agent Nicholas Conway, ALMA owning LLCs — one person), joining CUT-0008 (Wurtzberger) and
  CUT-0007 (Hirschfield, but agent-excluded per F6/F7). These size the **typo-recovery** lever, distinct from
  F4's `registered-llc-id`.
- **The 24 `review_merge` pairs are the symmetric false-MERGE set** — the FM side the S2 stratum actually
  estimates. Calibration matters here: **common surname is not a discriminator in this population** (median
  surname frequency ≈ 268, so flagging on it hit 221/340 — useless); **member count is** — 257 of 340
  entities are 2-member (a single merge decision, low risk), so the 24 non-curated merges with ≥5 members
  are where a retained merge is most likely wrong. Curated (audited) merges are exempt. Adjudicating **these
  51 (27 + 24) blind** is where the real signal is; the other 398 are routine.

*A methodological note the tool also corrected in-flight:* the first classifier over-flagged 25 merges on
`registered-llc` edges that merely **co-exist** with the identity edges (the pipeline writes all methods as
`CONNECTED_BY_SPLINK`); the true canary is an entity with **no identity edge at all**. Lesson mirrors F6/F9:
edge *presence* ≠ edge *dependence* — check identity-connectivity, not method membership.

*Blind spot found in adjudication (CUT-0029):* the `routine_blob_split` bucket assumes **dissimilar surname →
expected DIFFERENT** (a transitive/relationship split the frame treats as routine). But two **differently-named
partners** who co-own through the *same* LLC break that assumption: `ALAN SACKMAN` ↔ `JAMES HEFELFINGER` are
dissimilar surnames, yet both nodes are the *same owner* — `212-214 REALTY CO. LLC` (and Frontier / East West
Renovating) is the current owner of record on **both** sides, the two adjacent lots differing only in which
partner fills the HPD HeadOfficer slot. Adjudicated `SAME` (a person-anchoring recall miss, the F1/F4 cost),
so `frame_qa` mis-bucketed it as routine-DIFFERENT. The surname-dissimilarity heuristic is a triage prior, not
ground truth: a same-owning-entity check (same registered LLC / grantee on both sides) should override the
"dissimilar surname" routing before a blob split is called routine. Not a scoring bug — the frame-QA artifact
is blinding-side and never reaches the reviewer — but it means the **27+24 "needs judgment" set understates
the S1 false-split surface**: partner-split pairs hide inside the 82 routine blobs. Two fixes landed:
(1) the adjudication-side rule is written into eval-protocol §3.1 (single owning entity on both sides → SAME,
vs. distinct entities sharing a person → DIFFERENT); (2) `frame_qa.classify` promotes a split whose two
entities are joined by a **`registered-llc` edge crossing the A/B boundary directly** into a new
`same_llc_split` review bucket (priority 2) — the same-owning-entity override. The discriminator is a *direct
cross-boundary* edge (both entities own a building registered to the same LLC), computed by a dedicated query
(`_S1_CROSS_LLC`) — **NOT** the shortestPath hop count (which runs between arbitrary entity reps and buries
the edge: CUT-0029's own path is 2 hops, `splink`+`llc`), and **NOT** a transitive chain A–llc–X–llc–B through
a *third* entity (the OG-110/OG-1073 blobs, which have no direct A↔B edge). **Live re-run** (2026-09-09,
run `REV2-20260907T230254Z`): 43 pairs moved out of `routine_blob_split` (82→39) into `same_llc_split` —
CUT-0029 caught; OG-110 (CUT-0011) and OG-1073 (CUT-0013/0014) correctly stayed routine (`cross_llc=False`).
The S1 needs-judgment surface thus grows **27+24=51 → 94** (8 of the 43 already adjudicated). **Institutional
filter (added, tightening 43→40):** the override now also recovers the *shared DOF owner name(s)* between the
two entities (query `_S1_SHARED_OWNERS`) and drops a pair to routine (`same-llc-financier-noise`) when its
only shared owner is a financier / government / LIHTC-investor vehicle — the F5 discount (`_financier`:
NYC HDC "HOUSING DEVELOPMENT CORP", NYCHA, City, state, dormitory authority, dept, "EQUITY FUND"). This is
needed because the registered-llc edge carries no name and `llc_edges`' own exclude list misses HDC and equity
funds. Live: 3 pairs dropped — CUT-0002/0003 (NYC HDC) and CUT-0091 (NEW YORK EQUITY FUND 2005 LLC). A shared
**HDFC** is deliberately *kept* (a real nonprofit owner — CUT-0001, an actual SAME), as are private LLCs and
any pair sharing at least one non-financier owner. Only 3 of 43 were financier-only, so the override was not
badly polluted to begin with. **JV + placeholder refinement (tightening 40→23):** adjudicating the 34 new
`same_llc_split` pairs showed the residual over-inclusion was *two-party JVs* — a single small owning LLC that
both operators co-own on one asset while running otherwise-separate portfolios (co-ownership = common control,
Option B / R3, not identity). `classify` now (i) drops DOF placeholder owners (`_placeholder`: "UNAVAILABLE
OWNER" etc., which had inflated CUT-0064/0109 degree to ~7,650), and (ii) demotes a pair to routine
(`same-llc-jv-no-office`) when its only private shared owner is a **single LLC of citywide degree ≤ 4 with no
shared office** (query `_S1_SHARED_OFFICE` + `_OWNER_DEGREE`); a shared office, >1 shared LLC, a larger/dominant
owner, or a person-owner keeps it promoted. Live: 40→**24** (16 demoted as JV, the placeholder/financier ones
folded into `same-llc-noise`). One JV-guard exception — an **eponymous owner** (the LLC carries an anchor's
own surname, e.g. CUT-0052 anchor *Parlanti* + `PARLANTI GROUP LLC`) is that person's entity, an identity link
not a stranger JV, so it is reclaimed (`eponymous-owner`); surgical (CUT-0052 only, no false reclaims). The 23 survivors carry a real "one operation" signal (shared office, multiple
LLCs, a person owner-of-record, or a larger holder to judge — e.g. the OLIT servicer trust, Brooklyn Housing
Preservation LP, the MTEK triangle). Lead-side adjudication of the 34 (coverage + citywide degree + shared
office, not a full per-pair deed read): ~13 SAME (fragmented one-operation splits — the F1/F4 recall the
cutover trades away), ~15 DIFFERENT (JV / servicer / incidental), ~6 needing the panel. The one recall tail the JV rule
would have cut — a genuine *small* single-office-less operation under an eponymous LLC (CUT-0052) — is
reclaimed by the eponymous-owner guard above; any remaining tail stays in the blind review queue regardless
(all 449).

**Full adjudication of the 24 survivors (co-principal verified) + the shared-owner-principal refinement.**
Adjudicating all 24 from primary records — the decisive test being a **shared owner-principal** (an HPD
person-officer on *both* sides = one operation) — gave **13 SAME / 11 DIFFERENT**, and exposed that the JV
rule's `shared_office` keep-signal was wrong: a shared *office* is often the **managing agent's** office
(CUT-0047/0071/0103 — management nexus, no shared owner), which over-kept, while CUT-0087's SAME was
under-called from coverage. So the JV keep-signal was changed from `shared_office` to **`shared_principal`**
(a new Postgres lookup, `_SHARED_PRINCIPAL_SQL` over `hpd_contacts`, wired into `frame_qa` via `pg_conn`;
`--no-pg` falls back to eponymy/degree/multi-owner). `shared_office` is retained as context only. Live re-run:
**24 → 21** — demoted the 4 agent-office/no-principal pairs (0047/0071/0093/0103, matching the DIFFERENT
verdicts) *and* **reclaimed CUT-0068**, a real shared-principal operation the office-rule had wrongly cut
(a recall fix, not just tightening). Flag renamed `same-llc-jv-no-principal`. The 13 SAME are the F1/F4 recall
the cutover trades away (verified, on the memory tally); the DIFFERENTs are management nexus / two-party JV /
servicer (OLIT reverse-mortgage trust) / co-investor (MTEK). Lesson: **owner-principal overlap is the SAME
signal; shared office or shared agent is management → points DIFFERENT** — the project's core
ownership-vs-management line, now enforced by the triage. Artifact stays uncommitted (blinding).

## F11 — The panel asserted "owner of record" without currency, inviting a stale/current misread (null-`docdate` hazard)

Surfaced adjudicating **CUT-0028**: two person-named v2 entities — CATHERINE YU (33 bldgs) ↔ JAMES
HEFELFINGER (11) — whose *only* overlap was **HOMES FOR THE HOMELESS INSTITUTE, INC.** as shared
owner-of-record on one adjacent-lot building each (523 / 521 West 49th St), bridged by 2013 `$10` HDFC→HTHI
deeds. The panel's shared owner/principal line read "PLUTO owner, owner of record" with **no indication of
which deed made HTHI current, or when** — so confirming currency meant re-reading the ACRIS chain by hand.

**The hazard that bit the hand-check.** ACRIS legacy `FT_` deeds carry `docdate = NULL` with only
`recordedfiled` set. A naive `ORDER BY docdate` (NULLs sorted to one end) mis-ranks them. Re-deriving the
chain, I sorted by `docdate` and read the null-dated **1968–1980** FT_ deeds (Domb/Amorgos/Farhadian…) as
*post-2013* conveyances, and wrongly called HTHI a **stale/superseded** owner with divergent current owners.
The true chain is `1968–1980 private → 1982 City → 1992 HDFC → 2013 HTHI ($10, current)`. Note `deeds.py`
already orders `COALESCE(docdate, recordedfiled) DESC NULLS LAST` — **the panel's own latest-deed selection
was correct; the by-hand recheck was not.** The verdict is still **DIFFERENT**, but on the correct grounds:
HTHI is a *real, current* owner (F5 — kept substantive, not noise) that covers only **1/33 and 1/11** with no
shared operator/agent/address — **incidental minority co-ownership** (the BAANI / CUT-0015 pattern), not
staleness. Two entities each containing one building a third party owns are not thereby the same owner.

**The gap and the fix (owner-review `e6d5e8c`).** The panel left *currency* implicit and did not reconcile
PLUTO ownername against the latest deed grantee (the CLAUDE.md "recorded owner vs apparent controller —
surface the disagreement" principle). `fingerprint.py` now records `owner_deed_by_norm` — the most-recent deed
backing each owner-of-record claim, ranked by a **null-safe key (`_dkey`) so an undated `FT_` deed can never
outrank a dated one** — and `overlap()` attaches per-side `a_owner_deed`/`b_owner_deed` (date + amount) and
`a_pluto_only`/`b_pluto_only`. The panel renders **"owner of record · current 2013-07-01 $10"** inline and an
amber **"PLUTO only — not confirmed by deed"** caveat when a recorded owner has no deed backing (silent when,
as for HTHI, the deed confirms it — no false alarm). +2 hermetic tests (19/19).

**Lesson (mirrors F9's parity principle, applied to *currency* not *exclusions*):** make the deed that backs
an ownership claim legible *on the panel*, so a reviewer trusts the panel's correct latest-deed logic instead
of re-deriving it by hand and tripping over the null-`docdate` hazard. Additive and blinding-safe — no label,
score, or stratum; still pure over the same primary records. Not a cutover blocker.

## F12 — The aggregator-OFFICER exclusion: owner-diversity fails, out-of-state address works (Eric Moore)

Adjudicating `review_merge` surfaced **ERIC MOORE** (RE-34571) as a false merge: 210 NYC buildings under
one "Eric Moore" HeadOfficer name, all registered from **out-of-state corporate offices** (Temecula CA /
Dallas TX). This is the F6/F7 class — a shared *signer* (national SFR/REO servicer officer) that Splink
resolves as a single NYC owner. It needs an exclusion analogous to the aggregator-**address** mask
(`aggregator_audit.py`), but on the **officer** dimension.

**The obvious discriminator fails.** The aggregator-address mask keys on *owner diversity* (how many distinct
owners the filers span). Applied to officers it does **not** separate an aggregator from a real owner, because
a genuine owner running **one shell LLC per building** has the same profile:

| officer | buildings | distinct owner-LLCs | owners/bldg | states |
|---|---|---|---|---|
| ERIC MOORE (aggregator) | 210 | 194 | 0.92 | **CA, TX**, NY |
| MARK SCHARFMAN (real owner) | 136 | 103 | 0.76 | NY |
| ALBERT DWECK (real owner) | 34 | 31 | 0.91 | NJ, NY |

Scharfman — a verified single owner (CUT-0293, and WoW merges him) — spans 103 owner-of-record LLCs, nearly
Moore's ratio. **Owner-of-record diversity cannot tell a shell-LLC owner from a signer** — the F6 "mask must
not fire on shell-LLC owners" caveat, now shown in data.

**The clean discriminator is the out-of-state institutional address.** A person registering NYC buildings *at
scale* from a far corporate address (not the NY/NJ/CT/PA metro) is a national signer, not a local owner:
Moore = CA/TX (flag), Scharfman = NY (keep), Dweck = NJ (metro, keep). At **≥20 buildings and ≥60% far-state**
registrations, only **8 officers** flag population-wide — all clearly institutional, and several tie straight
back to adjudicated DIFFERENTs: Eric Moore, **Teresa Boudreaux** (the OLIT servicer trust, CUT-0056),
**Charles Gendron** (CUT-0085), Karla Ballard, Stanley Werb, Jacob Sacks, Matthew Lawrence, Sidnei Johnson.
No real NYC owner appears — a small, human-verifiable set, exactly like the 73 aggregator addresses.

**Draft (`aggregator_officer_audit.py`, read-only + tests):** a Postgres audit emitting the exclusion
*candidates* (pure `is_institutional_officer(buildings, pct_far)`; `MIN_BUILDINGS=20`, `FAR_PCT=60`,
`METRO_STATES=NY/NJ/CT/PA`). It **decides nothing** — like `aggregator_audit`/`curated_owners`, a human
curates the ~8. **WIRED (option a, extract-level):** `splink_bridge._resolve` now drops the flagged officers
(`aggregator_officer_audit.excluded_officer_names`) from the resolution input *before* clustering **and the
feedback loop**, so their buildings resolve by owner-of-record (registered-llc / deed), not the shared signer
name. Doing it at `extract()` — rather than as a clusterer veto — is essential: it is **feedback-proof**.
(This is the lesson from the earlier common-name/surname-escalation attempt in `cluster_gated`, since
**reverted**: `feedback_merge` runs after the clusterer with the same un-escalated `(last, first_initial)`
rarity gate and NO address check, so it re-merged what the veto split — the name-veto approach can't hold a
common signer. Dropping the identity at extract removes it from the frame `feedback_merge` even sees.)
**Out-of-state is necessary but NOT sufficient** (reviewing the 8 caught this): 4 of the 8 are genuine
out-of-state OWNERS — a Maine LIHTC developer (Gendron), an RI investor (Lawrence), a NH fund "CCM Ventures"
(Sacks), a NC apartment LLC (Werb) — whose buildings are ordinary owner-LLCs, not servicer-owned. The
distinguishing signal is the CorporateOwner being a **mortgage servicer / GSE / bank** (Fannie Mae, Selene
Finance, Shellpoint, Reverse Mortgage Solutions). So the rule (b) requires far-state AND `SERVICER_PCT`
servicer-owned buildings; it confirms **3** (Moore 59% / Ballard 78% / Boudreaux 100%), sparing the 4 owners
(and Johnson, out-of-state with servicer corps but <50% servicer-owned — conservatively left out). The
resolution excludes only the **curated allowlist** (a, `CURATED_SERVICER_OFFICERS = {Moore, Ballard,
Boudreaux}`) gated by that rule. Validated end-to-end: those 3 drop (Eric Moore **13 → 0** in the 145,412-row
frame; 24 identities total), the 4 real owners + Johnson are **kept**. Live-graph effect awaits the re-run.
Lesson (again): the "precision-safe" claim needed the review — out-of-state alone would have wrongly excluded
4 real owners. The **local**
aggregator-officer (Hirschfield/McEntee — NY managing agents across many owners) is a distinct sub-problem
out-of-state address does not catch, and owner-diversity can't safely catch either (Scharfman) — deferred.

*Correction to the review_merge finding (2026-09-10):* re-verifying on the re-run graph showed **GREG COHEN
was NOT a false merge** — one co-op/HDFC board officer (shared `MADISON AVENUE HDFC`, co-op buildings, already
dropped by the co-op/condo exclusion), reclassified SAME; my address-scatter read mistook it for different
people. So the S2 riskiest set had **one** genuine rental false merge (Eric Moore, handled here), not two.

## Materialization + status

Parallel `:ResolvedEntityV2` materialized (run `REV2-20260907T230254Z`): 5,886 entities / 13,756
memberships (all with `party_reference_id` = C1 lineage); legacy `OwnerGroup` (6,540) untouched; shadow
invariant holds on persisted data. Phase-2 reads/pure/materialization units complete. **Remaining:** apply
co-op/condo at C5 projection (F2); the Track-A cutover (gated on ratified §8.1 numbers + these shadow
results); curated audit (Kadden); size/decide the `registered-llc-id` DOS-entity-id join once the frame is
adjudicated (F4); add an `institutional_dominated` projection flag for nonprofit/HDFC/institutional
owners (F5, not a blocker); measure/mask aggregator *officers* in node construction (F6, not a blocker); add
an agent/exclude disposition to the adjudication frame, orthogonal to the identity label (F7), before scoring;
cluster-bootstrap the S1 stratum at the split-group level, not the pair level (F8), before scoring; parity pass
so the review panel mirrors the pipeline's deterministic edge exclusions (F9, mega-deed cap done, `7972dbf`);
adjudicate the 51 flagged pairs with special care (27 `name_similar_split` false-split / F4 recall-miss set +
24 `review_merge` false-merge candidates) — the rest routine, 0 anomalies (F10, `frame_qa.py`).
