# Recall-Anchor Starter Set

Seed for the **recall** measurement in [`eval-protocol.md`](eval-protocol.md) §5. Recall over the
full population is uncomputable (the denominator — *all* true same-owner pairs — is unknowable), so
we measure recall only on operators whose **complete portfolio is documented externally**. On each
such anchor: recall = (true same-owner pairs our system recovered) / (all true pairs in the
documented portfolio).

**Critical framing.** The building counts below are *our system's output*, **not** ground truth.
The truth comes from the **external source** (an AG settlement's building list, an investigative
piece, a registry filing). The human adjudicator's job per anchor:

1. Find the authoritative external source and extract its **true, complete** building/BBL list.
2. Confirm the anchor is a genuine single beneficial owner (not a management figure or nonprofit,
   unless intended).
3. Fix an **as-of date** — portfolios change hands; the external list and our snapshot must align.
4. Record the **true count**, then compute recovered/true.

Candidates are ranked by a cleanliness proxy — **surname %** = distinct surnames / member nodes;
low = a coherent single identity (name variants), high = possibly a multi-party or over-merged
group needing scrutiny. Recognizability / source hints are **starting points to verify, not facts**.

---

## Tier A — seed anchors (high-confidence, clean; start here)

| Anchor | Our buildings | Member nodes | Composition (what the group merges) | External source to obtain & verify |
|---|---|---|---|---|
| **Steven Croman** | 127 | 12 | name variants only (`STEVEN/STEVE CROMAN`) — surname % 8 | **2016 NY AG settlement** (*People v. Croman*) + DOB/press; building list is public — the gold anchor |
| **Efstathios Valiotis** | 119 | 10 | 5+ spelling variants of one name — surname % 10 | Alma Realty holdings (public developments, press) |
| **Jane Goldman** | 119 | 4 | `GOLDMAN` + `CHARLES FELDMAN` | Solil Management (well-documented family holdings) |
| **Zachary Kadden** | 38 | 9 | name variants (`ZACHARY/ZACH KADDEN`) — clean | curated canary; obtain registration/press footprint |
| **Divya Rashad** | 231 | 17 | `RASHAD` + co-officers (`BENDOV`, `BOTTAZZI`, `SACHS`) | curated canary — **⚠ multi-surname**; verify the co-officers are the *same beneficial owner*, not a JV, before using as a clean anchor |

The first four are near-ideal: coherent single identities the system assembled from name variants,
each with a plausible public paper trail. Croman is the anchor to build first (the AG settlement
gives a citable, complete building list independent of our system). Rashad is included because it's
a validated canary, but its cross-surname composition makes it a *curated assertion* — treat it as a
harder anchor and adjudicate the co-officers explicitly.

## Tier B — candidate pool (triage: verify cleanliness + find a source)

Fill the blank columns; drop any that turn out to be management agents, nonprofits, or over-merges.

| Anchor | Our buildings | Members | Surname % | Notes / flag | External source | Verified complete? | True count |
|---|---|---|---|---|---|---|---|
| Joseph Zitolo | 256 | 7 | 29 | large, low-diversity | | | |
| Gary Grinberg | 231 | 6 | 17 | clean | | | |
| Ilsoo Kim | 162 | 11 | 18 | clean | | | |
| Farhad Basal | 147 | 11 | 9 | very clean | | | |
| Mark Scharfman | 133 | 10 | 10 | clean; recognizable NYC LL | | | |
| Mendy Deutsch | 118 | 3 | 33 | recognizable NYC LL | | | |
| Martin Scharf | 111 | 10 | 30 | clean-ish | | | |
| Yossi Toledano | 102 | 10 | 30 | clean-ish | | | |
| Omid Mashieh | 95 | 14 | 43 | 2 portfolios; scrutinize | | | |
| Frank Lang | 131 | 18 | 61 | **review** — possible over-merge | | | |
| Madelyn Lugo | 132 | 8 | 75 | **review** — possible over-merge | | | |
| Yosef Emergi | 95 | 12 | 50 | **review** — scrutinize | | | |

## Caveats

- **Nonprofit / management look-alikes.** Some large, clean-looking anchors are affordable-housing
  nonprofits or management principals rather than private beneficial owners (candidates surfaced in
  the wider scan included names consistent with MHANY/HDFC-type entities). Fine as anchors *if*
  intended and documented, but classify them explicitly — don't let one slip in as a "private
  owner."
- **Our footprint ≠ truth.** If the external source lists buildings our system missed, that's a
  recall miss (the point of the measurement). If it lists *fewer*, check for a data-vintage gap
  (cf. the 333 Rector / Dianna Lam confound) before scoring.
- **High surname % = adjudicate first.** Rows flagged **review** may be legitimate multi-principal
  operations or genuine over-merges; resolve that before using them for recall (an over-merged
  anchor inflates apparent recall).
- **Target ~5–8 verified anchors** for the minimal eval — enough for a credible recall estimate
  across a size range. Croman + Valiotis + Goldman + Kadden are the strongest starting four; add
  2–4 from Tier B once sourced. A JustFix co-adjudicator on this set materially raises its trust.

*Graph metrics as of the current `entity-linking-prototype` snapshot; regenerate if the pipeline is
rebuilt.*
