"""eval/wow_gate.py — the hardened WoW veil-pierce gate (evaluation / analysis tooling).

**Not** production. The live graph (`deed_edges.py` / `owner_groups.py` / `pipeline.py`) does not use
this gate; it is the *verification* criterion the deed-review analysis applies to decide whether a
candidate `CONNECTED_BY_DEED` owner group is a **genuine deed veil-pierce** — real JustFix WoW *splits*
the owner across distinct portfolios and only the shared deed reunites them (the AXL case) — versus a
**WoW over-lump**, where WoW already groups most of the buildings via a shared aggregator/back-office
address, so the deed "recovers" nothing WoW hadn't already merged (Citadel, and the soft-aggregator
bridge cases OG-10150 / OG-33260).

## The failure this hardens (see specs/deed-gate-review.md §6)

The old gate asked: do the group's member BBLs land in ≥2 distinct real `wow.wow_portfolios`, *none an
aggregator lump* — where "aggregator" was a **hard cutoff: a WoW portfolio with > 25 distinct
landlords**. That cliff is too loose. A 121-building / 16-landlord portfolio is plainly an over-lump,
but 16 < 25, so the hard cutoff called it "not an aggregator" and passed the candidate. Verified
2026-09-19: all five bridge linked-successor candidates wrongly PASSED, the tell being the two with
scale — OG-10150 (35 of 37 buildings already in one 121/16 WoW portfolio) and OG-33260 (5 of 10 in one
102/11 portfolio).

## The two complementary checks (either failing → the candidate is NOT a clean veil-pierce)

1. **Graded soft-aggregator detection** — replaces the hard > 25-landlord cliff. A portfolio is an
   aggregator if it clears the hard address-level landlord threshold (kept at
   `aggregator_audit.MIN_DEGREE` = 25 as the default) *or* is a **soft aggregator**: large *and*
   multi-landlord (`>= SOFT_MIN_BUILDINGS` buildings and `>= SOFT_MIN_LANDLORDS` landlords), which
   recognizes an over-lump well below 25 landlords. Members landing in *any* aggregator portfolio fail
   the "≥2 distinct, none an aggregator" test.

2. **Dominant-portfolio-share check** — a threshold-*independent* backstop. Fail when a **majority**
   (`>= DOMINANT_SHARE`) of the candidate's member buildings already sit in **one** WoW portfolio that
   is itself large / multi-landlord (i.e. aggregator-ish). This asks the right question directly —
   "does WoW already group most of these?" — and catches both soft-aggregator cases regardless of the
   exact landlord threshold. A genuine split (AXL) is *distributed across comparable small portfolios*,
   so its dominant portfolio is small and this check does not fire.

The gate PASSES only when the members span ≥2 distinct WoW portfolios, none of which is an aggregator,
and no single large/multi-landlord portfolio holds a dominant share.

Design note — why the *portfolio proxy*, not the raw address degree. The truly primitive signal is the
degree of the business address WoW merged on (`aggregator_audit.py` classifies that on the discovery
graph). But `wow.wow_portfolios` exposes only `(orig_id, bbls, landlord_names)` — not the merge
address — so joining the address primitive to a WoW portfolio is not available from the WoW dump alone.
The graded landlord-count / buildings-per-landlord proxy is computed directly from the dump, is exactly
what the regression fixtures key on, and is tuned so every fixture resolves correctly. `MIN_DEGREE` is
imported so the hard landlord default stays a single source of truth with the address-level classifier.

Pure core (`is_aggregator_portfolio`, `wow_gate`) is import-only and unit-tested with fixtures rebuilt
from the regression table. `portfolio_placements` / `gate_bbls` are the thin, read-only Postgres
loaders for real use against `wow.wow_portfolios` (integration-only; need `PG*`).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _hard_default() -> int:
    """The hard landlord threshold, kept a single source of truth with the address-level classifier.

    `aggregator_audit.py` imports `watchline.shared.connections` (→ `psycopg2`, an `ingest` extra) at
    module top, so importing it eagerly would break this otherwise-stdlib pure core in a bare install.
    Mirror the repo's lazy-connection convention (cf. `deed_edges.py`): read `MIN_DEGREE` when it is
    importable, else fall back to the same literal (25). Both paths agree; a test pins the equality when
    the extra is present.
    """
    try:
        from watchline.discovery.ingest.portfolio.aggregator_audit import MIN_DEGREE
        return MIN_DEGREE
    except ImportError:
        return 25


# ---- thresholds --------------------------------------------------------------------------------
# Hard, address-level landlord threshold — kept aligned with the Splink/address-mask AGGREGATOR_DEGREE
# via aggregator_audit.MIN_DEGREE. A WoW portfolio with strictly more distinct landlords than this is an
# aggregator lump outright (the old gate's *only* test).
AGG_LANDLORD_HARD = _hard_default()     # 25
# Soft aggregator: recognizes an over-lump *below* the hard cutoff. A portfolio that is both large and
# multi-landlord is grouping many owners' buildings — an over-lump — even at, say, 16 or 11 landlords.
SOFT_MIN_BUILDINGS = 20
SOFT_MIN_LANDLORDS = 4
# Dominant-share: a portfolio holding at least this fraction of the candidate's member buildings is the
# dominant home of the group. Inclusive of 1/2 so an even split into one big + scattered small (OG-33260,
# 5 of 10) counts as dominant.
DOMINANT_SHARE = 0.5


@dataclass(frozen=True)
class Portfolio:
    """A WoW portfolio's identity + the two size primitives the gate reasons over."""
    orig_id: str
    n_buildings: int        # distinct BBLs in the WoW portfolio
    n_landlords: int        # distinct landlord_names in the WoW portfolio


