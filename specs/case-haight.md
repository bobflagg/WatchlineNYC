# Case study — 41 Haight Street (an apparent deed veil-pierce the consideration gate now declines)

The fourth in the series with [`case-escobar.md`](case-escobar.md),
[`case-miller.md`](case-miller.md), and [`case-levitov.md`](case-levitov.md). The first three turn on
**registration** signals — names, shared offices, managing agents — which is the only evidence Who
Owns What reads. This one turns on the evidence WoW reads **not at all**: the **ACRIS deed record**.
It began as the cleanest case in the set of a question WoW cannot answer *even in principle*. But it
also became the sharpest illustration of a *limit* of the deed signal — the point where a bulk
purchase and a genuine sale become indistinguishable on the record alone.

> **Status — read this first (superseded outcome).** An earlier version of this case reported that
> WatchlineNYC reunited **nine** of the ten townhouses into one owner group (`OG-51705`). That is
> **no longer true**, and on re-verification it was never safely provable. The nine were not held in
> shells at nominal consideration — they were **re-deeded to distinct LLCs at market prices
> (~$1.6M–$2.8M)** in 2021–2024. The nominal-consideration gate added to `deed_edges.py`
> (commit `5f51475`) therefore declines the whole set, and **no 41 Haight building is in any owner
> group on current data** (`OG-51705` no longer exists). This case is now a **recall limitation**
> study, not a veil-pierce success: it shows the gate choosing precision over recall where price alone
> cannot separate a same-owner restructuring from a real sale. See
> [`deed-gate-review.md`](deed-gate-review.md) for the measured tradeoff and a candidate refinement.

All figures re-verified against the live `justfixwow` schema + ACRIS (`real_property_*`) + the
discovery graph on **2026-09-16**. Re-verify vintage before citing.

## The headline

**Ten** identical 4-unit townhouses on one Flushing block (41-09 → 41-27 Haight Street, Queens; block
5063, all built 2015) — bought together on a single 2020 deed, then mostly sold off one at a time.
WoW never saw a connection; WatchlineNYC saw the bulk deed but now (correctly) declines to assert one
owner over priced resales:

| | Grouping | Why |
|---|---|---|
| **Who Owns What** | **6** portfolios over 9 buildings (5 singletons + a 4-building one) | nothing it can see |
| **WatchlineNYC (pre-gate)** | 1 owner group (`OG-51705`, 9 of 10) | the bulk deed + linked-successor recovery, **ungated** |
| **WatchlineNYC (current, gated)** | **0** — every parcel a singleton | the onward deeds are market-price sales; the nominal gate declines them |

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
  all ten parcels on a single deed** (`documentid 2020092500293001`) — to one buyer,
  **41 HAIGHT STREET TOWNHOUSE OWNER, LLC** (17770 Castleton St, City of Industry, **CA**), for
  **$18,600,000**.
- **2021–2024** — that acquisition LLC then **re-deeds nine of the ten parcels, one at a time, each
  into its own differently-named LLC**, grantor on every one = the acquisition LLC, but at **recorded
  market prices**, not nominal consideration: $1,600,000 (41-19 → `41-19 LIYANG INC.`), $2,575,625
  (41-13 → `AVERY AVENUE 168 LLC`), $2,500,000, $2,490,118, $2,337,662, $2,581,875, $2,500,000, and so
  on — every onward deed four orders of magnitude above the ~$0 a shell-restructuring records. (41-25
  saw a further 2024 transfer `PAWS 138 LLC` → `41 HAIGHT GROUP LLC`, $2,790,000.)
- **41-27** (bbl `4050630045`) was never re-deeded — it still sits under the original acquisition LLC,
  the only parcel still resting on the 2020 bulk deed.

So the surface — six head-officer names, nine owner-of-record LLCs — has **two readings that the deed
record cannot tell apart**: a same-owner restructuring that happened to record transfer prices, *or* a
bulk buyer who genuinely **sold most of the block** to independent owners. The prices point toward the
latter for at least part of the set; the registrations are genuinely mixed (see below).

## Why WatchlineNYC now declines it — the linked-successor guard, gated

The linked-successor guard in `deed_edges.py` (`_restructured_groups`) exists to recover exactly this
shape: a joint grantee (the acquisition LLC) that is later the **grantor** re-deeding each parcel into
its own **shell** LLC (globally the grantee of ≤3 buildings). Pre-gate, it re-merged the nine re-deeded
Haight parcels into `OG-51705` on that pattern alone.

But that pattern is **also** what a bulk buyer selling houses off one at a time produces — same grantor
chain, same small successor LLCs — and the only thing on the record that separates the two is the
**consideration**. Commit `5f51475` added the nominal-consideration gate: the restructuring branch
fires only when the successor deed's `docamount <= NOMINAL_MAX` ($100). Every Haight onward deed is
$1.6M–$2.8M, so **the gate rejects all nine**. Only 41-27 still rests on the bulk deed; a single
retained parcel is not a clique (needs ≥2), so the bulk deed drops out too. Result on current data:

