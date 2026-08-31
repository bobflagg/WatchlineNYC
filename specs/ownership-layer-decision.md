# Decision memo — an ownership layer distinct from the portfolio nexus

**Date:** 2026-08-26 · **Status:** decided (build), signals re-sequenced · **Scope:** `watchline/discovery/ingest/portfolio`

## Question

WoW's `Portfolio` is a *registration-graph cluster* — buildings connected by shared head-officer
name and shared business address. That conflates two different real things:

- an **ownership portfolio** — buildings the same party actually owns (Croman), and
- a **management nexus** — buildings different owners route through one operator/manager (Orsid).

Should Watchline add a distinct **ownership layer** (`:OwnerGroup`) that resolves who owns what
*across LLCs*, separate from the management nexus? And is the **ACRIS multi-parcel-deed** signal
the way to pierce the LLC veil? Before committing, we took three measurements on the live `wow`
data (run `PF-20260825T004449Z`).

## Measurements

### M1 — Deed coverage beyond the nexus: large raw, but mostly stale

Multi-parcel deeds (2–25 parcels; 181 bulk/institutional deeds >50 parcels excluded), distinct
building pairs, split by whether the nexus already co-locates them:

| window | new cross-portfolio pairs | % of deed pairs |
|---|---|---|
| all-time | **13,911** | 35% |
| 2013+ (likely still current) | **~670** | 5% |
| 2018+ (recent) | 324 | 7% |

**75% of multi-parcel deeds are pre-2005** — 20+ year-old co-conveyances since split apart. The
35% headline is stale. For *current* ownership the nexus already captures ~95%; deeds add ~670.

Of the 670 current new pairs: **160 share the same registered LLC** (recoverable far more cheaply,
see below) and **510 are different-LLC** — the deed's *unique* veil-pierce, before discounting
sale/multi-grantee noise (face-validity ≈ half real → ~250 genuine).

### M2 — How badly the portfolio count overstates ownership (the real justification)

Portfolios ≥50 buildings, classified by owner-surname diversity:

| kind | portfolios | buildings |
|---|---|---|
| **nexus** (many owners; ownership badly overstated) | 120 | **13,566** |
| mixed | 71 | 6,310 |
| owner (clean) | 65 | 6,008 |

**~half the buildings in large portfolios sit in management nexuses** where "portfolio = owner" is
simply wrong — precisely where investigations concentrate (Orsid: 231 buildings, 224 owners).

### M3 — Face-validity of the new deed links

Recent cross-portfolio deed pairs are ~75–80% genuine same-owner (SIR REALTY, WILSON PROPERTIES,
DAO SAN across two locations…), ~20% noise (a sale/split conveying to two buyers, an HDFC leak).
**Most real wins share the identical registered LLC name** the nexus split — because the nexus
links on *head officer* (person), never on the *DOF owner-of-record*.

### Bonus finding — the cheap sleeper signal

Matching the **registered LLC (`pluto_latest.ownername`)** directly:

- **489 owner entities span ≥2 portfolios over 1,336 buildings** — same legal entity = same owner,
  *deterministically*, with **no ACRIS pipeline**, just a match on data already in the KG.

Larger and cleaner than the deed signal's current unique contribution.

## Decision

Two conclusions, kept separate:

1. **The ownership layer is worth building — yes.** M2 settles it independently of deeds: half the
   large-portfolio buildings conflate ownership with management, and disentangling them is exactly
   the question the audience (journalists, advocates, watchdogs) asks. Add `:OwnerGroup` as a second
   partition alongside `:Portfolio` (a building gets both `IN_PORTFOLIO` and `IN_OWNER_GROUP`).
2. **ACRIS deeds are NOT the lead signal — re-sequence.** The raw appeal was 75% stale; the current
   unique yield is ~250 genuine different-LLC links — high value per case, low volume, expensive,
   noisy. It's a *specialist* final pass, not the workhorse.

### Signal ladder (build in this order — value per unit effort)

| # | signal | yield | cost | precision | status |
|---|---|---|---|---|---|
| 1 | Splink head-officer resolution | backbone | built | high | ✅ `CONNECTED_BY_SPLINK` |
| **2** | **same-LLC `dof_ownername` edge** | **1,336 buildings** | tiny (KG-only) | deterministic | ✅ **prototyped — `llc_edges.py`** |
| 3 | corp co-owner feedback loop | moderate | built | high | ✅ `feedback_merge` |
| 4 | ACRIS deed, different-LLC only, 2013+, non-institutional | ~250 real | expensive + noisy | probabilistic | ⏳ deferred, specialist pass |

**Guardrail unchanged:** `:OwnerGroup` outputs *apparent* common owner with supporting signals and a
caveat — never a legal ownership determination. Its distinct caveat ("apparent common owner") is what
lets the nexus keep its own ("commonly registered/managed, not evidence of common ownership").

## Prototype delivered (step 2)

`watchline/discovery/ingest/portfolio/llc_edges.py` — emits weight-100 `CONNECTED_BY_SPLINK` edges
(`method="registered-llc"`) between the landlord nodes of buildings sharing a DOF owner entity.
Word-boundary entity markers; HDFC/institutional and placeholder exclusions; degree cap (100) for
nominee/placeholder blobs. Wired into `pipeline.load_splink_edges` after the model and curated edges;
`verify_splink` now keys its hard scatter gate on the model method only (curated + LLC deterministic
edges → info). Live run: 1,709 owner entities, 2,270 edges over 3,282 nodes.

Run `--step splink` + `--step reconcile` to materialize the ~489 new owner merges.

## Open questions for the `:OwnerGroup` build (step 3+)

- Materialize `:OwnerGroup` from the Splink owner clusters (`node_clusters`) already computed at build
  time — cheap; the mapping exists, only the write is new.
- Model the LLC as a first-class node with `CO_CONVEYED` (deed) edges only if step-2 coverage gaps
  justify the deed pass.
- Positioning: this is where Watchline diverges from WoW (inference vs. connections). `CONNECTED_BY_SPLINK`
  stays upstream-contributable; `:OwnerGroup` + deeds is a Watchline differentiator, not a WoW PR.
