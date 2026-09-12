# Case study — Ramon Escobar (the "one typo, two portfolios" split)

A presentation- and paper-grade worked example of the merge WatchlineNYC gets
right that Who Owns What splits — driven by a single registration-address typo,
recovered by the ACRIS held-deed signal, and independently confirmed by a blind
human reviewer. Eval pair **P0012** (stratum `S1a_deed_held`, signal
`acris-deed`). A second owner sharing the name "Ramon Escobar" (a *different*
person) is a second WoW split by a *different* mechanism, and the two are
correctly kept apart — see **Same name, two owners** below for the full
recall-plus-precision story.

All figures below were pulled from the live JustFix `wow` schema, the PLUTO /
ACRIS / HPD records, and the discovery graph on **2026-09-05**. Re-verify vintage
before citing in anything dated.

## The headline

| | Portfolios | Buildings | Landlord label |
|---|---|---|---|
| **WatchlineNYC** | **1** (`PF-20260901T165123Z-77675`) | **26** | one Bronx portfolio |
| **Who Owns What** | **2** (`77821` + `77822`) | 2 + 24 | **both** "RAMON ESCOBAR @ 2432 GRAND CONCOURSE #504" |

WoW produces **two portfolios carrying the identical landlord name and business
address** and never joins them. WatchlineNYC keeps all 26 buildings together.

## The vivid detail — three neighbors, split down the middle

Three adjacent buildings on one Bronx block, all PLUTO-owned by Walton Cluster LP:

| BBL | Address | PLUTO owner | WoW portfolio |
|---|---|---|---|
| 2028070067 | **2031 Creston Ave** | WALTON CLUSTER LP | `77821` (2-bldg) |
| 2031600005 | **2064 Creston Ave** | WALTON CLUSTER LP | `77822` (24-bldg) |
| 2031600009 | **2070 Creston Ave** | WALTON CLUSTER L.P. | `77821` (2-bldg) |

WoW puts 2064 Creston in the big portfolio but its two immediate block-neighbors
(2031, 2070) in a separate one — even though **2031 and 2064 Creston sit on the
same 2000-12-28 multi-parcel deed** `NEIGHBORHOOD PARTNERSHIP HOUSING DEV FUND →
WALTON CLUSTER L.P.`

## Why WoW splits — the root cause

WoW builds portfolios from the HPD registration-contact graph (shared
name+address edges). Portfolio `77821` carries two contact variants:

- `RAMON ESCOBAR @ 2432 GRAND CONCOURSE 504, BRONX NY`
- `RAMON ESCOBAR @ 2432 GRAND **COURSE** 504, BRONX NY`   ← dropped "CON"

The mistyped address (`GRAND COURSE`) is a distinct node in the connection graph,
so the two Creston buildings fail to link to the 24-building cluster. The wider
HPD record for this owner is full of the same class of noise: `RAMON ESCOBAR` /
`RAMOS ESCOBAR` / `RAMON E`; `2432 GRAND CONCOURSE` / `GRAND CONCOURS` / `GRAND
COCNOURSE`; city as `Bronx` / `BX` / `White Plains`. Registration-string matching
is brittle against exactly this.

### The full variant family — one office recorded ~a dozen ways

Pulled fresh from HPD `hpd_contacts` (2026-09-12): across the 26 buildings, every
`RAMON ESCOBAR` registration resolves to a **single Bronx office — 2432 Grand Concourse,
Suite 504, Bronx NY 10458** — but the raw record enters that one address in a whole *family*
of inconsistent keys, and WoW's exact-address matching shatters on each. The street/apartment
spellings actually on file for this owner:

| As filed | The corruption |
|---|---|
| `2432 GRAND CONCOURSE 504` | canonical |
| `2432 GRAND CONCOURS 504` | dropped **E** |
| `2432 GRAND COURSE 504` | dropped **CON** — the headline typo (on building `2031600009`) |
| `2432 GRAND COCNOURSE 504` | transposed letters |
| `2432 GRAND CONCOURSE` | apartment (`504`) dropped |
| `105 SHERMAN AVENUE` | a stray, unrelated address |
| *(blank)* | no address filed |

