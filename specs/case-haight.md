# Case study — 41 Haight Street (the "one block, six owners" deed veil-pierce)

The fourth in the series with [`case-escobar.md`](case-escobar.md),
[`case-miller.md`](case-miller.md), and [`case-levitov.md`](case-levitov.md). The first three turn on
**registration** signals — names, shared offices, managing agents — which is the only evidence Who
Owns What reads. This one turns on the evidence WoW reads **not at all**: the **ACRIS deed record**.
It is the cleanest case in the set of a question WoW cannot answer *even in principle* — here WoW isn't
merely wrong, it is **blind**, because the only thing tying these buildings together is a transaction.

All figures from the live `wow` schema + ACRIS + the discovery graph on **2026-09-11**
(run `20260910T095723Z`). Re-verify vintage before citing.

## The headline

Nine identical 4-unit townhouses on one Flushing block (41-09 → 41-27 Haight Street, Queens; block
5063, all built 2015):

| | Grouping | What connects them |
|---|---|---|
| **Who Owns What** | **6** portfolios (5 singletons + a 4-building one) | nothing it can see |
| **WatchlineNYC** | **1** owner group (`OG-51705`, 9 buildings) | a single ACRIS deed |

WoW splits the block into six unrelated owners because the registrations share **nothing** it keys on:
six different head-officer names, and **nine different DOF owner-of-record LLCs**.

| Building | DOF owner (recorded) | HPD head officer | WoW portfolio |
|---|---|---|---|
| 41-09 | NEW YUN REALTY LLC | Yun Li | `PF-…-96192` |
| 41-11 | HT ELEVEN REALTY LLC | Nicole Ho | `PF-…-72167` |
| 41-13 | AVERY AVENUE 168 LLC | John Jun Xu | `PF-…-48518` |
| 41-15 | 4115 HAIGHT ST INC. | Zhifeng Chen | `PF-…-96922` |
| 41-17 | C & L 17 FAMILY LLC | Jane Chan | `PF-…-44331` |
| 41-19 | 41-19 LIYANG INC. | John Jun Xu | `PF-…-48518` |
| 41-21 | 888 HAIGHT LLC | Shi Lin | `PF-…-85110` |
| 41-25 | 41 HAIGHT GROUP LLC | John Jun Xu | `PF-…-48518` |
| 41-27 | 41 HAIGHT STREET TOWNHOUSE OWNER, LLC | John Jun Xu | `PF-…-48518` |

No shared name, no shared registration address, no fuzzy identity link. WoW has nothing to grip.

## What actually connects them — one deed

The tie is a transaction, and it is unambiguous:

- **2020-09-14** — a Chapter 11 **bankruptcy trustee** (Gregory Messer, Esq.) sells the **entire row —
  all nine parcels on a single deed** (`documentid 2020092500293001`) — to one buyer,
  **41 HAIGHT STREET TOWNHOUSE OWNER, LLC** (17770 Castleton St, City of Industry, **CA**), for
  **$18,600,000**.
- **2021–2022** — that acquisition LLC then **re-deeds seven of the parcels, one at a time, each into
  its own single-purpose LLC** (grantor on every one = the acquisition LLC; ~$1.6M–$2.6M apiece).
- **41-27** was never re-deeded — it still sits under the original acquisition LLC, anchoring the whole
  set to the 2020 bulk deed.

So the six-names / nine-LLCs surface is a **restructuring of one bulk purchase**: buy the block
together out of bankruptcy, then scatter title across single-purpose shells and register each under a
different individual. It is the shell game's signature move.

## How WatchlineNYC catches it — `CONNECTED_BY_DEED` + the linked-successor guard

The owner-identity layer reunites all nine into `OG-51705`, and the wiring is **pure deed**: among the
six member landlord nodes the edges form a **complete clique — 15 `CONNECTED_BY_DEED` edges
(`method='acris-deed'`), and zero `CONNECTED_BY_NAME` / `_ADDRESS` / `_SPLINK`.** Composition =
**`deed_only`**: no identity signal at all, the pure veil-pierce.

Two `deed_edges.py` mechanisms combine here:
- **Latest-deed grouping** ties in 41-27, which still rests on the 2020 bulk deed.
- **The linked-successor guard** (`_restructured_groups`) recovers the seven re-deeded parcels: it
  recognizes that the joint grantee of the bulk deed (the acquisition LLC) is the **grantor** re-deeding
  each parcel, and that each successor LLC is a **shell** (globally the latest grantee of ≤3 buildings) —
  the exact "bought together, then re-deeded into its own LLC" pattern the guard exists to catch. Without
  it, the individual re-titlings would strand each parcel as its own group, which is precisely how they
  were designed to read.

