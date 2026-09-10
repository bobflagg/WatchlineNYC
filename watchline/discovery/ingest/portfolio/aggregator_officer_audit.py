"""aggregator_officer_audit.py — flag OUT-OF-STATE INSTITUTIONAL officers (national servicer / REO
signers) that Splink would otherwise resolve as a single NYC owner, to produce a precision-safe
exclusion-candidate list for human curation.

The aggregator problem also comes through shared OFFICERS, not just shared addresses (F6/F7): a
HeadOfficer name that signs across many buildings owned by DIFFERENT parties is a shared *signer*
(servicer / managing agent), not a beneficial owner — yet Splink merges the name into one
owner-entity. Eric Moore is the canonical case: 210 NYC buildings under one "Eric Moore" head-officer
name, registered from out-of-state corporate offices (Temecula CA / Dallas TX) — a national
SFR/REO signer, not a NYC landlord.

The *obvious* discriminator — owner-of-record DIVERSITY (how many distinct owning LLCs the officer
spans) — **fails**: a real owner running one shell LLC per building looks identical to an aggregator.
Mark Scharfman, a genuine single owner, spans 103 owner-LLCs over 136 buildings (0.76 / building) —
essentially Eric Moore's 194 / 210 (0.92). That is the F6 "mask must not fire on shell-LLC owners"
caveat, in data.

Out-of-state address is necessary but NOT sufficient: at `MIN_BUILDINGS` buildings + `FAR_PCT`
far-state, 8 officers flag, but only 4 are servicers — the other 4 are genuine out-of-state OWNERS (a
Maine LIHTC developer, an RI investor, a NH fund "CCM Ventures", a NC apartment LLC). The distinguishing
signal is the CorporateOwner on their buildings: a mortgage SERVICER / GSE / bank (Fannie Mae, Selene
Finance, Shellpoint, Reverse Mortgage Solutions, Security National Servicing) means REO/foreclosure
holdings the officer merely signs for, not owns. So the rule requires out-of-state (`FAR_PCT`) AND
servicer-owned buildings (`SERVICER_PCT`) — Moore/Ballard/Boudreaux/Johnson flag; the 4 real owners do not.
(Owner-of-record diversity is useless here — a real shell-LLC owner (Scharfman, 103 owner-LLCs / 136
bldgs) matches an aggregator, the F6 caveat.)

Read-only, Postgres-only. `audit()` DECIDES nothing — it emits candidates (option b, the durable rule);
`excluded_officer_names()` returns the hand-verified CURATED allowlist (`CURATED_SERVICER_OFFICERS`,
option a) gated by that rule, and the resolution (`splink_bridge._resolve`) drops exactly those from
`extract()` so their buildings resolve by owner-of-record (registered-llc / deed), not the shared signer.
Doing it at extract-level is essential — it is feedback-proof (a clusterer veto is not: `feedback_merge`
re-merges past it).
"""
from __future__ import annotations

# The legitimate NYC-metro owner footprint. A HeadOfficer registering from outside it, at scale, is
# a national institutional/servicer signer rather than a local beneficial owner.
METRO_STATES = ("NY", "NJ", "CT", "PA")
# Below this many buildings a genuine out-of-state owner (a snowbird, a relocated family) is
# plausible; at or above it, a far-state footprint reads as institutional.
MIN_BUILDINGS = 20
# ... and only when at least this share of the officer's registrations use a far-state address, so
# an owner with one stray out-of-state filing is not flagged.
FAR_PCT = 60
# Out-of-state alone is NOT enough — it also catches genuine out-of-state OWNERS (a Maine LIHTC developer,
# a NH fund). The distinguishing signal is that the buildings' CorporateOwner is a mortgage SERVICER / GSE /
# bank (REO/foreclosure holdings the officer merely signs for). Require this share of servicer-owned buildings.
SERVICER_PCT = 50

# CURATED allowlist (option a) — the officer names hand-verified as mortgage servicers/REO signers, the ONLY
# names the resolution actually excludes. The audit rule below (option b) is the durable candidate generator;
# a human promotes a candidate here after checking it. Verified 2026-09-10 from their CorporateOwners
# (Fannie Mae / Selene Finance / Shellpoint / Reverse Mortgage Solutions) AND confirmed servicer-dominant by
# the rule (>=SERVICER_PCT). NB SIDNEI JOHNSON is out-of-state with servicer corps too, but <50% of his
# buildings are servicer-owned so the rule does not confirm him — left out (conservative), revisit if needed.
CURATED_SERVICER_OFFICERS = frozenset({"ERIC MOORE", "KARLA BALLARD", "TERESA BOUDREAUX"})