```
# neo4j discovery graph, 2026-09-16
MATCH (og:OwnerGroup {owner_group_id:'OG-51705'}) RETURN count(og)   -> 0   (group gone)
MATCH (b:Building) WHERE b.bbl IN [the 10 Haight bbls]
OPTIONAL MATCH (a:Actor)-[:REGISTERED_FOR]->(b)-[]->()
OPTIONAL MATCH (a)-[:IN_OWNER_GROUP]->(og) RETURN b.bbl, collect(og.owner_group_id)
  -> every bbl: []   (no 41 Haight building is in any owner group)
```

This is the **correct precision call, at a real recall cost**. The guard cannot know whether John Jun
Xu reorganized his own holdings and booked transfer prices, or whether he sold the block; the price
says "sale" and the gate believes the price. What the registrations show is a genuinely **mixed** set,
not a clean single owner:

| Building | latest-deed grantee (ACRIS) | HPD head officer | HPD owner-of-record |
|---|---|---|---|
| 41-27 (`…045`, held) | 41 HAIGHT STREET TOWNHOUSE OWNER LLC | **John Jun Xu** | 41 HAIGHT STREET TOWNHOUSE OWNER LLC |
| 41-25 (`…046`) | 41 HAIGHT GROUP LLC | **John Jun Xu** | 41 HAIGHT STREET TOWNHOUSE OWNER LLC |
| 41-19 (`…049`) | 41-19 LIYANG INC. | **John Jun Xu** | 41 HAIGHT STREET TOWNHOUSE OWNER LLC |
| 41-13 (`…052`) | AVERY AVENUE 168 LLC | **John Jun Xu** | 41 HAIGHT STREET TOWNHOUSE OWNER LLC |
| 41-21 (`…048`) | 888 HAIGHT LLC | Shi Lin | 888 HAIGHT LLC |
| 41-17 (`…050`) | C & L 17 FAMILY LLC | Jane Chan | C&L 17 Family LLC |
| 41-15 (`…051`) | 4115 HAIGHT ST INC. | Zhifeng Chen | 4115 HAIGHT ST INC |
| 41-11 (`…053`) | HT ELEVEN REALTY LLC | Nicole Ho | HT ELEVEN REALTY LLC |
| 41-09 (`…055`) | NEW YUN REALTY LLC | Yun Li | NEW YUN REALTY LLC |

So **four** parcels (41-27/25/19/13) still register to **John Jun Xu** — three of them *still under the
acquisition LLC as owner-of-record* despite the market-price deeds, which reads like a retained set —
while the other **five** register to five different individuals, which reads like real sales. Whether
Xu's four are "one owner" is precisely the **§3 restructuring-vs-sale adjudication** question the
automated gate deliberately cannot answer; the price-only gate resolves it conservatively by declining
the whole set. A shared-principal refinement (re-include a market-price successor whose HPD head officer
matches a held parcel of the same joint deed) would recover *just Xu's set* — 41-27 held + 41-19 + 41-13
— and leave the five distinct-registrant parcels split; see [`deed-gate-review.md`](deed-gate-review.md).

WoW never reaches any of this by tuning: it has no deed edge to begin with, and no registration snapshot
can express "these ten were one purchase in 2020." The deed signal *can* see the shared origin — it just,
correctly, will not upgrade "shared origin + priced resale" to "same current owner" without a human.

## The tenth townhouse (41-23) — a second, independent recall gap

Even under the *pre-gate* grouping, one parcel never made it in: **41-23 Haight Street** (bbl
`4050630047`) — same 4-unit 2015 build, mid-row, on the 2020 bulk deed and re-deeded from the
acquisition LLC into its own LLC (`41-23 L&Y INC.`, 2022-12-21, $1.6M), exactly like its neighbours.

It drops out for a **structural** reason independent of the consideration gate: **41-23 has no HPD
registration at all** (verified — zero rows in `hpd_registrations`; in the graph it is only a `Building`
with no `Actor`). Owner groups are built over **landlord/actor nodes** — `deed_edges` maps each
co-conveyed building to a node to form its clique — so a building with no node has nothing for the deed
edge to attach to. It is also in **no** WoW portfolio (WoW is entirely registration-based). So 41-23
slips through **both** systems for lack of a registration, on top of the whole set now dropping for
lack of nominal consideration — two different recall gaps stacked on one parcel. The map
(`docs/maps/haight.html`) shows it as a ghosted "in neither system" dot, mid-row.

**Architecture takeaway:** the deed veil-pierce can only reunite buildings that carry a landlord node; a
registration-less building is beyond its reach — a real recall limit worth stating, not hiding. (Noted in
`watchline/discovery/ingest/portfolio/CLAUDE.md`.) The consideration gate then adds a *second*,
price-based recall limit on top — the subject of this case as re-framed.

## Caveats — a lead, not a verdict

