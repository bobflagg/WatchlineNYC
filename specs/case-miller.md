# Case study — Abraham Miller (the "one office, eleven owners" un-merge)

The mirror image of [`case-escobar.md`](case-escobar.md). Escobar is the merge
WatchlineNYC gets right that Who Owns What *splits*; Miller is the split
WatchlineNYC gets right that Who Owns What *conflates* — many distinct owners
lumped into one "portfolio" because they share a mailing address. Together the
two cases show the honest truth from the divergence stat: **v2 diverges from WoW
in *both* directions**, and neither direction is uniformly "more merged."

This example also carries a de-fragmentation win *and* an honest recall miss
inside the same portfolio, so it teaches all three behaviors at once.

All figures pulled from the live JustFix `wow` schema, PLUTO/ACRIS/HPD records,
and the discovery graph on **2026-09-11**. Re-verify vintage before citing.

## The headline

| | Grouping | Buildings | Label |
|---|---|---|---|
| **Who Owns What** | **1** portfolio (`183`) | **27** | "NATHAN OBSTFELD" (its largest name) |
| **WatchlineNYC** | **7** distinct owner units | 27 (7+7+4+4+3+1+1) | seven separate owners |

WoW's portfolio `183` is not one owner. It is **~10–11 different owners** —
Obstfeld, Miller, Nebenzahl, Padilla, Soria, Fisch — joined only because they all
register from a single shared office: **235 River Ave #220, Lakewood NJ**.

## What actually connects them — a shared office, not an owner

`235 River Ave #220, Lakewood NJ` hosts **31 buildings · ~11 distinct owner/officer
names · 34 single-purpose LLCs** citywide. Its role, from the HPD contact roles:

- **28 HeadOfficer rows → 10 distinct people**, each their own signer for their own
  buildings (Nebenzahl 8, Miller 6, Padilla 6, Obstfeld 4, …).
- **No host entity** — the corporate owners are all separate address-named shells
  (`141 AVE A LLC`, `2307 AVE D LLC`, …); there is **no recurring management company
  or legal-service corporation**, and only 5 `Agent`-type rows total.

So it is **not a registered agent** (no third-party service host) and **not a single
managing agent** (no recurring management co). It is a **shared business address** — a
Lakewood office/community suite many small NYC landlords self-file from. The owners
are genuinely distinct; the only thing they share is the mailbox.

## WatchlineNYC's partition of the same 27 buildings

| Owner unit | Buildings | Note |
|---|---|---|
| **ABRAHAM MILLER** (`OG-233`) | 7 | ✅ merged the **ABARAHAM** typo into ABRAHAM |
| JOE NEBENZAHL (`OG-55820`) | 7 | ✅ merged JOE / JOSEPH |
| NATHAN OBSTFELD (`OG-85030`) | 4 | |
| JEANETTE PADILLA (`OG-52916`) | 4 | |
| VANESSA SORIA (`OG-110200`) | 3 | ✅ merged VANESSA / VANEESA |
| BENYOMIN FISCH | 1 | singleton (its own owner) |
| **NATHAN OBTFELD** | 1 | ⚠️ **recall miss** — the OBTFELD/OBSTFELD typo was *not* merged into Obstfeld |

## Why WoW conflates — the root cause

WoW links landlords who share an exact business address
(`portfoliograph/sql/landlords_with_connections.sql`, no aggregator/degree cap), so a
shared registration office pulls otherwise-unrelated owners into one connected
component. Portfolio `183` is "everyone who files from 235 River Ave, Lakewood" — a
real but *weak* co-location signal, mislabeled as one ownership portfolio. It answers
*"who operates through this office,"* not *"who owns these buildings."*

## Why WatchlineNYC gets it right — and the sub-threshold twist

The owner-identity layer is **name-anchored** and never merges on shared address, so it
separates the ten owners cleanly (0 cross-surname merges) while de-fragmenting the
spelling variants *within* each true owner.

The sharp point: **235 River Ave has a degree of only ~10 owners — below a typical
aggregator degree-cap** (our `aggregator_audit` masks at 25). A purely *address-degree*
mask would **miss** this over-merge entirely. The owner-identity layer catches it anyway,
because it doesn't rely on masking big addresses — it resolves identity from names + true
identity edges. **The shell game hides in sub-threshold aggregators too, and this is why
the identity layer earns its place over address-masking alone.**

## The combined lesson (one portfolio, three phenomena)

