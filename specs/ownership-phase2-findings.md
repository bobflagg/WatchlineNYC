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

## Materialization + status

Parallel `:ResolvedEntityV2` materialized (run `REV2-20260907T230254Z`): 5,886 entities / 13,756
memberships (all with `party_reference_id` = C1 lineage); legacy `OwnerGroup` (6,540) untouched; shadow
invariant holds on persisted data. Phase-2 reads/pure/materialization units complete. **Remaining:** apply
co-op/condo at C5 projection (F2); the Track-A cutover (gated on ratified §8.1 numbers + these shadow
results); curated audit (Kadden); size/decide the `registered-llc-id` DOS-entity-id join once the frame is
adjudicated (F4); add an `institutional_dominated` projection flag for nonprofit/HDFC/institutional
owners (F5, not a blocker); measure/mask aggregator *officers* in node construction (F6, not a blocker); add
an agent/exclude disposition to the adjudication frame, orthogonal to the identity label (F7), before scoring.