# The officer key is `upper(btrim(first)) || ' ' || upper(btrim(last))` — built the same way here and at the
# resolution's exclusion (splink_bridge) so the two match exactly (whitespace-robust: each part trimmed).
_OFFICER_KEY = "upper(btrim(c.firstname)) || ' ' || upper(btrim(c.lastname))"
_OFFICER_SQL = f"""
WITH svc_bbl AS (   -- buildings whose CorporateOwner is a mortgage servicer / GSE / bank (not an owner)
  SELECT DISTINCT r.bbl
  FROM hpd_contacts c JOIN hpd_registrations r ON r.registrationid = c.registrationid
  WHERE c.type = 'CorporateOwner' AND c.corporationname IS NOT NULL
    AND (c.corporationname ILIKE '%%MORTGAGE%%' OR c.corporationname ILIKE '%%SERVICING%%'
         OR c.corporationname ILIKE '%%SAVINGS%%' OR c.corporationname ILIKE '%%FANNIE%%'
         OR c.corporationname ILIKE '%%FREDDIE%%' OR c.corporationname ILIKE '%%NATIONAL ASSOCIATION%%'
         OR c.corporationname ~* '\\yBANK\\y')),
o AS (
  SELECT {_OFFICER_KEY} AS officer, r.bbl,
         CASE WHEN upper(btrim(c.businessstate)) = ANY(%(metro)s) THEN 0 ELSE 1 END AS far,
         CASE WHEN r.bbl IN (SELECT bbl FROM svc_bbl) THEN 1 ELSE 0 END AS svc
  FROM hpd_contacts c JOIN hpd_registrations r ON r.registrationid = c.registrationid
  WHERE c.type = 'HeadOfficer' AND c.firstname IS NOT NULL AND c.lastname IS NOT NULL
        AND btrim(c.lastname) <> '' AND c.businessstate IS NOT NULL)
SELECT officer, count(DISTINCT bbl) AS buildings,
       round(100.0 * sum(far) / count(*), 0) AS pct_far,
       round(100.0 * sum(svc) / count(*), 0) AS pct_servicer
FROM o GROUP BY officer HAVING count(DISTINCT bbl) >= %(min_bldg)s
"""


def is_institutional_officer(buildings: int, pct_far: float, pct_servicer: float) -> bool:
    """Pure classifier: an out-of-state mortgage-SERVICER / REO signer (exclusion candidate), not a local
    owner. Requires scale + far-state footprint AND servicer-owned buildings — the servicer-corp test is
    what separates a national servicer signer (Eric Moore) from a genuine out-of-state OWNER (a Maine LIHTC
    developer / a NH fund), which the far-state address alone conflates."""
    return buildings >= MIN_BUILDINGS and pct_far >= FAR_PCT and pct_servicer >= SERVICER_PCT


def audit(conn, *, min_buildings: int = MIN_BUILDINGS) -> list[dict]:
    """Read-only: HeadOfficer names that read as out-of-state institutional signers, newest first by
    building count. Candidates for a human-curated exclusion list — not an automatic mask."""
    with conn.cursor() as cur:
        cur.execute(_OFFICER_SQL, {"metro": list(METRO_STATES), "min_bldg": int(min_buildings)})
        rows = [{"officer": o, "buildings": int(b), "pct_far": float(pf), "pct_servicer": float(ps)}
                for o, b, pf, ps in cur.fetchall()]
    flagged = [r for r in rows if is_institutional_officer(r["buildings"], r["pct_far"], r["pct_servicer"])]
    return sorted(flagged, key=lambda r: -r["buildings"])


def excluded_officer_names(conn, *, min_buildings: int = MIN_BUILDINGS) -> set[str]:
    """The officer NAMES the resolution actually drops from `extract()` — the CURATED allowlist (option a),
    gated by the audit rule (option b) so nothing is excluded that the rule no longer flags. To promote the
    rule to the sole authority once trusted, return `{r["officer"] for r in audit(...)}` directly."""
    return {r["officer"] for r in audit(conn, min_buildings=min_buildings)} & CURATED_SERVICER_OFFICERS


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at justfixwow)
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    try:
        for r in audit(conn):
            print(f"{r['buildings']:5d} bldgs  {r['pct_far']:3.0f}% far   {r['officer']}")
    finally:
        conn.close()
