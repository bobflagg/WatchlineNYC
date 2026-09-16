# Case study — Citadel Estates (the deed veil-pierce that *works* — 15 buildings, 12 shells, one owner)

The positive companion to [`case-haight.md`](case-haight.md), and part of the series with
[`case-escobar.md`](case-escobar.md), [`case-miller.md`](case-miller.md), and
[`case-levitov.md`](case-levitov.md). Haight is the deed signal's **limit** — a bulk buy whose onward
conveyances were priced resales, so the consideration gate (correctly) declines to call it one owner.
Citadel is the deed signal's **payoff**: a bulk buy the owner never sold, only re-titled into a fleet
of single-purpose shells **at $0** — so the linked-successor recovery reunites it, and it is the
*only* thing in the graph that can. Same machinery; opposite, correct verdicts. The discriminator is
the one the gate reads: **consideration**.

All figures verified against the live `justfixwow` schema + ACRIS (`real_property_*`) + the discovery
graph on **2026-09-16**. Read-only. Re-verify vintage before citing.

## The headline

In 2008, **`CITADEL ESTATES LLC` bought fifteen Brooklyn buildings on a single deed** for **$58.4M**,
then re-deeded each one into its own **single-purpose LLC named after a Grateful Dead song — at $0**.
The fifteen buildings register today under **three different people** and sit in **three different Who
Owns What portfolios**; nothing WoW keys on ties them together. WatchlineNYC reunites all three into one
owner group on the deed alone:

| | Grouping | What connects them |
|---|---|---|
| **Who Owns What** | **3** portfolios (Leroy Forde / Michael Roth / Thomas Forde), the 15 buildings split across them | nothing it can see |
| **WatchlineNYC** | **1** owner group (`OG-67966`), the 3 landlord nodes in a complete clique | a single 2008 ACRIS deed |

WoW splits the set three ways because the registrations share **nothing** it keys on: three different
head-officer names and **twelve differently-named single-purpose LLCs**. There is no shared name, no
shared registration address, no fuzzy identity link — this is the pure veil-pierce, `deed_only`
composition, exactly what Haight was originally (and wrongly) reported to be.

## What actually connects them — one deed, then a $0 restructuring

- **2008-07-15** — `CITADEL ESTATES LLC` takes title to **fifteen** buildings on one deed
  (`documentid 2008072300342001`, **$58,400,000**), bought out of fifteen numbered seller LLCs
  (`1006-22 REALTY LLC`, `1110 REALTY LLC`, `1505 REALTY LLC`, … `636 REALTY LLC`) — a portfolio
  assemblage.
- **2015-05-01** — Citadel re-deeds **each parcel into its own single-purpose shell**, grantor on every
  one = `CITADEL ESTATES LLC`, and **every onward deed is recorded at $0** — a pure intra-owner
  restructuring, not a sale. The shells are a Deadhead's roll-call:

  | Shell LLC (successor) | Building(s) | HPD head officer |
  |---|---|---|
  | `RIPPLE EP LLC` | 371 & 348 Eastern Pkwy | Leroy Forde |
  | `FRANKLIN'S TOWER 26 LLC` | 426 Eastern Pkwy | Leroy Forde |
  | `MORNING DEW 18 LLC` | 1655 / 1602 / 1608 Union St | Leroy Forde |
  | `SCARLET BEGONIAS LLC` | 322 Rockaway Pkwy | Leroy Forde |
  | `SUNRISE 57 LLC` | 59 St Pauls Pl | Leroy Forde |
  | `HALF STEP 36 LLC` | 1022 E 36th St | Leroy Forde |
  | `PICASSO MOON 72 LLC` | 1517 Ocean Ave | Leroy Forde |
  | `ETERNITY 11 LLC` | 1110 Flatbush Ave | Michael Roth |
  | `BIRD SONG 18 LLC` | 467 E 23rd St | Michael Roth / Thomas Forde |
  | `BLUE MOON 24 LLC` | 2401 Newkirk Ave | Thomas Forde |
  | `STELLA BLUE REALTY LLC` | 2415 Newkirk Ave | Thomas Forde |
  | `SUGAREE LLC` | 636 E 21st St | Thomas Forde |

So the three-names / twelve-LLCs surface is a **restructuring of one bulk purchase** — buy the
portfolio together, then scatter title across single-purpose shells and register them under a few
different individuals. It is the shell game's signature move, and here — unlike Haight — the record
proves it: **the consideration is $0 on every transfer**, so these are re-titlings within one hand, not
sales to independent buyers.

## How WatchlineNYC catches it — `CONNECTED_BY_DEED` + the linked-successor guard

The owner-identity layer reunites the three landlord nodes into `OG-67966`, and the wiring is **pure
deed**: the three members form a **complete clique — 3 `CONNECTED_BY_DEED` edges (`method='acris-deed'`),
and zero `CONNECTED_BY_NAME` / `_ADDRESS` / `_SPLINK`**. Composition = **`deed_only`**: no identity
signal at all.