1. **v2 splits what WoW conflates** (the headline, a precision win): 1 WoW portfolio → 7
   distinct owners. The counterweight to Escobar's "we merge what WoW splits."
2. **v2 de-fragments typos within** (recall): ABRAHAM/ABARAHAM, JOE/JOSEPH, VANESSA/VANEESA
   — the misspelling splits WoW carries, resolved.
3. **v2 has a real recall miss** (honesty): OBSTFELD vs OBTFELD not bridged — one building
   stranded as a singleton, the same class of typo caught elsewhere. Show it, don't hide it.

## Caveats — leads, not verdicts

- **Divergence, not accuracy.** Whether separating these ten owners is "right" depends on
  whether they are truly independent or a loose Lakewood investor network sharing services.
  Different surnames, each bound to their own buildings and LLCs, make the ownership split
  well-supported — but co-located communities do sometimes co-invest, so a specific pair
  could warrant a second look. A lead to adjudicate, never a determination.
- The OBTFELD miss is a candidate for a curated fix (cf. the Croman ROCKSOLID remnant), not
  evidence the split is wrong.

## Reproduce

Live-graph + `wow`-schema pulls (read-only). Vintage 2026-09-11.

```python
# 1) Abraham Miller's owner group in the discovery graph (note the ABARAHAM typo merge)
#    MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup {owner_group_id:'OG-233'})
#    RETURN l.name, l.actor_id, size(l.bbls), og.member_count, og.building_count

# 2) WoW portfolio 183: size, landlord_names, and the shared address gluing it
#    SELECT bbls, landlord_names, graph FROM wow.wow_portfolios WHERE orig_id=183;
#    -> 27 bldgs; names span Obstfeld/Miller/Nebenzahl/Padilla/Soria/Fisch;
#       bizAddr '235 RIVER AVENUE 220, LAKEWOOD NJ' recurs.

# 3) v2 partition of portfolio 183's 27 bbls, via the IDENTITY mapping
#    (Landlord.bbls -> IN_OWNER_GROUP; NOT via APPARENT_CONTROL, which mis-maps here):
#    UNWIND $bbls AS bbl MATCH (l:Landlord) WHERE bbl IN l.bbls
#    OPTIONAL MATCH (l)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
#    RETURN bbl, collect(DISTINCT coalesce(og.name, l.name+' [singleton]'))
#    -> 7 owner units.

# 4) Is 235 River Ave a registered agent? Contact-role breakdown (Postgres hpd_contacts):
#    WHERE businesshousenumber='235' AND businessstreetname LIKE 'RIVER%' AND businesscity LIKE 'LAKEWOOD%'
#    -> 28 HeadOfficer rows / 10 distinct people; no recurring host corp; 5 Agent rows.
#       => shared office, not a registered/managing agent.
```

## Show it (comparison map)

The **inverse** of the Escobar map: one WoW portfolio, colored by WatchlineNYC's owner split.
It opens on the reveal — WoW's 27 buildings resolved into **7 color-coded owners** across three
boroughs, with the two singletons flagged "unmerged" (the OBTFELD recall-miss visible in the
legend) — and toggles to WoW's single-color "one portfolio" view. Hover a dot for building facts,
HPD head officer, and the shared `235 River Ave, Lakewood` business address.

```bash
# Inverse map (WoW portfolio 183 vs WatchlineNYC's 7 owners). --basemap esri loads from file://
# in any browser; add --with playwright --png for slide-ready PNGs (-watchline = the owner split).
uv run --extra ingest python -m watchline.discovery.ingest.portfolio.eval.portfolio_map \
    --wow-portfolio 183 --basemap esri --out eval_out/maps/miller.html
```

Pairs with Escobar's forward map (`--portfolio <PF-id>`), which shows the merge direction. Same
tool, both directions.

**The quartet:** [`case-escobar.md`](case-escobar.md) = *merge* what WoW split (owner identity,
one typo); this file = *un-merge* what WoW conflated on a shared **address** (operational nexus);
[`case-levitov.md`](case-levitov.md) = *un-merge* on a shared **manager** (management ≠ ownership);
[`case-haight.md`](case-haight.md) = *merge* what WoW is **blind** to — nine buildings tied only by an
ACRIS **deed** (the veil-pierce). One message: the owner-identity layer is *precision-first*, keeps
*who owns* separate from *who operates through this office* and *who manages the building*, and reads the
transaction record WoW does not.