WoW cannot reach this by any tuning: it has no deed edge to begin with, and no registration snapshot can
express "these nine were one purchase two years ago."

## Caveats — a lead, not a verdict

- **Shared origin and likely common control — not proof of one current beneficial owner.** A single
  bankruptcy purchase, a consistent grantor (the acquisition LLC) re-deeding into address-named shells,
  and one parcel never leaving the parent are strong **common-control** signals. But the onward deeds
  carry real ~$2.5M prices and distinct registrants, so a subset *could* be genuine individual sales
  rather than intra-owner SPE restructuring. The deed history says *"these nine share one origin and very
  likely one hand"* — it does not adjudicate present beneficial ownership. An investigator verifies from
  here (LLC filings, financing, management overlap).
- One nuance in the record: **41-25** saw a further 2024 transfer (grantor `PAWS 138 LLC` → `41 HAIGHT
  GROUP LLC`); its controller (John Jun Xu) is tied into the group through the parcels he still holds on
  the original chain (41-27 retained, 41-13/41-19 re-deeded from the parent), not through that later deed.
- Owner-group membership and apparent control are **Type II** inferences; the deed, its parties, and the
  DOF owner-of-record are directly **sourced** (ACRIS / DOF).

## Reproduce

Read-only. Vintage 2026-09-11.

```python
# 1) The owner group: deed-only, members span multiple WoW portfolios
#    MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup {owner_group_id:'OG-51705'})
#    OPTIONAL MATCH (l)-[:MEMBER_OF]->(p:Portfolio)
#    RETURN l.name, l.bbls, p.portfolio_id
#    -> 6 members / 6 names / 6 portfolios / 9 buildings.

# 2) The tie is deed-only (complete clique, no name/address/splink)
#    MATCH (a:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup {owner_group_id:'OG-51705'}),
#          (c:Landlord)-[:IN_OWNER_GROUP]->(og)
#    WHERE id(a) < id(c) MATCH (a)-[r]-(c) WHERE type(r) STARTS WITH 'CONNECTED_BY'
#    RETURN type(r), count(*)  -> CONNECTED_BY_DEED: 15  (== C(6,2); nothing else)

# 3) Nine different DOF owner LLCs on nine 4-unit townhouses built 2015
#    MATCH (b:Building) WHERE b.bbl IN [the 9 bbls] RETURN b.address, b.dof_ownername

# 4) The bulk deed (ACRIS, Postgres) — all 9 parcels, one document
#    SELECT m.documentid, m.docdate, m.docamount, count(DISTINCT l.bbl)
#    FROM real_property_master m JOIN real_property_legals l USING (documentid)
#    WHERE l.bbl = ANY(<9 bbls>) AND m.doctype LIKE '%DEED%'
#    GROUP BY 1,2,3 HAVING count(DISTINCT l.bbl) >= 2 ORDER BY 4 DESC;
#    -> 2020092500293001 · 2020-09-14 · $18,600,000 · 9 parcels.
#    Parties: grantor = "GREGORY MESSER, ESQ., AS CHAPTER 11 TRUSTEE";
#             grantee = "41 HAIGHT STREET TOWNHOUSE OWNER, LLC" (City of Industry, CA).

# 5) The restructuring: each parcel's LATEST deed, grantor -> grantee
#    (DISTINCT ON (bbl) ... ORDER BY docdate DESC) joined to parties
#    -> 7 parcels re-deeded 2021-22 FROM the acquisition LLC into single-purpose LLCs;
#       41-27 still on the 2020 bulk deed; 41-25 a further 2024 transfer.
```

## The quartet — one message, four mechanisms

- [`case-escobar.md`](case-escobar.md) — **merge** what WoW split (owner identity, one address typo).
- [`case-miller.md`](case-miller.md) — **un-merge** what WoW conflated on a shared **address** (nexus ≠ owner).
- [`case-levitov.md`](case-levitov.md) — **un-merge** on a shared **manager** (management ≠ owner).
- `case-haight.md` (this file) — **merge** what WoW is **blind** to: nine buildings tied only by an
  ACRIS **deed** (the veil-pierce; different names, different LLCs, different signers).

Together: the owner-identity layer is *precision-first* and reads evidence WoW does not — it keeps *who
owns* separate from *who operates through this office* and *who manages the building*, and it can see the
transaction record that a registration snapshot cannot. Escobar/Miller/Levitov show it deciding well on
signals WoW **has**; Haight shows it answering a question WoW **cannot ask**.