The recovery runs entirely through the **linked-successor guard** (`_restructured_groups` in
`deed_edges.py`). No parcel is "held since" the 2008 deed — every one has a newer 2015 latest deed — so
the staleness rule alone would strand all fifteen as singletons. The guard recovers them because for
each parcel it sees the joint grantee of the 2008 deed (`CITADEL ESTATES LLC`) as the **grantor** of the
2015 re-deed, the successor as a **shell** (globally the latest grantee of ≤ `SUCCESSOR_MAX` = 3
buildings), **and the onward consideration nominal** (`docamount = 0 <= NOMINAL_MAX = $100`). All three
conditions hold on all fifteen, so the guard re-includes them and the 2008 deed maps to a ≥2-node
clique.

**This is the case that justifies the nominal-consideration gate rather than being blocked by it.** The
same guard, on the same shape, declines Haight — because Haight's onward deeds were $1.6M–$2.8M, not $0.
Citadel passes precisely because it is what the guard is calibrated to admit: a same-owner restructuring
recorded at nominal consideration. Remove `CONNECTED_BY_DEED` and this owner group ceases to exist; WoW
never reaches it by any tuning, because no registration snapshot can express "these fifteen were one
2008 purchase, re-papered into twelve shells."

## Caveats — a strong lead, still Type II

- **Strong common-control, on the strongest deed evidence available.** One assemblage purchase, one
  consistent grantor (`CITADEL ESTATES LLC`) re-deeding every parcel, and **$0 consideration on every
  onward transfer** together make this about as clean a same-owner restructuring as the public record
  offers — materially stronger than Haight, whose priced resales left the question open. But
  owner-group membership and present beneficial ownership remain **Type II** inferences; the deed, its
  parties, and the $0 amounts are directly **sourced** (ACRIS) — **Type I**.
- **Three registrants, one owner is the inference, not a certainty.** Leroy Forde, Thomas Forde, and
  Michael Roth are three different people; the claim is that they operate one portfolio through Citadel's
  shells (the $0 grantor-chain is the basis), not that they are the same individual. An investigator
  confirms from LLC filings / management overlap; the shared registrant *surname* (Forde) and the
  common Citadel grantor are the leads.
- The nominal-consideration recovery is the mechanism; see [`deed-gate-review.md`](deed-gate-review.md)
  for its measured precision/recall and [`eval-protocol.md`](eval-protocol.md) §3 for the
  restructuring-vs-sale adjudication this case sits on the *recover* side of.

## Reproduce

Read-only. Vintage **2026-09-16** (`justfixwow` + discovery graph; `real_property_*` ACRIS tables).

```python
# 1) The owner group is deed-only: 3 members, 3 CONNECTED_BY_DEED edges, nothing else.
#    MATCH (a)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:'OG-67966'}),
#          (c)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:'OG-67966'})
#    WHERE id(a) < id(c) MATCH (a)-[r]-(c) WHERE type(r) STARTS WITH 'CONNECTED_BY'
#    RETURN type(r), count(*)   -> CONNECTED_BY_DEED: 3  (== C(3,2); nothing else)

# 2) WoW splits them: the 3 members map to 3 different WoW portfolios.
#    MATCH (n)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:'OG-67966'})
#    OPTIONAL MATCH (n)-[:MEMBER_OF]->(p:Portfolio) RETURN n.name, collect(p.portfolio_id)
#    -> LEROY FORDE / MICHAEL ROTH / THOMAS FORDE, three distinct PF-... ids.

# 3) The bulk deed (ACRIS, Postgres): fifteen parcels, $58.4M, grantee CITADEL ESTATES LLC.
#    SELECT documentid, count(DISTINCT btrim(bbl)) FROM real_property_legals
#      WHERE documentid='2008072300342001';   -> 15 parcels
#    parties: grantor = fifteen '... REALTY LLC' sellers; grantee = 'CITADEL ESTATES LLC'; $58,400,000.

# 4) The $0 restructuring: each parcel's LATEST deed is a 2015 CITADEL -> shell transfer at docamount 0.
#    DISTINCT ON (bbl) ... ORDER BY docdate DESC, joined to parties + docamount
#    -> 15 shells (RIPPLE EP, SCARLET BEGONIAS, STELLA BLUE REALTY, FRANKLIN'S TOWER 26, ...), all $0.
#       Every docamount <= NOMINAL_MAX ($100), so _retained()'s restructuring branch fires for all 15.
```

## The series — four mechanisms, and the deed signal's two faces

- [`case-escobar.md`](case-escobar.md) — **merge** what WoW split (owner identity, one address typo).
- [`case-miller.md`](case-miller.md) — **un-merge** what WoW conflated on a shared **address**.
- [`case-levitov.md`](case-levitov.md) — **un-merge** on a shared **manager** (management ≠ owner).
- **The deed veil-pierce, both faces:**
  - `case-citadel.md` (this file) — **merge** what WoW is blind to: fifteen buildings tied only by an
    ACRIS deed, re-titled into twelve shells **at $0** — the recovery the consideration gate *admits*.
  - [`case-haight.md`](case-haight.md) — the **limit**: the same shape, but re-deeded at **market
    prices**, so the gate declines it — precision over recall, the question left to a human.

Together: the owner-identity layer reads a transaction record WoW cannot, *and* it knows when that
record proves one owner (Citadel, $0) versus when it only proves a shared origin (Haight, priced). The
consideration gate is the line between the two.
