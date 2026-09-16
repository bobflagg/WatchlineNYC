# Case study — 43-58 & 43-60 164th Street (the deed veil-pierce that beats *real* WoW)

The positive companion to [`case-haight.md`](case-haight.md), and part of the series with
[`case-escobar.md`](case-escobar.md), [`case-miller.md`](case-miller.md), and
[`case-levitov.md`](case-levitov.md). Haight is the deed signal's **limit** — a bulk buy whose onward
conveyances were priced resales, so the consideration gate (correctly) declines to call it one owner.
This case is the deed signal's **payoff**: a bulk buy the owner never sold, only re-titled into two
single-purpose shells **at $0** — reunited on the deed alone, and it is the *only* thing that reunites
them, because **JustFix Who Owns What genuinely splits them into two unrelated portfolios.**

> **Verification standard (read first).** A positive "false-split" example must be checked against the
> **live JustFix `wow.wow_portfolios`** table — *not* the discovery graph's own `Portfolio` nodes.
> WatchlineNYC's `Portfolio` layer masks aggregator addresses (landlord-degree > 25); real WoW does not.
> A group can look split in our `Portfolio` layer yet be one big lump in real WoW. The gate this case
> passes: the members land in **≥2 distinct real WoW `orig_id`s, none an aggregator lump**. (See the
> Citadel counter-example at the bottom — a genuine deed recovery that *fails* this gate.)

All figures verified against the live `justfixwow` schema (`real_property_*`, `wow.wow_portfolios`,
`hpd_*`) + the discovery graph on **2026-09-16**. Read-only.

## The headline

Two adjacent Flushing row houses — **43-58 and 43-60 164th Street** (Queens; block 5421, lots 59 & 61)
— were bought together in 2015 by **`AXL HOME LLC`**, which in 2019 re-deeded each into its own
single-purpose LLC **at $0**. Today they register to two different people at two different addresses, and
JustFix WoW files them under two **unrelated** owners. WatchlineNYC reunites them on the deed alone:

| | Grouping | What connects them |
|---|---|---|
| **JustFix Who Owns What** | **2** unrelated portfolios — `orig_id 14133` (Brian Lin, 1 building) and `orig_id 55695` (Xianglian Wang + Rong Chen + Kong Chen, 3 buildings) | nothing it can see |
| **WatchlineNYC** | **1** owner group (`OG-15928`), the 2 landlord nodes joined by a `CONNECTED_BY_DEED` edge | a single 2015 ACRIS deed + the $0 restructuring |

WoW splits them because the two registrations share **nothing** it keys on: different head officers
(Brian Lin vs Xianglian Wang), different single-purpose LLCs (`BRIDGEWOOD DEVELOPMENT LLC` vs
`HONG LI GROUP LLC`), and **different registration addresses** (43-58 164th St vs 254-10 57th Ave — so
not even an aggregator lumps them). There is no shared name, address, or Splink link — pure `deed_only`.

## What actually connects them — one deed, then a $0 split

- **2015-11-24** — `AXL HOME LLC` takes title to **both** houses on **one deed**
  (`documentid 2015120200784001`, **$1,200,000**, 2 parcels), bought from the Cherot family estate
  (`CHEROT, JUANITA R.` / `CHEROT, DECEASED, LAWSON L.`).
- **2019-09-19** — on a **single day**, AXL re-deeds each house into its own single-purpose shell, grantor
  on both = `AXL HOME LLC`, **both at $0**:
  - 43-58 164th St (`4054210059`) → `BRIDGEWOOD DEVELOPMENT LLC` (`2019092001164001`, $0) — HPD head
    officer **Brian Lin**
  - 43-60 164th St (`4054210061`) → `HONG LI GROUP LLC` (`2019092001137001`, $0) — HPD head officer
    **Xianglian Wang**

So the two-owners surface is a **restructuring of one bulk purchase**: buy the pair together, then split
title into two single-purpose shells registered to two different individuals. It is the shell game's
signature move — and here, unlike Haight, the record proves it is **not** a sale: **the consideration is
$0 on both re-deeds**, so these are re-titlings within one hand, not arms-length sales to independent
buyers.

## How WatchlineNYC catches it — `CONNECTED_BY_DEED` + the linked-successor guard

The owner-identity layer reunites the two landlord nodes into `OG-15928`, wired **purely by deed**: one
`CONNECTED_BY_DEED` edge (`method='acris-deed'`), and zero `CONNECTED_BY_NAME` / `_ADDRESS` / `_SPLINK`.
Composition = **`deed_only`**.

The recovery runs entirely through the **linked-successor guard** (`_restructured_groups` in
`deed_edges.py`). Neither house is "held since" the 2015 purchase — each now has a newer 2019 latest deed
— so the staleness rule alone would strand both as singletons. The guard recovers them because for each
it sees the joint grantee of the 2015 deed (`AXL HOME LLC`) as the **grantor** of the 2019 re-deed, the
successor as a **shell** (globally the latest grantee of ≤ `SUCCESSOR_MAX` = 3 buildings), **and the
onward consideration nominal** (`docamount = 0 <= NOMINAL_MAX = $100`). All three conditions hold, so the
2015 deed maps to a 2-node clique.

**This is the case that justifies the nominal-consideration gate rather than being blocked by it.** The
same guard, on the same shape, declines Haight — because Haight's onward deeds were $1.6M–$2.8M, not $0.
AXL passes precisely because it is what the guard is calibrated to admit: a same-owner restructuring
recorded at nominal consideration. Remove `CONNECTED_BY_DEED` and this owner group ceases to exist, and
**real WoW never reaches it** — it has the two houses in two unrelated portfolios and no registration
snapshot can express "these two were one 2015 purchase, re-papered into two shells four years later."