@dataclass(frozen=True)
class Placement:
    """How many of a candidate owner group's member BBLs fall inside one WoW portfolio."""
    portfolio: Portfolio
    n_members: int          # member BBLs of the candidate that land in `portfolio` (>= 1)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)   # empty iff passed
    # diagnostics (populated regardless of outcome)
    n_members: int = 0
    n_placed: int = 0                                   # members that land in some WoW portfolio
    n_distinct_portfolios: int = 0
    aggregator_orig_ids: list[str] = field(default_factory=list)
    dominant_orig_id: str | None = None
    dominant_share: float = 0.0

    def __bool__(self) -> bool:
        return self.passed


# ---- pure core (unit-tested) -------------------------------------------------------------------
def is_aggregator_portfolio(n_buildings: int, n_landlords: int, *,
                            hard: int = AGG_LANDLORD_HARD,
                            soft_buildings: int = SOFT_MIN_BUILDINGS,
                            soft_landlords: int = SOFT_MIN_LANDLORDS) -> bool:
    """True if a WoW portfolio is an aggregator / over-lump.

    Hard: strictly more than `hard` distinct landlords (the address-level default, 25). Soft: large AND
    multi-landlord (`>= soft_buildings` and `>= soft_landlords`) — catches over-lumps below the cliff.
    """
    if n_landlords > hard:
        return True
    return n_buildings >= soft_buildings and n_landlords >= soft_landlords


