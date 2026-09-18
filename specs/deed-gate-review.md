# Deed nominal-consideration gate — impact review & recommendation

**Scope.** Reviews the nominal-consideration gate added to the linked-successor recovery in
`watchline/discovery/ingest/portfolio/deed_edges.py` (commit `5f51475`). The gate re-includes a
restructured parcel only when its latest deed's `docamount <= NOMINAL_MAX` ($100). This note (a)
quantifies how much recall the gate costs, (b) classifies a sample of what it drops, and (c) evaluates
whether $100 is defensible and whether a better-than-price signal exists.

**TL;DR recommendation.** Keep `NOMINAL_MAX = 100`. It is defensible and precision-safe: at the
owner-group layer it costs ~160 deed cliques / ~170 edges, and a sample of what it drops is
overwhelmingly genuine arms-length sales to distinct owners. Price alone genuinely cannot separate a
same-owner restructuring from a sale (the §3 "restructuring vs. sale" check that needs a human), so a
residual recall loss is irreducible for a price-only test. A **shared-principal refinement** (re-include
a market-price successor whose HPD head officer matches a held parcel of the same joint deed) is
precision-safe on all three anchor cases and recovers genuine restructurings the price gate drops — but
its reach is small (24 parcels) and it adds an HPD dependency to an otherwise ACRIS-only module.
**Prototyped and measured below; recommended as an optional, deliberately-adopted enhancement, not
wired into production here.** Code left as-is.

All figures re-verified against `justfixwow` (ACRIS `real_property_*`) + the discovery graph on
**2026-09-16**, by running `deed_edges.py`'s own pure functions gated vs. ungated (monkeypatching
`_is_nominal` to always-true reproduces the pre-`5f51475` behavior exactly). Read-only; the graph was
**not** rebuilt.

---

## 1. How much does the gate drop?

The gate only touches the **restructuring branch** of `_retained` (the held-since branch, `ldoc == doc`,
is untouched). Among candidates that satisfy that branch's structural test — latest-deed grantor ∈ joint
grantee **and** successor is a shell (≤ `SUCCESSOR_MAX` = 3 buildings):

| parcel-level (bbl × joint-deed) | count |
|---|---:|
| held-since (unaffected by gate) | 74,043 |
| restructuring, **nominal ≤ $100** → gate **admits** | 4,219 |
| restructuring, **price > $100** → gate **rejects** | **≈9,460** |
| restructuring, `docamount` NULL → gate rejects (precision-safe) | 0 |

So the gate rejects ~69% of restructuring-branch re-inclusions. **But most of those never reach the
owner-identity layer** (no landlord node, or the joint deed still keeps ≥2 nodes via held parcels). The
impact that actually matters — deed cliques / `CONNECTED_BY_DEED` edges / nodes — is far smaller:

| `deed_edges` output | ungated (pre-`5f51475`) | gated (current) | delta |
|---|---:|---:|---:|
| joint deeds mapping to ≥2 landlord nodes | 1,201 | 1,058 | **−160 lost, 11 shrunk** |
| `CONNECTED_BY_DEED` edges | 1,428 | 1,258 | **−170 (−11.9%)** |
| distinct nodes touched | 2,120 | 1,946 | −174 |

(Gated 1,258 ≈ the live graph's 1,256 `CONNECTED_BY_DEED` edges — expected minor drift from data
updates.) **Owner-group impact is bounded above by ~160 groups** — each lost deed clique that is not
*also* held together by `CONNECTED_BY_SPLINK` (name/address) becomes a lost or shrunk owner group; some
survive on the Splink edge, so ≤160 groups actually lose a deed-only reunification. The guard still does
substantial work *post*-gate: **1,555** joint deeds currently keep ≥2 parcels via ≥2 nominal successors.

### 1a. The upside the gate protects — deed-only false-split fixes (checked against *real* WoW)

The gate is worth defending because the signal fixes false splits that *no* registration signal can.
But "false split" must be scored against the **live JustFix `wow.wow_portfolios`**, not the discovery
graph's own `Portfolio` nodes — WatchlineNYC's `Portfolio` layer masks aggregator addresses
(landlord-degree > 25), real WoW does not, so a group can look split in our layer yet be one lump in
WoW. Applying that gate changes the picture sharply:

- In the graph, **55 owner groups are wired by `CONNECTED_BY_DEED` only**, of which **44 span ≥2 distinct
  registered persons**. Against real WoW, ~40 of those 44 do land in ≥2 distinct portfolios — **but the
  population is dominated by non-shell-game patterns**: HDFC / co-op sponsor conveyances, family/estate
  trust transfers, and institutional REIT deals (the `_INST` grantee filter misses these when the
  institution is the *grantor*). Screening to a genuine same-owner restructuring — all onward transfers
  $0, a single non-institutional **company** grantor, non-family — leaves only **5**, of which just
  **one** is multi-shell.

- That one is the clean positive companion: **AXL HOME LLC (`OG-15928`)** — two adjacent Flushing houses
  (43-58 & 43-60 164th St) bought on one 2015 deed ($1.2M), re-deeded in 2019 into `BRIDGEWOOD
  DEVELOPMENT LLC` and `HONG LI GROUP LLC` at $0, registered to two different people at two different
  addresses. **Real WoW files them under two unrelated portfolios** (`orig_id` 14133 vs 55695, neither an
  aggregator), and only the deed reunites them. Written up as [`case-axl.md`](case-axl.md).

- **The vivid big fleets are usually WoW *over-lumps*, not false-splits.** `CITADEL ESTATES (OG-67966)` —
  15 Brooklyn buildings re-deeded into Grateful-Dead-named shells at $0 — is a *genuine* deed recovery,
  but its three registrants all file at one 33-landlord aggregator address (`1330 EASTERN PARKWAY 6A`),
  so **all 15 sit in a single real WoW portfolio (`orig_id 161`, 83 bldgs, 33 landlords)**. Relative to
  WoW it is an over-lump, not a split. This is the structural tension worth stating: the shell operators
  most worth catching tend to reuse one registration address (which lumps them in WoW), so the deed's
  *uniquely* recovered false-splits skew small — an operator who spread the shells across different
  addresses (AXL). A follow-up worth doing: fixing the grantor-side institutional leakage (HDFC/co-op
  sponsor deeds) that pads the deed-only pool.

## 2. What is in the drop? (classification of a sample)

A random 15 of the ~9,460 price-rejected parcels, enriched with successor grantee + HPD head officer:

- **Correct drops (real sales to distinct owners): the large majority.** Most successors are **named
  individuals** — `LEUNG, YIU TUNG`; `KOZYREVA, NATALIA`; `PATINA, INESSA`; `DOLIVEUX, MAELLE`;
  `SHIN, HOONHEE`; `OMOTADE, ADEKUNLE` — i.e. a person bought a building. One is a **$150M** sale
  (`CS WALL STREET, LLC`). These are unambiguously arms-length; re-merging them was the original bug
  (block-3498 / `P0133`). The gate is right to drop them.
- **Recall regressions (same-owner restructuring priced for tax/financing): a small, identifiable slice.**
  These leave a fingerprint the price hides but the **registration** reveals — the successor shares a
  **principal** with the joint grantee / sibling successors. Examples the shared-principal signal catches
  (§3 prototype): deed `2023110200174001` → `1022 CONEY LLC` + `1024 CONEY LLC`, both head officer
  `SOLOMON ISRAEL`, both $800k; and **41 Haight** itself (John Jun Xu on the retained set). These are the
  cases where the gate genuinely loses a real merge.

The honest split: **most rejections are correct**; a **minority** are recall regressions, of which only
the subset that shares a registered principal is *recoverable by any automated signal*. The rest —
an owner who deliberately registers each shell under a different person (five of nine at 41 Haight) —
is indistinguishable from a sale on every public record, and is exactly the §3 manual-adjudication
residue by construction.

## 3. Is $100 defensible? Is there a better signal than price?

**$100 is defensible.** ACRIS restructurings into a controlled shell record $0 (occasionally a $1–$10
token / transfer-tax basis); real NYC building sales are $10^5–10^8. $100 sits four orders of magnitude
below any sale, so it never admits a market transaction — 0 of the rejected parcels had a NULL price to
mishandle, and the admitted set (4,219) is cleanly nominal. Raising it buys almost nothing (there is no
population of genuine restructurings recorded at $100–$100k) while risking a cheap real sale. Keep it,
and keep it **preregistered** (fix before any accuracy run; feeds `eval-protocol.md` §3.2 / `P0133`).