- **Shared origin, mixed present ownership — no proof of one current beneficial owner.** A single
  bankruptcy purchase and a consistent grantor (the acquisition LLC) re-deeding each parcel are strong
  **common-origin** signals. But the onward deeds carry **market prices** (~$1.6M–$2.8M) and the
  registrations split into **five different individuals** plus a four-parcel John-Jun-Xu set, so most of
  the block reads as genuine individual sales, not intra-owner SPE restructuring. The deed history says
  *"these ten share one 2020 origin"* — it does not adjudicate present beneficial ownership, and the
  price gate correctly refuses to. An investigator verifies from here (LLC filings, financing, management
  overlap); the Xu-registered four (41-27/25/19/13) are the strongest common-control sub-lead.
- **The earlier "9 of 10 reunited (OG-51705)" claim was an ungated artifact** and is retracted — see the
  status note up top. It rested on the linked-successor guard firing without a consideration check.
- Owner-group membership and apparent control are **Type II** inferences; the deed, its parties, prices,
  and the HPD/DOF owner-of-record are directly **sourced** (ACRIS / HPD).

## Reproduce

Read-only. Vintage **2026-09-16** (`justfixwow` + discovery graph). All queries use the current
`real_property_*` ACRIS tables (not the stale `acris_real_property_*` 2013 load).

```python
# 1) CURRENT graph outcome: OG-51705 is gone; no Haight bbl is in any owner group.
#    MATCH (og:OwnerGroup {owner_group_id:'OG-51705'}) RETURN count(og)   -> 0
#    MATCH (b:Building) WHERE b.bbl IN [the 10 bbls]
#      OPTIONAL MATCH (a:Actor)-[:REGISTERED_FOR]->(b) OPTIONAL MATCH (a)-[:IN_OWNER_GROUP]->(og)
#      RETURN b.bbl, collect(DISTINCT og.owner_group_id)   -> every bbl: []

# 2) The bulk deed (ACRIS, Postgres) — count ALL legals on the document: TEN parcels.
#    SELECT documentid, count(DISTINCT btrim(bbl)) FROM real_property_legals
#      WHERE documentid='2020092500293001';
#    -> 2020092500293001 · 2020-09-14 · $18,600,000 · 10 parcels.
#    Parties: grantor = "GREGORY MESSER, ESQ., AS CHAPTER 11 TRUSTEE";
#             grantee = "41 HAIGHT STREET TOWNHOUSE OWNER, LLC" (City of Industry, CA).

# 3) The onward deeds are MARKET-PRICE, not nominal — why the gate declines them.
#    Each parcel's LATEST deed (DISTINCT ON (bbl) ... ORDER BY docdate DESC) joined to parties+docamount
#    -> 9 parcels re-deeded 2021-2024 FROM the acquisition LLC at $1.6M-$2.79M into differently-named
#       LLCs; only 41-27 (4050630045) still rests on the 2020 bulk deed. Every docamount >> NOMINAL_MAX
#       ($100), so _retained()'s restructuring branch fires for none of them.

# 4) The registrations are MIXED — four parcels still register to JOHN JUN XU (three still under the
#    acquisition LLC as HPD owner-of-record), five to five different people:
#    SELECT r.bbl, ct.firstname, ct.lastname, ct.corporationname
#      FROM hpd_registrations r JOIN hpd_contacts ct ON ct.registrationid=r.registrationid
#      WHERE r.bbl LIKE '4050630%' AND ct.type IN ('HeadOfficer','CorporateOwner');

# 5) 41-23 (bbl 4050630047) — the registration-less parcel: 0 rows in hpd_registrations -> no node
#    (was on the bulk deed + re-deeded 2022-12-21 -> 41-23 L&Y INC., $1.6M; in NEITHER system).
```

## The quartet — one message, four mechanisms (and one honest limit)

- [`case-escobar.md`](case-escobar.md) — **merge** what WoW split (owner identity, one address typo).
- [`case-miller.md`](case-miller.md) — **un-merge** what WoW conflated on a shared **address** (nexus ≠ owner).
- [`case-levitov.md`](case-levitov.md) — **un-merge** on a shared **manager** (management ≠ owner).
- **The deed veil-pierce, both faces:**
  - [`case-citadel.md`](case-citadel.md) — the **payoff**: 15 buildings re-titled into 12 shells **at
    $0**, reunited on the deed alone (`OG-67966`, `deed_only`) — the recovery the gate *admits*.
  - `case-haight.md` (this file) — the **limit**: the same shape, but the onward conveyances are
    **priced resales**, so "shared origin" cannot be upgraded to "same current owner" on the record
    alone. The consideration gate declines it — precision over recall.

Together: the owner-identity layer is *precision-first* and reads evidence WoW does not — it keeps *who
owns* separate from *who operates through this office* and *who manages the building*, and it can see the
transaction record that a registration snapshot cannot. Escobar/Miller/Levitov show it deciding well on
signals WoW **has**; Haight shows both that it can *see* a question WoW cannot ask **and** where it
correctly declines to answer that question without a human (the §3 restructuring-vs-sale adjudication).