And even the *canonical* spelling fractures further on **city** (`BRONX` / `Bronx` / `BX` /
`White Plains` / even `GRAND CONCOURSE` filed as the city) and **ZIP** (`10458` / `10459` /
`10607`) — each distinct combination its own node in WoW's connection graph, and a single
building often carries several of these across its registration history. So "the typo" is really
a *dozen-way smear* of one office; `GRAND COURSE` is merely the variant the headline names.
WatchlineNYC is immune because it never keys on the registration string: the name-anchored Splink
model, the exact-legal-name `registered-llc` edge, and the **name-free** ACRIS deed all bridge
across every one of these forms — which is why the three landlord nodes (`ACT-LL-93014` plus the
two split-off singletons `ACT-LL-93013` and `ACT-LL-93015`) collapse into one owner group
(`OG-93013`).

### The precise mechanism — an exact-ZIP gate meets a *missing* ZIP

Under the variant noise sits a sharper cause. WoW's `landlords_with_connections` builds a node per
unique `(name, standardized street, apt, ZIP)` tuple, and **both** of its edge rules hard-require an
exact ZIP match:

- **name edge** — exact name **and equal ZIP** and street trigram-similarity > 0.9 (or > 0.8 with the
  same apartment number);
- **address edge** — *exact* street **and equal ZIP** and compatible apartment.

The three `RAMON ESCOBAR` nodes, as WoW standardized them (`wow_landlords`):

| Node | building | street | apt | ZIP |
|---|---|---|---|---|
| `ACT-LL-93014` (24) | canonical | `2432 GRAND CONCOURSE` | 504 | `10458` |
| `ACT-LL-93013` (1) | 2031 Creston | `2432 GRAND CONCOURSE` | 504 | *(empty)* |
| `ACT-LL-93015` (1) | 2070 Creston | `2432 GRAND COURSE` (typo) | 504 | *(empty)* |

- **93014 ↔ 93013** is *byte-identical* on name, street and apartment — the **only** difference is the
  ZIP (`10458` vs empty), and the ZIP gate alone fails both rules. A *missing ZIP*, not the typo,
  exiles the correctly-spelled 93013 from the 24-building node.
- **93014 ↔ 93015** fails twice over — the ZIP mismatch **and** the `GRAND COURSE` typo breaking the
  address rule's *exact*-street requirement.
- **93013 ↔ 93015** connect only because `'' = ''`: two *empty* ZIPs pass the very gate that excludes
  93014, and then the name rule fires on street-similarity ≈ 0.86 (> 0.8) with a matching apartment.
  That reproduces the `CONNECTED_BY_NAME` weight exactly: **`3.54 = (0.86 + 0.5 + 1) × 1.5`**
  (street-sim + apt-bonus + base, × the name-weight multiplier).

The Creston registrations standardized to a **blank ZIP** because their raw records carried
inconsistent city/ZIP noise (`White Plains`, `10607`, `10459`) the geocoder couldn't resolve to a clean
Bronx ZIP. So "the typo" is the headline, but the operative fracture is **brittle exact-key matching
meeting a missing key** — WoW joins nothing across a ZIP mismatch. Watchline's identity edges (the
Splink model, `registered-llc`, and the deed) don't read the ZIP field at all, so none of this reaches
them.

## Why WatchlineNYC gets it right

The `acris-deed` signal keys on **recorded ACRIS conveyances**, not on
registration spelling. 2031 Creston is one parcel of a held multi-parcel deed to
Walton Cluster L.P. that also covers buildings in the 24-building cluster, so the
deed signal binds it in regardless of the registration typo. The registration
noise that fractures WoW simply isn't in the deed signal's path.

## How a blind reviewer confirms it (eval P0012)

The reviewer never sees the system's answer. They see Entity A (Ramon Escobar, 1
building) vs Entity B (Ramon Escobar, 24 buildings) and must find the link in the
primary records:

- **T1 deed chain** — A's 2031 Creston shares the identical 2000-12-28 Walton
  Cluster L.P. deed with B's 2064 Creston and 2349 Jerome. Dispositive on its own.