## Caveats — a strong lead, still Type II

- **$0 restructuring, distinct registrants — same-owner is the inference, not proof.** The single-grantor
  chain and **$0 consideration** on both re-deeds make same-hand restructuring the leading read (materially
  stronger than Haight, whose priced resales left it open). But two *different* registered people (Lin,
  Wang) after a $0 split could also be a **partition between two partners** — the same ambiguity §3's
  "restructuring vs. sale" check exists to resolve. The nominal price favors restructuring; it does not
  settle beneficial ownership. Owner-group membership is **Type II**; the deed, its parties, and the $0
  amounts are directly **sourced** (ACRIS) — **Type I**.
- The recovery mechanism and its measured precision/recall are in
  [`deed-gate-review.md`](deed-gate-review.md); the adjudication frame is
  [`eval-protocol.md`](eval-protocol.md) §3.

## Counter-example — why *not* Citadel (compare against real WoW, never the `Portfolio` layer)

An earlier draft of this case used **Citadel Estates** — `CITADEL ESTATES LLC` bought 15 Brooklyn
buildings on one 2008 deed ($58.4M) and re-deeded each into a Grateful-Dead-named shell at $0
(`RIPPLE EP LLC`, `SCARLET BEGONIAS LLC`, `STELLA BLUE REALTY LLC`, …), reunited as `OG-67966`,
`deed_only`, across three registrants (Leroy Forde / Michael Roth / Thomas Forde). The deed clique and
the $0 restructuring are **genuine**. But Citadel is **not** a WoW false-split, and it fails the gate
above:

- Against the graph's own `Portfolio` nodes, Citadel looks split three ways — but that is because
  WatchlineNYC **masks** the aggregator address the three registrants share.
- Against real WoW, **all 15 Citadel bbls are in ONE portfolio** (`orig_id 161`, 83 buildings, 33
  landlords). Root cause: all three registrants file at **`1330 EASTERN PARKWAY 6A`**, a 33-landlord
  aggregator address; real WoW merges on it (it does not mask aggregators), lumping Citadel together with
  ~30 unrelated landlords and 68 stranger buildings.

So relative to real WoW, Citadel is a WoW **over-lump**, not a deed false-split — the deed recovery is
right, but the WoW comparison it was written up against was wrong. **The lesson this case encodes: score
positive deed recoveries against `wow.wow_portfolios`, and beware that the shell operators most worth
catching often share one registration address — which lumps them in real WoW rather than splitting
them.** The clean false-splits the deed uniquely fixes (like AXL) tend to be the ones where the operator
spread the shells across *different* registration addresses.

## Reproduce

Read-only. Vintage **2026-09-16** (`justfixwow` + discovery graph; `real_property_*` ACRIS tables).

```sql
-- 1) The gate: members land in >=2 distinct real WoW portfolios, neither an aggregator lump.
WITH member_bbls(bbl) AS (VALUES ('4054210059'),('4054210061'))
SELECT m.bbl, p.orig_id AS wow_portfolio, array_length(p.bbls,1) AS wow_pf_size,
       array_length(p.landlord_names,1) AS n_landlords
FROM member_bbls m LEFT JOIN wow.wow_portfolios p ON m.bbl = ANY(p.bbls) ORDER BY m.bbl;
--  -> 4054210059 : orig_id 14133, size 1 (Brian Lin);  4054210061 : orig_id 55695, size 3 (Wang/Chen/Chen)
--     two distinct orig_ids, neither an aggregator  => PASS
```

```sql
-- 2) The mechanism: one 2015 bulk deed to AXL HOME LLC, then two $0 same-day re-deeds into shells.
SELECT btrim(l.bbl) AS bbl, m.documentid, m.docdate, m.docamount,
  (SELECT string_agg(DISTINCT name,'|') FROM real_property_parties WHERE documentid=m.documentid AND partytype=1) AS grantor,
  (SELECT string_agg(DISTINCT name,'|') FROM real_property_parties WHERE documentid=m.documentid AND partytype=2) AS grantee
FROM real_property_master m JOIN real_property_legals l ON l.documentid=m.documentid
WHERE m.doctype ILIKE '%DEED%' AND btrim(l.bbl) IN ('4054210059','4054210061')
ORDER BY btrim(l.bbl), COALESCE(m.docdate,m.recordedfiled);
--  -> 2015 CHEROT estate -> AXL HOME LLC ($1.2M, 2 parcels); 2019 AXL -> BRIDGEWOOD ($0) / HONG LI GROUP ($0)
```

```
-- 3) The graph: one deed-only owner group over the two landlord nodes.
--    MATCH (a)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:'OG-15928'}),
--          (c)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id:'OG-15928'})
--    WHERE id(a)<id(c) MATCH (a)-[r]-(c) WHERE type(r) STARTS WITH 'CONNECTED_BY'
--    RETURN type(r), count(*)   -> CONNECTED_BY_DEED: 1  (nothing else)
```

## The series — four mechanisms, and the deed signal's two faces

- [`case-escobar.md`](case-escobar.md) — **merge** what WoW split (owner identity, one address typo).
- [`case-miller.md`](case-miller.md) — **un-merge** what WoW conflated on a shared **address**.
- [`case-levitov.md`](case-levitov.md) — **un-merge** on a shared **manager** (management ≠ owner).
- **The deed veil-pierce, both faces:**
  - `case-axl.md` (this file) — **merge** what real WoW splits: two houses bought together, re-titled
    into two shells **at $0**, filed by WoW under two unrelated owners — the recovery the consideration
    gate *admits*, verified against `wow.wow_portfolios`.
  - [`case-haight.md`](case-haight.md) — the **limit**: the same shape, but re-deeded at **market
    prices**, so the gate declines it — precision over recall, the question left to a human.