def wow_gate(placements: list[Placement], n_members: int, *,
             hard: int = AGG_LANDLORD_HARD,
             soft_buildings: int = SOFT_MIN_BUILDINGS,
             soft_landlords: int = SOFT_MIN_LANDLORDS,
             dominant_share: float = DOMINANT_SHARE) -> GateResult:
    """Decide whether a candidate owner group is a genuine deed veil-pierce vs a WoW over-lump.

    `placements` — one per distinct WoW portfolio the group's member BBLs land in (0..N).
    `n_members`  — total member BBLs of the candidate (denominator for the dominant-share test; members
                   not in any WoW portfolio contribute `n_members - sum(p.n_members)`).

    PASS iff members span ≥2 distinct WoW portfolios, none an aggregator, and no single large/
    multi-landlord portfolio holds a dominant share. Otherwise FAIL with one reason per triggered check.
    """
    def agg(p: Portfolio) -> bool:
        return is_aggregator_portfolio(p.portfolio.n_buildings, p.portfolio.n_landlords,
                                       hard=hard, soft_buildings=soft_buildings,
                                       soft_landlords=soft_landlords)

    n_placed = sum(p.n_members for p in placements)
    distinct = len(placements)
    aggregators = [p for p in placements if agg(p)]
    dominant = max(placements, key=lambda p: p.n_members, default=None)
    dom_share = (dominant.n_members / n_members) if (dominant and n_members) else 0.0

    reasons: list[str] = []

    # Check 1a: the members must actually span ≥2 distinct WoW portfolios. A single portfolio means WoW
    # already groups them — the deed reunites nothing.
    if distinct < 2:
        only = f" (all in orig_id {placements[0].portfolio.orig_id})" if placements else ""
        reasons.append(f"members span only {distinct} distinct WoW portfolio(s){only}; a genuine "
                       f"veil-pierce is distributed across ≥2")

    # Check 1b: graded soft-aggregator — none of the portfolios the members land in may be an over-lump.
    for p in aggregators:
        reasons.append(
            f"member BBLs land in aggregator/over-lump WoW portfolio orig_id "
            f"{p.portfolio.orig_id} ({p.portfolio.n_buildings} bldgs / {p.portfolio.n_landlords} "
            f"landlords)")

    # Check 2: dominant-portfolio-share — a majority of the group's buildings already sit in one large/
    # multi-landlord portfolio. Threshold-independent backstop for a soft-aggregator the graded test
    # might miss under a differently-tuned threshold.
    if dominant is not None and dom_share >= dominant_share and agg(dominant):
        reasons.append(
            f"dominant-share: {dominant.n_members}/{n_members} "
            f"({dom_share:.0%}) of member buildings already sit in one large WoW portfolio "
            f"orig_id {dominant.portfolio.orig_id} "
            f"({dominant.portfolio.n_buildings} bldgs / {dominant.portfolio.n_landlords} landlords)")

    return GateResult(
        passed=not reasons,
        reasons=reasons,
        n_members=n_members,
        n_placed=n_placed,
        n_distinct_portfolios=distinct,
        aggregator_orig_ids=[p.portfolio.orig_id for p in aggregators],
        dominant_orig_id=dominant.portfolio.orig_id if dominant else None,
        dominant_share=round(dom_share, 4),
    )


def legacy_hard_gate(placements: list[Placement], *, hard: int = AGG_LANDLORD_HARD) -> GateResult:
    """The *old* gate, for regression comparison only: members must span ≥2 distinct WoW portfolios,
    none with strictly more than `hard` landlords. Retained to demonstrate what the hardening fixed —
    it wrongly PASSES the soft-aggregator bridge cases (OG-10150, OG-33260)."""
    distinct = len(placements)
    reasons: list[str] = []
    if distinct < 2:
        reasons.append(f"members span only {distinct} distinct WoW portfolio(s)")
    for p in placements:
        if p.portfolio.n_landlords > hard:
            reasons.append(f"orig_id {p.portfolio.orig_id} exceeds hard cutoff "
                           f"({p.portfolio.n_landlords} > {hard} landlords)")
    return GateResult(passed=not reasons, reasons=reasons, n_members=0,
                      n_distinct_portfolios=distinct)


# ---- Postgres loader (integration; read-only on wow.wow_portfolios) ----------------------------
def portfolio_placements(conn, member_bbls) -> tuple[list[Placement], int]:
    """Load, for a candidate's member BBLs, the WoW portfolios they land in and each portfolio's size.

    Read-only on `wow.wow_portfolios(orig_id, bbls, landlord_names)`. Returns `(placements, n_members)`
    where `n_members` is the count of distinct input BBLs and one `Placement` is emitted per distinct
    WoW portfolio any member BBL falls in. `n_buildings` = distinct BBLs in the portfolio,
    `n_landlords` = distinct `landlord_names`.
    """
    members = {str(b).strip() for b in member_bbls if str(b).strip()}
    n_members = len(members)
    if not members:
        return [], 0

    cur = conn.cursor()
    cur.execute("SELECT orig_id, bbls, landlord_names FROM wow.wow_portfolios WHERE bbls IS NOT NULL")
    placements: list[Placement] = []
    for orig_id, bbls, landlord_names in cur.fetchall():
        pf_bbls = {str(b).strip() for b in (bbls or [])}
        hit = members & pf_bbls
        if not hit:
            continue
        placements.append(Placement(
            portfolio=Portfolio(
                orig_id=str(orig_id),
                n_buildings=len(pf_bbls),
                n_landlords=len({str(n).strip() for n in (landlord_names or []) if str(n).strip()}),
            ),
            n_members=len(hit),
        ))
    return placements, n_members


def gate_bbls(conn, member_bbls, **kw) -> GateResult:
    """Convenience: load placements from `wow.wow_portfolios` for `member_bbls`, then run `wow_gate`."""
    placements, n_members = portfolio_placements(conn, member_bbls)
    return wow_gate(placements, n_members, **kw)