- **T3 HPD** — Ramon Escobar is HeadOfficer/Shareholder of Walton Cluster,
  Melrose Cluster, Rae Findlay, CE Hunts Point and Jefferson/3531, all run from
  2432 Grand Concourse.

Verdict: **SAME**, tiers **T1 + T3** → **cross-source corroborated (C1)**, counts
toward *strict* precision. The deed-only hard gate does **not** fire (SAME does
not rest on T1 alone). Distractors to read past: two irrelevant DOS hits
(`CONTACT REALTY` / `SHIMON REALTY` — false-positive name resolutions) and OCR
garble in the 1970s–80s in-rem deed rows.

## The teaching arc (why this example is strong)

1. **It looks like a trap** — same common name on both sides — but is a genuine,
   well-corroborated match. Discipline: verify the record, don't pattern-match the
   name.
2. **The failure is a one-character data-entry error**, and it produces two WoW
   portfolios with the *same* name and address. Concrete, non-abstract, hard to
   argue with.
3. **The reviewer upgrades the evidence class** the pipeline couldn't: the system
   linked on the deed (T1); the human independently corroborates on HPD (T3),
   turning a deed-only (C2) candidate into a cross-source (C1) confirmation —
   exactly what the human-in-the-loop is for.

## Same name, two owners — and WoW splits the second one too

The name "Ramon Escobar" resolves to **two distinct portfolios** in the KG — and
they are **two different people**, correctly kept apart:

| Watchline portfolio | Bldgs | Where | Who |
|---|---|---|---|
| `PF-…-77675` | 26 | Bronx | Ramon Escobar @ 2432 Grand Concourse (the case above) |
| `PF-…-44544` | 12 | Manhattan / Bronx / Bklyn / Queens | an **Escobar + Espinal** partnership @ PO Box 370 (Manhattan) / 374 McLean Ave (Yonkers) |

Different addresses, different co-principals, no BBL overlap. A naïve name match
would fuse them into a bogus 38-building "Ramon Escobar"; WatchlineNYC does not —
linkage rests on deeds and the shared registration/address nexus, never the name
string. **That is the precision half of the story.**

And the second owner is *another* WoW split — by a **different mechanism**:

| WoW portfolio | Bldgs | Landlords on the registrations | Business address |
|---|---|---|---|
| `#50057` | 8 | RAMON ESCOBAR, JOSE ESPINAL | **PO BOX 370, Manhattan** |
| `#44728` | 4 | RAMON ESCOBAR, JOSE ESPINAL, Levites, Rettner | **374 McLean Ave, Yonkers** |

Here the fracture isn't a typo but **two legitimate business addresses** (a
Manhattan PO box and a Yonkers street address) for the *same* principals — so
WoW's name+address graph never joins them. WatchlineNYC merges all 12.

**Why that merge is sound (not an over-merge)** — two checks:

- *Signals.* The 12 landlords are joined by **four** corroborating edge types, not
  one: `CONNECTED_BY_ADDRESS` (7 edges), `acris-deed` (3 — including an
  Escobar↔Espinal co-grantee deed), `registered-llc` (3), and the Fellegi-Sunter
  model (1).
- *Principals.* In the HPD owner-role records, **Jose Espinal appears on 10 of the
  12 buildings and Ramon Escobar on 6**, recurring across *both* business
  addresses — one operation under two registration addresses, not a name-based
  guess.

### The combined lesson (one name, three phenomena)

- **Recall, case A** — merges the Bronx Escobar's 26 (WoW: 24 + 2).
- **Recall, case B** — merges the Escobar/Espinal 12 (WoW: 8 + 4).
- **Two different fracture mechanisms** — an address *typo* (A) and *two distinct
  addresses* for shared principals (B).
- **Precision** — the two unrelated Escobars are kept apart despite the identical
  name.

Together these pre-empt the obvious objection — *"aren't you just merging on
names?"* — on the very name that would seem to invite it.

## Which signal to trust — edge-reliability ranking

Both Escobar cases were rescued by `CONNECTED_BY_DEED`. It is the most reliable of
the *heuristic* connection edges for the veil-pierce job — but reliability is
really per-*method*, not per-edge-type, and a couple of deterministic signals match
it on precision while the deed edge wins on a different axis (it is **name-free**).
The pipeline's own weighting, strongest first:

