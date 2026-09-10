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

The clean discriminator for this class is the OUT-OF-STATE INSTITUTIONAL ADDRESS: a person
registering NYC buildings AT SCALE from a far corporate address (not the NY/NJ/CT/PA metro) is a
national signer, not a local owner. Moore = CA/TX (flag); Scharfman = NY (keep); Albert Dweck = NJ
(metro, keep). At `MIN_BUILDINGS` buildings and `FAR_PCT` far-state registrations, only ~8 officers
flag — all clearly institutional (Eric Moore; servicer signers Teresa Boudreaux [OLIT trust],
Charles Gendron) — a small, human-verifiable set, exactly like the aggregator-ADDRESS mask.

Read-only, Postgres-only. It DECIDES nothing — it emits exclusion *candidates*. Apply a curated
subset (human-verified, like `curated_owners`) by dropping those officers' HPD contacts from
`extract()` so their buildings resolve by owner-of-record (registered-llc / deed) rather than the
shared signer name — the officer analogue of the aggregator-address mask blanking the address.
(Alternative: a projection-side `institutional_officer` flag that excludes the entity from
accountability targeting, additive, mirroring the co-op/condo drop / F5.)
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

# The officer key is `upper(btrim(first)) || ' ' || upper(btrim(last))` — built the same way here and at the
# resolution's exclusion (splink_bridge) so the two match exactly (whitespace-robust: each part trimmed).
_OFFICER_KEY = "upper(btrim(c.firstname)) || ' ' || upper(btrim(c.lastname))"
_OFFICER_SQL = f"""
WITH o AS (
  SELECT {_OFFICER_KEY} AS officer, r.bbl,
         CASE WHEN upper(btrim(c.businessstate)) = ANY(%(metro)s) THEN 0 ELSE 1 END AS far
  FROM hpd_contacts c JOIN hpd_registrations r ON r.registrationid = c.registrationid
  WHERE c.type = 'HeadOfficer' AND c.firstname IS NOT NULL AND c.lastname IS NOT NULL
        AND btrim(c.lastname) <> '' AND c.businessstate IS NOT NULL)
SELECT officer, count(DISTINCT bbl) AS buildings,
       round(100.0 * sum(far) / count(*), 0) AS pct_far
FROM o GROUP BY officer HAVING count(DISTINCT bbl) >= %(min_bldg)s
"""


def is_institutional_officer(buildings: int, pct_far: float) -> bool:
    """Pure classifier: an out-of-state institutional/servicer signer (exclusion candidate), not a
    local owner. Grounded on scale + far-state footprint — NOT owner-of-record diversity, which a
    real shell-LLC owner (Scharfman) shares with an aggregator (Eric Moore)."""
    return buildings >= MIN_BUILDINGS and pct_far >= FAR_PCT


def audit(conn, *, min_buildings: int = MIN_BUILDINGS) -> list[dict]:
    """Read-only: HeadOfficer names that read as out-of-state institutional signers, newest first by
    building count. Candidates for a human-curated exclusion list — not an automatic mask."""
    with conn.cursor() as cur:
        cur.execute(_OFFICER_SQL, {"metro": list(METRO_STATES), "min_bldg": int(min_buildings)})
        rows = [{"officer": o, "buildings": int(b), "pct_far": float(pf)} for o, b, pf in cur.fetchall()]
    flagged = [r for r in rows if is_institutional_officer(r["buildings"], r["pct_far"])]
    return sorted(flagged, key=lambda r: -r["buildings"])


def excluded_officer_names(conn, *, min_buildings: int = MIN_BUILDINGS) -> set[str]:
    """The set of flagged officer NAMES (`upper(btrim(first)) ' ' upper(btrim(last))`), for the resolution
    to drop from `extract()` so their buildings resolve by owner-of-record rather than the shared signer.
    The rule is precision-safe (see module docstring: 0 real owners among the flagged), but it is a *rule* —
    review the list before a run of consequence, or gate it behind a curated allowlist."""
    return {r["officer"] for r in audit(conn, min_buildings=min_buildings)}


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at justfixwow)
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    try:
        for r in audit(conn):
            print(f"{r['buildings']:5d} bldgs  {r['pct_far']:3.0f}% far   {r['officer']}")
    finally:
        conn.close()