**Price alone cannot do better** — that is the whole point of §3 check 3. The improvement has to come
from a **second, orthogonal signal**: does the successor share a **principal** with the joint grantee?

### Prototype — shared-principal recovery (HPD head officer)

Rule: for a joint deed `D` with grantee `G`, re-include a **market-price** restructuring successor
parcel `b` (grantor ∈ `G`, successor a shell) when `b`'s **HPD head officer** matches the head officer
of a **held** parcel of the same deed `D` (the anchor for `G`'s principal). Exact match on the
normalized `firstname+lastname`. This stays **Neo4j-free** (HPD is Postgres: `hpd_registrations` ⋈
`hpd_contacts` on `registrationid`, `type = 'HeadOfficer'`).

Measured effect over the ~9,460 price-rejected parcels:

| | result |
|---|---|
| parcels recovered (successor head officer = a held-parcel head officer) | **24** (across 22 joint deeds) |
| still dropped (distinct or absent principal) | ≈9,436 |
| **block-3498 / Leland** (must stay split) | **0 recoveries** ✅ — sold lots' officers are `None` or `OSMANI ALI` ≠ held lots' `OSMAN ALI` |
| **CHERRY 168** (priced resale to distinct people) | **0 recoveries** ✅ — `MoBun Yip` ≠ `Jan How Kang`, no held anchor |
| **41 Haight** | recovers `41-19` + `41-13` (both head officer `JOHN JUN XU`) → with held `41-27`, a **3-parcel clique** = exactly the Xu-retained set; the five distinct-registrant parcels stay split ✅ |

So the refinement does precisely what a human adjudicator would: recover the same-principal restructuring
(Xu's set; the Coney/Solomon-Israel pairs) while leaving genuine sales split. **All three anchor cases
behave correctly**, including the block-3498 regression fixture. The 24 recovered rows spot-check as
genuine — each is one person on both sides of the deed.

### Why it is *not* wired into production here

1. **Marginal reach.** 24 parcels across 22 deeds. Net graph effect after node-mapping is a handful of
   small cliques — real, but small. The reach is limited by requiring a **held** parcel to anchor `G`'s
   principal; deeds where *every* parcel was re-deeded (e.g. CHERRY) have no anchor. A looser variant
   (anchor on `G`'s own HPD registrations wherever they appear) would reach more but risks `G` being a
   common holding/management LLC — more precision surface to defend.
2. **Architectural cost.** `deed_edges.py` is deliberately an **ACRIS-only** specialist signal
   (`_deed_sql`/`_JOINT_SQL`/`_LATEST_SQL` are all `real_property_*`). Adding `hpd_registrations` /
   `hpd_contacts` couples it to the registration layer it is designed to be independent of. Worth doing
   deliberately, not as a drive-by.
3. **No effect without a rebuild.** The recovery only changes the graph after a pipeline rebuild, which
   is a separate, out-of-scope data step.

**Recommendation:** adopt it as a *deliberate* enhancement if the ~24-parcel recall gain is judged worth
the HPD coupling — the rule is precision-safe and validated. If adopted, add it as a second recovery
predicate in `_retained` (keep the price gate as the default path; the head-officer match is an
*additional* admit, never a relaxation), thread an `officer_by_bbl` map alongside `latest`/`succ_size`,
and add tests mirroring §3's table (block-3498 → 0 recoveries; a synthetic shared-officer market-price
successor → recovered). Until then, **code stays as-is** and the tradeoff is documented here.

## 4. Reproduction

```
# gated vs ungated deed-edge counts (monkeypatch _is_nominal -> always True for the pre-gate baseline)
python - <<'PY'
import watchline.discovery.ingest.portfolio.deed_edges as de
from watchline.shared.connections import pg_conn
conn = pg_conn()
g = de.deed_node_groups(conn); E = de.deed_edges(conn)          # gated
de._is_nominal = lambda *a, **k: True
gu = de.deed_node_groups(conn); Eu = de.deed_edges(conn)        # ungated
print(len(g), len(E), '|', len(gu), len(Eu))
PY
```

The shared-principal measurement joins `hpd_registrations ⋈ hpd_contacts (type='HeadOfficer')` on
`registrationid` to get one normalized `firstname+lastname` per bbl, anchors each joint deed on its
held-parcel officers, and re-tests the price-rejected candidates against that anchor.

---

## 5. Held-since branch precision fix — co-op/condo + public-grantor exclusion

**Scope.** A *separate* precision fix, in the **held-since** grouping — applied in **both** deed paths
(`_deed_sql` and `_JOINT_SQL`; see *Applied to both deed paths* below) (not the nominal-consideration
gate of §1–§4, which is the linked-successor `$0` branch and is untouched). The
held-since rule groups landlords whose buildings share one *still-latest* joint deed. Two failure modes
make that shared deed prove not private co-ownership but a shared *program* or *building form*, fusing
unrelated people into one owner group.

**Audit (frame: the 75 "deed-only" owner groups — ≥2 members connected only by `CONNECTED_BY_DEED`,
zero `CONNECTED_BY_SPLINK`; `justfixwow` + discovery graph, 2026-09-18, read-only, graph not rebuilt).**
Of the 75, **61** are held-since (two members share a still-latest multi-parcel deed). Classifying each
group's linking deed:

- **Public / affordable-housing conveyance (10 groups)** — the linking deed's **grantor OR grantee** is
  a government / nonprofit housing entity, so its two grantees are program *co-beneficiaries*, not
  co-owners. The pre-existing `_INST` filter screened only the **grantee** side, so an *HPD-as-grantor*
  conveyance TO two people slipped through. Examples: NYC HPD (Roccio+Guillen, Garcia+Ocon,
  Geer+Geula), Dept. of Housing Preservation & Development (Rojas+Vargas), Neighborhood Partnership
  HDFC (Rosa+Espinal), NYC Partnership program via L&M Madison (Imdad+Wolkoff), H.E.L.P.-Bronx
  (Greenaway+Aquino).
- **Co-op / condo building (6 groups)** — the parcel is owned by shareholders / unit-owners, so its
  original/association deed fuses unrelated shareholders. Examples: 980 Fifth Ave Corp / class D4
  (Lesten+Gordon-Ptashne), 332-336 E 77th St Assoc / class C6 (Bean+Osher), Bond Street Associates /
  C6 (Zasloff+Holman), John Gault Company / C6 (Astacio+Pablo).

**The fix.** In the held-since candidate generation (`_deed_sql`, and mirrored in `_JOINT_SQL` — see
*Applied to both deed paths*), drop a shared latest deed from forming a held group when either:
1. **Public / affordable-housing** — grantor (`partytype = 1`) **or** grantee (`partytype = 2`) matches
   the conservative keyword list `_HELD_PUBLIC_KW` (`HPD`, `HOUSING PRESERVATION`, `DEPARTMENT OF
   HOUSING`, `CITY OF NEW YORK`, `HDFC`, `HOUSING DEVELOPMENT FUND`, `HOUSING AUTHORITY`, `NYCHA`,
   `NEIGHBORHOOD PARTNERSHIP`, `MUTUAL HOUSING`, `H.E.L.P`, `RESTORATION`, `SETTLEMENT`, `LAND BANK`,
   `COMMISSIONER OF FINANCE`, `SECRETARY OF HOUSING`). Verified case-insensitively against the
   merge-forming held set: every match is a genuine public/nonprofit entity — **zero** private-LLC
   false positives.
2. **Co-op / condo building (majority)** — a `coop` CTE unions the DOF/PLUTO building-class rule
   (co-op `C6/C8/D0/D4`, condo class `R*`) with the project's existing HPD-`contactdescription`
   plurality filter (`coop_condo.py`, the same rule `owner_groups.py` uses); a deed is dropped when
   **>50%** of its held parcels are co-op/condo (matching `owner_groups.py`'s building-level
   convention). Neither source alone suffices — the HPD filter catches 980 Fifth (Lesten) but misses
   332-336 E 77th / Bond St / John Gault; the class filter catches those.

**Measured effect (held-since candidate set, deterministic, 2026-09-18):**
- On the 75-group audit frame: the fix removes **16 of the 61** held-since deed-only groups (10 by the
  public-grantor/grantee rule, 6 by the co-op/condo-majority rule), retaining **45** — the family/estate
  co-ownership (person grantor sharing a member surname: Curmi, Lax, Wilson, Damiani, Boiardi, D'Urso,
  …), name-variant Splink-misses (out of scope), and benign private LLCs. This matches the ~16 spurious
  groups (~36% of the held-since portion) found in the audit.
- Globally (all held-since deeds mapping to ≥2 landlord nodes, i.e. that actually form a merge): of
  **966** such deeds, the fix drops **211** (127 public-grantor/grantee, 100 co-op/condo, 16 overlap).
- **Unchanged, as required:** the linked-successor `$0` cases (AXL joint deed `2015120200784001`,
  Citadel) are private, non-co-op conveyances, so the guard leaves them; they are recovered by
  `_restructured_groups` as before. Family/estate held-since groups remain. `_INST` / `_INST_RE` /
  `_retained` unchanged.

**Applied to both deed paths (completeness).** `deed_node_groups` unions `_deed_sql` (branch A) with
`_restructured_groups` (branch B) — and branch B *also* emits held-since parcels: `_retained` keeps a
parcel when `ldoc == doc` (the joint deed is its latest). Filtering only branch A therefore let
**post-2005** public/co-op held deeds re-enter through branch B (they clear `_JOINT_SQL`'s 2005+
recency floor), silently undoing the fix for recent conveyances. The same guard (`_PUBLIC_LIKE` +
`_COOP_CTE`, factored to a single source of truth) is now applied in `_JOINT_SQL` too. Verified
before→after on `_restructured_groups` (deterministic, 2026-09-18): the leaking held deeds are removed —
e.g. `2005070600401001` (City-of-NY grantor) and `2007061401549001` (majority co-op) — while the
linked-successor `$0` recoveries AXL `2015120200784001` and Citadel
`2008072300342001` (private, non-co-op) are retained; branch B's joint-deed set drops **31,163 → 30,767**.
The invariant is guarded by `tests/test_deed_edges.py::test_joint_sql_mirrors_the_held_since_guard`.
Conservative-by-design: deeds that are neither clearly public nor majority co-op (e.g. Grassmere
Terrace, and a person-grantor group that is exactly 50% co-op) are deliberately kept — zero
false-positive exclusions of private co-ownership.

**Residual (deliberate).** One audited example is *not* dropped: Grassmere Terrace (Lugo+Emono), a
class-C0 townhouse HOA whose grantee is a "HOME OWNERS ASSOCIATION" — caught by neither rule. Adding a
generic `OWNERS CORP` / `ASSOCIATION` keyword would risk nuking legitimate private entities, so the
filter is left conservative (per the fix's precision-first intent); this one is left to a future pass.

Reproduce with the audit scripts (deed-only groups from the graph → linking held-since deed → classify
grantor/grantee + building class); the hermetic SQL-shape check is
`tests/test_deed_edges.py::test_deed_sql_carries_the_held_since_precision_guard`.


## 6. What does `CONNECTED_BY_DEED` actually buy? — classification of the deed-critical owner groups

Motivation: `CONNECTED_BY_DEED` is one of the two owner-group edge sets (owner group = connected
components of `CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED`). This section measures, on the live graph, how
often the deed edge is *load-bearing* and what kind of ownership it recovers. Read-only, vintage
**2026-09-18** (discovery graph + `justfixwow`; deed-critical via GDS WCC over `CONNECTED_BY_SPLINK`
joined to owner groups; deed-only classification via ACRIS grantor/grantee + DOF building class + name
similarity). Frame is **pre-§5-fix** unless noted.

**Load-bearing footprint.** The **pre-§5-fix** audit (of 6,528 multi-member owner groups) found **763**
groups carry ≥1 `CONNECTED_BY_DEED` edge, but in **611** Splink alone already connects them (the deed is
*redundant*); the deed is **load-bearing in 152** ("deed-critical": removing the deed edges fragments the
group into ≥2 Splink-components) = **75 deed-only** (no Splink among members) + **77 bridge** (deed joins
≥2 otherwise-separate Splink-clusters). **After the §5 rebuild** (current graph, 6,521 groups) these
tighten to **130 deed-critical — 63 deed-only + 67 bridge** — the fix dissolved ~22 spurious deed-critical
groups and left **zero** public/co-op residual bridges.

**Classification of the 75 deed-only groups** (pre-§5-fix frame; the fix later removed the ~12 spurious
held-since, leaving 63. Assigned by *primary* mechanism; name-variant first, so these are a clean
partition — §5 counts held-since more broadly by deed-shape, 61 of 75, because many name-variant groups
also happen to share a held deed):

| Mechanism | n | What it is | Demo/precision value |
|---|---|---|---|
| **held-since** (shared joint deed) | 44 | co-ownership via one still-latest deed | mostly ordinary; ~⅓ spurious |
| **name-variant** (Splink miss) | 22 | one person, spelling/order variants the deed corroborated | recall backstop, not a veil-pierce |
| **linked-successor `$0`** (shell game) | 5 | bulk buy → per-parcel `$0` shells | the concealed-ownership payoff |
| **other** (multi-hop chains) | 4 | recovered through a deed chain | case-by-case |

- The **44 held-since** break down (by linking grantor) into **9 public/affordable**, **16
  family/estate** (person grantor sharing a member surname — legitimate co-ownership), **19 private
  company/other**; **9** are majority co-op/condo buildings. **~16 are spurious** (public/HDFC/city
  grantor or majority co-op/condo — co-op shareholders / program co-beneficiaries fused as one owner);
  **§5 removes these** and keeps the family/estate and benign-private ones.
- The **5 linked-successor `$0`** are only ~2 clean concealed-ownership veil-pierces: **AXL**
  (`OG-15928`, 2 houses, grantor `AXL HOME LLC`) and **Citadel** (`OG-67966`, 15 buildings, grantor
  `CITADEL ESTATES LLC`). The other three are weaker: **Roubeni** (`ORIENT PARK LLC`) is a convoluted
  multi-shell tangle, and **Brates**/**Guo** are `$0` *intra-family* transfers (person grantor).

**Where the deed's value actually lives — the owner-group layer, not WoW-portfolio splits.** A clean
"deed reunites what real WoW *split*" example is *rare*: checked against JustFix `wow.wow_portfolios`
(not the graph's own `Portfolio` nodes), **AXL is essentially the only one**. Citadel and Roubeni
*fail* that gate — real WoW **over-merges** their shells into one aggregator portfolio (Citadel: 83
buildings / 33 landlords at `1330 Eastern Pkwy`; Roubeni: 32 buildings / 15 landlords), so relative to
WoW they are over-lumps, not splits. The reason is structural: shell operators register from a shared
back-office, and WoW merges on that address (it does not mask aggregators), so the sets a deed would
reunite are already grouped by WoW. The deed's payoff is therefore concentrated in the **owner-group**
layer, which *deliberately ignores* shared/aggregator addresses (to avoid the Miller-style false
*merge*) — and that masking is exactly what would otherwise false-*split* a shell operator with no
name/Splink tie. In one line: **you need the deed precisely where you refused to trust the address**;
aggregator-masking and `CONNECTED_BY_DEED` are two halves of one design.

**Classification of the 67 bridge groups** (current graph, post-§5 rebuild — the deed joins ≥2
Splink-clusters; same ACRIS grantor/grantee + name method applied to the cross-cluster tie):

| Bucket | n | What the deed bridges |
|---|---|---|
| **held-since** | 41 | a shared joint deed spanning ≥2 Splink-clusters (co-ownership) |
| **name-variant** | 12 | Splink *under*-merged one person into clusters; the deed corroborates (e.g. IGHODARD/IGHODARO, MARITN/MARTIN KALT) |
| **other** | 9 | multi-hop / unclear (large operators: Fruchthandler `OG-34289`, Beach Front `OG-13058`) |
| **linked-successor `$0`** | 5 | common nominal grantor across clusters — the shell-game bridge (`2180 WALTON LLC`, `GC 26 LLC`) |
| **public/co-op residual** | 0 | cleared by §5 ✓ |

The bridge groups **mirror the deed-only picture** — dominated by ordinary co-ownership (41 held-since)
and Splink recall-backstop (12 name-variant), with only **5** genuine veil-pierce-style recoveries (which
need the same WoW-gate scrutiny as AXL/Citadel). So across all **130** deed-critical groups, the deed's
concealed-ownership payoff stays small; most of its work is ordinary co-ownership and Splink backstopping.

**Residual — institutional over-merge (open item).** The 41 held-since bridges still contain a few
**institutional over-merges** the conservative §5 keyword filter misses — e.g. `OG-40172` (114 buildings;
distinct HDFCs + Columbia University). A future pass with broader institutional detection (owner-type /
HDFC-corp signals, not a static keyword list) would tighten this; it is the one open item left in the
deed-critical picture.