| Signal (edge · method) | Basis | Reliability | Weakness |
|---|---|---|---|
| `CONNECTED_BY_SPLINK` · `curated` | human-verified table | highest (tiny, manual) | doesn't scale |
| `CONNECTED_BY_SPLINK` · `registered-llc` | **exact** legal owner name (PLUTO) | precision-1, weight 100 | needs the *same* legal name |
| **`CONNECTED_BY_DEED`** · `acris-deed` (held) | co-grantees on one recorded deed | **very high — documentary, name-free** | proves co-ownership *at deed time* |
| `CONNECTED_BY_DEED` · `acris-deed-linked-successor` | grantor-chain reconstruction | high but **more inferential** | gated by single-purpose-successor check |
| `CONNECTED_BY_SPLINK` · `splink-fellegi-sunter` | probabilistic model | medium (weight 10) | name-anchored |
| `CONNECTED_BY_NAME` | fuzzy name | low (weight 1.5) | **namesake collisions** (the Espinal trap above) |
| `CONNECTED_BY_ADDRESS` | shared business address | low (weight 1.0) | aggregator over-merge; **typo splits** (the `GRAND COURSE` case) |

Why the deed edge is special: two buildings on one deed share a grantee → same
owner **regardless of LLC name**, so it merges differently-named LLCs that both the
name-anchored model and the exact-name `registered-llc` edge keep apart. It is
immune to exactly the noise — typos, namesakes, aggregator addresses — that
fractures the name/address edges, which is why it is deliberately specialist and
sparse (~1,428 edges) and targets the hardest fully-obscured cases.

Three qualifiers keep it from being *unconditionally* "most reliable":

1. **Deterministic name signals tie or beat it on precision** — `registered-llc`
   (exact legal name) and `curated` (human) are both weight-100 / precision-1. The
   deed edge wins on being *name-free*, not on raw precision; they cover different
   failure modes, so the pipeline uses all of them.
