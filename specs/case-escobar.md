# Case study — Ramon Escobar (the "one typo, two portfolios" split)

A presentation- and paper-grade worked example of the merge WatchlineNYC gets
right that Who Owns What splits — driven by a single registration-address typo,
recovered by the ACRIS held-deed signal, and independently confirmed by a blind
human reviewer. Eval pair **P0012** (stratum `S1a_deed_held`, signal
`acris-deed`).

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

## Reproduce

```sql
-- WoW: two portfolios, both "RAMON ESCOBAR @ 2432 GRAND CONCOURSE #504"
SELECT orig_id, array_length(bbls,1) FROM wow.wow_portfolios WHERE orig_id IN (77821,77822);
SELECT DISTINCT orig_id, upper(l.name), upper(l.bizaddr)   -- shows the GRAND COURSE typo
FROM (SELECT 77821 oid, unnest(bbls) bbl FROM wow.wow_portfolios WHERE orig_id=77821
      UNION ALL SELECT 77822, unnest(bbls) FROM wow.wow_portfolios WHERE orig_id=77822) pf
JOIN wow.wow_landlords l ON l.bbl=pf.bbl GROUP BY orig_id, upper(l.name), upper(l.bizaddr);
```

```cypher
// Watchline: one portfolio, 26 buildings, all three Creston neighbors inside it
MATCH (p:Portfolio {portfolio_id:'PF-20260901T165123Z-77675'})<-[:IN_PORTFOLIO]-(b:Building)
RETURN count(b), collect(b.bbl);
```

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