2. **It's only as good as its guards** — a raw deed proves co-ownership *at
   conveyance time*; the **staleness guard** (group by each building's latest deed)
   and **deed-hub cap** (drop a grantee on >20 deeds) are what make it trustworthy.
   The `linked-successor` variant is more inferential than a currently-held deed.
3. **All `CONNECTED_BY_*` edges are Type II** (derived, caveat-bearing, never a
   legal determination), and a deed-**only** SAME is the eval's *most*-scrutinized
   class (C2, behind the three-check hard gate). The strongest *conclusion* is not
   any single edge but **cross-source corroboration** — e.g. deed **+** HPD (C1),
   exactly what elevated P0012 to the strict-precision bar.

## Reproduce

```sql
-- WoW: two portfolios, both "RAMON ESCOBAR @ 2432 GRAND CONCOURSE #504"
SELECT orig_id, array_length(bbls,1) FROM wow.wow_portfolios WHERE orig_id IN (77821,77822);
SELECT DISTINCT orig_id, upper(l.name), upper(l.bizaddr)   -- shows the GRAND COURSE typo
FROM (SELECT 77821 oid, unnest(bbls) bbl FROM wow.wow_portfolios WHERE orig_id=77821
      UNION ALL SELECT 77822, unnest(bbls) FROM wow.wow_portfolios WHERE orig_id=77822) pf
JOIN wow.wow_landlords l ON l.bbl=pf.bbl GROUP BY orig_id, upper(l.name), upper(l.bizaddr);
```

```sql
-- The full address-variant family behind case A: one office (2432 Grand Concourse #504)
-- recorded ~a dozen ways, which is what shatters WoW's exact-address graph.
SELECT concat_ws(' ', businesshousenumber, businessstreetname, businessapartment) AS address_as_filed,
       upper(businesscity) AS city, businesszip, count(*) AS rows
FROM hpd_registrations r JOIN hpd_contacts c USING (registrationid)
WHERE upper(btrim(c.firstname||' '||c.lastname)) = 'RAMON ESCOBAR'
  AND upper(c.businessstreetname) LIKE 'GRAND%'
GROUP BY 1,2,3 ORDER BY rows DESC;
-- -> GRAND CONCOURSE 504 / CONCOURS 504 / COURSE 504 / COCNOURSE 504 / CONCOURSE (no apt);
--    city BRONX/Bronx/BX/White Plains/GRAND CONCOURSE; zip 10458/10459/10607 — each its own key.
```

```sql
-- The ZIP-gate: WoW's standardized (street, apt, ZIP) for the three nodes' representative buildings.
-- 93014 has ZIP 10458; the two Creston singletons standardized to a BLANK ZIP — and WoW's name AND
-- address rules both hard-require an exact ZIP match, so neither can join the 24-building node.
SELECT bbl, name, bizhousestreet, regexp_replace(bizapt,'\D','','g') AS bizaptnum, bizzip
FROM wow_landlords
WHERE bbl IN ('2023730043','2031600005',   -- in ACT-LL-93014 (24): CONCOURSE / 504 / 10458
              '2028070067',                -- ACT-LL-93013 (2031 Creston): CONCOURSE / 504 / '' (empty)
              '2031600009')                -- ACT-LL-93015 (2070 Creston): GRAND COURSE / 504 / '' (empty)
ORDER BY bbl;
-- 93013 differs from 93014 ONLY on ZIP (blank vs 10458) -> a missing ZIP, not the typo, splits it.
-- The two blanks match each other ('' = ''), so 93013<->93015 still connect by name.
```

```cypher
// Watchline: one portfolio, 26 buildings, all three Creston neighbors inside it
MATCH (p:Portfolio {portfolio_id:'PF-20260901T165123Z-77675'})<-[:IN_PORTFOLIO]-(b:Building)
RETURN count(b), collect(b.bbl);
```

Case B (the Escobar/Espinal 12; WoW splits 8 + 4):

```cypher
// The KG holds two distinct "Ramon Escobar" portfolios (two different owners)
MATCH (l:Landlord) WHERE toUpper(l.name) CONTAINS 'RAMON ESCOBAR'
OPTIONAL MATCH (l)-[:MEMBER_OF]->(p:Portfolio)
RETURN count(DISTINCT p) AS portfolios, collect(DISTINCT p.portfolio_id);

// Signals that merge case B, and the recurring principals check
MATCH (p:Portfolio {portfolio_id:'PF-20260901T165123Z-44544'})<-[:MEMBER_OF]-(a:Landlord)
MATCH (p)<-[:MEMBER_OF]-(b:Landlord) WHERE id(a)<id(b)
OPTIONAL MATCH (a)-[r:CONNECTED_BY_DEED|CONNECTED_BY_ADDRESS|CONNECTED_BY_NAME|CONNECTED_BY_SPLINK]-(b)
RETURN type(r) AS rel, r.method AS method, count(*) ORDER BY rel;
```

```sql
-- WoW splits case B into #50057 (8, PO Box 370 Manhattan) + #44728 (4, McLean Ave Yonkers)
SELECT orig_id, array_length(bbls,1) FROM wow.wow_portfolios WHERE orig_id IN (50057,44728);
```

## See the split in Neo4j — WoW's WCCs vs. the merge

The WoW 24+2 isn't materialized in the graph (both `:Portfolio` and `:OwnerGroup` already merge it),
but it is **latent**: show only WoW's *own* edges (`CONNECTED_BY_NAME` + `CONNECTED_BY_ADDRESS`, hiding
splink/deed) and the owner group breaks back into WoW's two weakly-connected components. Buildings are
drawn via `REGISTERED_FOR` **restricted to each landlord's own `bbls`** — that recovers the 24/1/1
partition exactly (the merged-portfolio anchor's `APPARENT_CONTROL` would wrongly show it holding all 26,
and raw `REGISTERED_FOR` is noisier still).

```cypher
// A) WoW's edges only -> two WCCs = WoW's 24 + 2
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup {owner_group_id:'OG-93013'})
OPTIONAL MATCH pB = (l)-[:REGISTERED_FOR]->(b:Building) WHERE b.bbl IN l.bbls   // 24 / 1 / 1
OPTIONAL MATCH pE = (l)-[:CONNECTED_BY_NAME|CONNECTED_BY_ADDRESS]-(m:Landlord)
  WHERE (m)-[:IN_OWNER_GROUP]->(og)
RETURN l, b, m, pB, pE;
// -> Component 1: ACT-LL-93014 + 24 buildings  (= WoW 77822)
//    Component 2: ACT-LL-93013 -[CONNECTED_BY_NAME]- ACT-LL-93015, 1 building each
//                 (= WoW 77821, the two Creston Ave parcels)
//    93014 floats free — NO name/address edge reaches the typo'd variants. That gap IS the split.

// B) Add the identity edges -> the two components fuse into the 26-building owner group
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup {owner_group_id:'OG-93013'})
OPTIONAL MATCH pB     = (l)-[:REGISTERED_FOR]->(b:Building) WHERE b.bbl IN l.bbls
OPTIONAL MATCH pWoW   = (l)-[:CONNECTED_BY_NAME|CONNECTED_BY_ADDRESS]-(m:Landlord)
  WHERE (m)-[:IN_OWNER_GROUP]->(og)
OPTIONAL MATCH pIdent = (l)-[:CONNECTED_BY_SPLINK|CONNECTED_BY_DEED]-(m2:Landlord)
  WHERE (m2)-[:IN_OWNER_GROUP]->(og) AND l.actor_id < m2.actor_id
RETURN l, b, m, m2, pB, pWoW, pIdent;
```

Toggling A → B is the architecture in one view: **WoW's weakly-connected components vs. what the
name-free deed and the Splink model merge.** In Browser, set the `Landlord` caption to `actor_id` (all
three read "RAMON ESCOBAR") and color the `SPLINK`/`DEED` edges distinctly so the reuniting links stand
out. This *reconstructs* WoW's portfolios from the graph's name/address edges — matched here because it's
a clean two-component case; the authoritative membership is still `wow.wow_portfolios`.

## Show it (map + blind review page)

Two views make the case in a talk — the **map** shows what each system concluded;
the **review page** shows the raw records a human weighs to check it (no system
answer, no WoW comparison — so there's no circularity). Open both in tabs.

```bash
# 1) Comparison map (WatchlineNYC 1 portfolio vs WoW 24+2). Hover a dot for building
#    facts + HPD head officer + business address; the two red Creston strays show the
#    "2432 GRAND COURSE 504" typo that fractured WoW. Add --png for slide images.
uv run python -m watchline.discovery.ingest.portfolio.eval.portfolio_map \
    --portfolio PF-20260901T165123Z-77675 --out eval_out/maps/escobar.html
```

```bash
# 2) The blind reviewer page for this pair (P0012), in the owner-review repo.
#    Needs RECORDS_DSN in owner-review/.env (the records dump).
cd ../owner-review && scripts/serve.sh P0012        # or open the URL directly:
# http://127.0.0.1:8000/pair/P0012?annotator=demo
```

Case B is **not** in the frozen eval sample, so it has an OFF-EVAL one-pair queue
(`PB01`) for a blind walkthrough — reviewed the same way, but never mixed into the
metrics (see `eval_out/offeval/README.md`):

```bash
# 3) Blind review of case B (Escobar/Espinal), split along WoW's 8-vs-4 fracture.
cd ../owner-review && REVIEW_QUEUE=../WatchlineNYC/eval_out/offeval/review_queue.jsonl \
  OWNER_REVIEW_STORE=data/offeval.sqlite uvicorn owner_review.review.app:app --port 8020
# then open http://127.0.0.1:8020/pair/PB01?annotator=demo
```

---

**The quartet:** this file = *merge* what WoW split (owner identity, one typo);
[`case-miller.md`](case-miller.md) = *un-merge* what WoW conflated on a shared **address**
(operational nexus); [`case-levitov.md`](case-levitov.md) = *un-merge* on a shared **manager**
(management ≠ ownership); [`case-haight.md`](case-haight.md) = *merge* what WoW is **blind** to —
nine buildings tied only by an ACRIS **deed** (the veil-pierce). One message: the owner-identity layer is
*precision-first*, keeps *who owns* cleanly separate from *who operates through this office* and *who
manages the building*, and reads the transaction record WoW does not.
