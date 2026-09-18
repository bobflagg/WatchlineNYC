"""CONNECTED_BY_DEED — the ACRIS multi-parcel-deed co-ownership edge (name-free veil-pierce).

Buildings conveyed on ONE ACRIS deed share a grantee, so they have the same owner — regardless of
what their individual LLCs are named. This is the ONLY signal that pierces the sophisticated shell
game (one owner, many differently-named single-purpose LLCs): name-anchored Splink and the exact
registered-LLC edge both keep those LLCs apart, but a shared deed proves them one owner. Validated
on PF-...739 (Williamsburg): it merged a 22-building bundle spanning 17 different LLC names, and the
"175 REALTY ASSOCIATES I/II/IV" numbered shells — links nothing else in the KG could make.

A SPECIALIST signal, by design: most buildings are bought individually (own deed), so it is sparse
(only the co-conveyed portfolios link). It feeds the OWNERSHIP layer only (owner_groups reads
CONNECTED_BY_SPLINK|CONNECTED_BY_DEED), never the address-nexus Portfolio — deeds are ownership
evidence, not an operational nexus.

STALENESS GUARD — use each building's LATEST deed, not any deed. Two buildings are grouped only when
their *most recent* conveyance is the SAME multi-parcel deed: if a building was co-bought long ago
but never re-sold, that old deed is still its latest, so the co-ownership stands (captures PF-...739's
older bundles); if it was re-sold since, it has a newer latest deed and drops out (no stale merge).
This replaces a date cutoff, which would wrongly drop old-but-held bundles and keep recent-but-sold ones.

LINKED-SUCCESSOR GUARD — the latest-deed rule alone MISSES the shell game's signature move: buy
buildings together, then re-deed each into its own single-purpose LLC (each parcel's latest deed is
now a separate transfer, so the joint deed is "superseded" and dropped). We recover it: a superseded
joint deed still proves co-ownership between parcels Bi,Bj when the joint grantee G is the GRANTOR of
each parcel's latest deed (G restructured them) AND the successor LLC is a shell (globally the latest
grantee of <= SUCCESSOR_MAX buildings) AND that onward conveyance is a NOMINAL transfer (docamount
<= NOMINAL_MAX, i.e. a $0/token restructuring) — NOT a market-price sale. The nominal-consideration
check is what separates same-owner restructuring from an arms-length SALE to an independent buyer:
without it, a genuine $1.1M sale to a small (<= SUCCESSOR_MAX-building) buyer is indistinguishable
from a $0 re-deed into a controlled shell and gets falsely re-merged (the block-3498 / P0133 trap —
see specs/eval-protocol.md §3.2). Verified recovery (nominal consideration, DEED-ONLY, and a true
false-split vs REAL JustFix WoW): AXL HOME LLC bought two adjacent Flushing houses (43-58 & 43-60 164th
St) on one 2015 deed (2015120200784001, $1.2M) and in 2019 re-deeded each into its own shell at $0 —
43-58 -> BRIDGEWOOD DEVELOPMENT LLC (head officer Brian Lin), 43-60 -> HONG LI GROUP LLC (head officer
Xianglian Wang). They register to different people at different addresses, so WoW files them under two
UNRELATED portfolios (wow.wow_portfolios orig_id 14133 vs 55695); the shared deed + nominal recovery is
the SOLE link that reunites them (owner group OG-15928, CONNECTED_BY_DEED only). block-3498's assemblage,
sold off in real ($1.1M) arms-length deals to distinct buyers, stays split, as it should.

RECALL CAVEAT — the nominal gate is deliberately precision-first, and its recall cost is real, not
hypothetical: a same-owner restructuring recorded at a market-scale price (a transfer-tax or financing
basis) is dropped right alongside true arms-length sales, because price alone cannot tell them apart
(the §3 "restructuring vs. sale" check that needs human adjudication). The showcase 41 Haight bulk buy
is exactly this: nine of ten townhouses were re-deeded at ~$1.6-2.8M, so the gate declines the whole
set and NO Haight building is now in an owner group — a defensible precision call, but a recall miss
worth naming (see specs/case-haight.md and the measured impact + a candidate shared-principal
refinement in specs/deed-gate-review.md).

DEED-HUB CAP — a landlord on more than DEED_HUB_CAP distinct multi-parcel deeds is a serial co-investor
whose transitive links would over-merge unrelated parties (Aaron Feldman doing separate JVs with many
partners = the deed analogue of the aggregator megaoffice). Such hub nodes are dropped from the cliques
(precision-safe: drops edges, never adds a wrong one).

Scope: doctype ILIKE '%DEED%' (the 8 conveyance subtypes), 2..MAX_PARCELS lots (mega-deeds are
bulk/institutional transfers). Held-since branch also excludes public/affordable-housing conveyances
(HPD/City/HDFC/program grantor OR grantee) and co-op/condo buildings — shared deeds that fuse
unrelated co-beneficiaries / co-shareholders, not co-owners (see _HELD_PUBLIC_KW / _COOP_CLASSES and
specs/deed-gate-review.md). One clique per deed over the co-conveyed buildings' landlord nodes (star
above STAR_ABOVE to bound edges).

Node mapping is the same explode-join on ``bbl`` that splink_bridge/llc_edges use. Neo4j-free;
returns ``(src_nodeid, dst_nodeid, weight)`` so pipeline.py loads it as CONNECTED_BY_DEED.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import pandas as pd

from watchline.discovery.ingest.portfolio.splink_bridge import SPLINK_WEIGHT, STAR_ABOVE
from watchline.discovery.ingest.portfolio.curated_owners import _clique_rows

DEED_METHOD = "acris-deed"

# A deed conveying more lots than this is a bulk / institutional transfer, not private co-ownership.
MIN_PARCELS, MAX_PARCELS = 2, 25
# A landlord on more distinct multi-parcel deeds than this is a serial co-investor hub -> masked.
DEED_HUB_CAP = 20
# LINKED-SUCCESSOR GUARD: a superseded joint deed still proves co-ownership when its grantee later
# restructured the parcels into per-building single-purpose LLCs. successor_max = the successor LLC
# must be a shell (globally the latest-deed grantee of <= this many buildings), else it looks like an
# arms-length SALE to an independent owner (stale) rather than a same-owner restructuring.
SUCCESSOR_MAX = 3
# LINKED-SUCCESSOR GUARD, consideration gate: a successor parcel is only re-included when its latest
# deed's docamount (the recorded consideration, in dollars) is NOMINAL — i.e. a restructuring, not a
# market-price sale. Without this, an arms-length SALE to a small buyer (who passes SUCCESSOR_MAX) is
# indistinguishable from a $0 re-deed into a controlled shell and gets falsely re-merged (the
# block-3498 / P0133 over-merge; see specs/eval-protocol.md §3.2 and §3 "restructuring vs. sale").
#
# Threshold choice ($100): ACRIS restructurings into a controlled shell are typically recorded at $0,
# occasionally at a small token / transfer-tax basis ($1-$10). $100 sits FOUR ORDERS OF MAGNITUDE
# below any NYC building sale (block-3498's real sales were ~$1.1M), so it never admits a market
# transaction, while still catching a restructuring booked slightly above $0. The tradeoff is
# deliberately precision-favoring: raising it risks re-merging a genuinely cheap sale; the residual
# hole (a genuine sale improperly recorded at $0-$100, or a restructuring recorded above it) is
# irreducible for a price-only test and is left to §3's manual C2 "restructuring vs. sale" gate. This
# is a PREREGISTERABLE parameter (eval feeds specs/eval-protocol.md §3.2, P0133, check 3): fix its
# value before any accuracy run rather than tuning it against the frame.
NOMINAL_MAX = 100
# Only recover restructuring from joint purchases this recent (current-ownership relevance; bounds cost).
RESTRUCT_MIN_DATE = "2005-01-01"
# Institutional grantees whose "co-ownership" is not a private owner.
_INST = ("HDFC", "HOUSING DEVELOPMENT FUND", "HOUSING AUTHORITY", "NYCHA", "CITY OF NEW YORK")
_INST_RE = re.compile("|".join(_INST) + "|BANK|FANNIE|FREDDIE|AUTHORITY|CHURCH|FOUNDATION|"
                      "UNIVERSITY|COLLEGE|TRUSTEES|HOSPITAL", re.I)

# HELD-SINCE PRECISION GUARD (branch A only). The held-since rule groups landlords whose buildings'
# LATEST deed is one shared multi-parcel deed. Two failure modes make that shared deed prove NOT
# private co-ownership but a shared *program* or *building form*, fusing unrelated people:
#   (1) Public / affordable-housing conveyance — the linking deed's GRANTOR or GRANTEE is a
#       government or nonprofit housing entity (HPD/City/HDFC/a partnership program), so its two
#       grantees are co-*beneficiaries*, not co-owners. The pre-existing _INST filter only screened
#       the GRANTEE side, so an HPD-as-grantor conveyance TO two people slipped through — this list
#       screens both sides (partytype 1 AND 2). Kept deliberately narrow (governmental / affordable-
#       housing names) so it never nukes a legitimate private LLC; a person grantor sharing a member
#       surname (family/estate co-ownership) is left untouched, as it should be.
#   (2) Co-op / condo building — the parcel is owned by shareholders / unit-owners, not one landlord,
#       so its original/association deed fuses unrelated shareholders. See coop_condo.py: co-op/condo
#       buildings have no place in the ownership layer. We drop a held deed whose parcels are majority
#       co-op/condo (matching owner_groups.py's >50% building-level convention).
# See specs/deed-gate-review.md (held-since precision fix). Does NOT touch the linked-successor $0
# branch (_retained / _restructured_groups), which is a separate signal.
_HELD_PUBLIC_KW = (
    "HPD", "HOUSING PRESERVATION", "DEPARTMENT OF HOUSING", "CITY OF NEW YORK",
    "HDFC", "HOUSING DEVELOPMENT FUND", "HOUSING AUTHORITY", "NYCHA",
    "NEIGHBORHOOD PARTNERSHIP", "MUTUAL HOUSING", "H.E.L.P", "RESTORATION",
    "SETTLEMENT", "LAND BANK", "COMMISSIONER OF FINANCE", "SECRETARY OF HOUSING",
)
# DOF/PLUTO building classes that mark a co-op (C6/C8/D0/D4) or condo (class starting with 'R').
_COOP_CLASSES = ("C6", "C8", "D0", "D4")


def _norm(name: str) -> str:
    """Fold an entity name for identity comparison: uppercase, strip non-alphanumerics."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _deed_sql(max_parcels: int) -> str:
    # Held-since precision guard (see _HELD_PUBLIC_KW / _COOP_CLASSES): exclude a shared latest deed
    # from proving co-ownership when it is a public/affordable-housing conveyance (grantor OR grantee)
    # or a co-op/condo building's deed. Both drop unrelated co-beneficiaries / co-shareholders that a
    # bare "shared latest deed" would otherwise fuse into one owner group.
    public = " OR ".join(f"upper(p.name) LIKE '%{k}%'" for k in _HELD_PUBLIC_KW)
    coop_classes = ", ".join(f"'{c}'" for c in _COOP_CLASSES)
    return f"""
        WITH latest AS (                        -- each building's most recent deed (staleness guard)
            SELECT DISTINCT ON (btrim(l.bbl)) btrim(l.bbl) AS bbl, m.documentid AS doc
            FROM real_property_master m
            JOIN real_property_legals l ON l.documentid = m.documentid
            WHERE m.doctype ILIKE '%%DEED%%'
              AND COALESCE(m.docdate, m.recordedfiled) <= CURRENT_DATE
            ORDER BY btrim(l.bbl), COALESCE(m.docdate, m.recordedfiled) DESC NULLS LAST
        ),
        coop AS (                               -- co-op/condo bbls: DOF/PLUTO class OR HPD plurality
            SELECT trim(bbl) AS bbl FROM pluto_latest
            WHERE upper(trim(bldgclass)) IN ({coop_classes})
               OR upper(trim(bldgclass)) LIKE 'R%%'                       -- condo classes (R0..R9,RR)
            UNION                               -- same rule owner_groups.py uses (coop_condo.py)
            SELECT g.bbl AS bbl
            FROM hpd_contacts c
            JOIN hpd_registrations_grouped_by_bbl_with_contacts g ON g.registrationid = c.registrationid
            WHERE c.type IN ('HeadOfficer','IndividualOwner','CorporateOwner')
            GROUP BY g.bbl
            HAVING avg(CASE WHEN c.contactdescription IN ('CO-OP','CONDO') THEN 1.0 ELSE 0.0 END) > 0.5
        )
        SELECT lt.doc AS doc, array_agg(DISTINCT lt.bbl) AS bbls
        FROM latest lt
        LEFT JOIN coop cc ON cc.bbl = lt.bbl
        WHERE NOT EXISTS (                      -- (1) public / affordable-housing grantor OR grantee
            SELECT 1 FROM real_property_parties p
            WHERE p.documentid = lt.doc AND p.partytype IN (1, 2) AND ({public}))
        GROUP BY lt.doc
        HAVING count(DISTINCT lt.bbl) >= {MIN_PARCELS}
           AND count(DISTINCT lt.bbl) <= {int(max_parcels)}
           AND avg(CASE WHEN cc.bbl IS NOT NULL THEN 1.0 ELSE 0.0 END) <= 0.5  -- (2) not majority co-op/condo
    """


# --- Linked-successor guard (branch B): recover restructured joint purchases ------------------
# A joint multi-parcel deed whose grantee later spun each parcel into its own single-purpose LLC.
_JOINT_SQL = f"""
    WITH jd AS (
        SELECT m.documentid AS doc, array_agg(DISTINCT btrim(l.bbl)) AS bbls
        FROM real_property_master m
        JOIN real_property_legals l ON l.documentid = m.documentid
        WHERE m.doctype ILIKE '%%DEED%%'
          AND COALESCE(m.docdate, m.recordedfiled) BETWEEN DATE '{RESTRUCT_MIN_DATE}' AND CURRENT_DATE
        GROUP BY m.documentid
        HAVING count(DISTINCT btrim(l.bbl)) BETWEEN {MIN_PARCELS} AND {{max_parcels}}
    )
    SELECT jd.doc AS doc, jd.bbls AS bbls, g.grantees AS grantees
    FROM jd
    LEFT JOIN (
        SELECT documentid, array_agg(DISTINCT name) AS grantees
        FROM real_property_parties WHERE partytype = 2 AND documentid IN (SELECT doc FROM jd)
        GROUP BY documentid
    ) g ON g.documentid = jd.doc
"""
# Latest deed per parcel + that deed's grantor(s) (party1), grantee (party2), and docamount (the
# recorded consideration, for the nominal-consideration gate), joined (not correlated).
_LATEST_SQL = """
    WITH latest AS (
        SELECT DISTINCT ON (btrim(l.bbl)) btrim(l.bbl) AS bbl, m.documentid AS doc,
               m.docamount AS docamount
        FROM real_property_master m
        JOIN real_property_legals l ON l.documentid = m.documentid
        WHERE m.doctype ILIKE '%%DEED%%' AND COALESCE(m.docdate, m.recordedfiled) <= CURRENT_DATE
          AND btrim(l.bbl) = ANY(%s)
        ORDER BY btrim(l.bbl), COALESCE(m.docdate, m.recordedfiled) DESC NULLS LAST
    ),
    parties AS (
        SELECT documentid,
               array_agg(DISTINCT name) FILTER (WHERE partytype = 1) AS grantors,
               string_agg(DISTINCT name, '|') FILTER (WHERE partytype = 2) AS grantee
        FROM real_property_parties
        WHERE documentid IN (SELECT doc FROM latest) AND partytype IN (1, 2)
        GROUP BY documentid
    )
    SELECT latest.bbl AS bbl, latest.doc AS doc, pr.grantors AS grantors, pr.grantee AS grantee,
           latest.docamount AS docamount
    FROM latest LEFT JOIN parties pr ON pr.documentid = latest.doc
"""
# GLOBAL single-purpose size: distinct buildings each (normalized) entity has ever received as grantee.
_SUCC_SIZE_SQL = """
    SELECT regexp_replace(upper(p.name), '[^A-Z0-9]', '', 'g') AS g, count(DISTINCT btrim(l.bbl)) AS n
    FROM real_property_parties p
    JOIN real_property_legals l ON l.documentid = p.documentid
    WHERE p.partytype = 2 AND regexp_replace(upper(p.name), '[^A-Z0-9]', '', 'g') = ANY(%s)
    GROUP BY 1
"""


def _is_nominal(docamount, nominal_max: float = NOMINAL_MAX) -> bool:
    """True when a deed's recorded consideration is nominal (<= ``nominal_max``) — a restructuring,
    not a market sale. A missing amount (None) is treated as NON-nominal: absent price evidence we do
    not re-merge, which is precision-safe (drops a possible edge, never invents one)."""
    if docamount is None:
        return False
    try:
        return float(docamount) <= nominal_max
    except (TypeError, ValueError):
        return False


def _retained(doc: str, bbls, grantee_norm: set[str],
              latest: dict, succ_size: dict, successor_max: int,
              nominal_max: float = NOMINAL_MAX) -> list[str]:
    """Pure: which parcels of joint deed ``doc`` (grantee set ``grantee_norm``) are still co-owned —
    either held directly (the joint deed is their latest) or restructured by the same grantee into a
    single-purpose LLC (latest-deed grantor == grantee AND that successor is a shell AND that onward
    conveyance is a NOMINAL transfer, not a market-price sale). ``latest``:
    bbl -> (latest_doc, {grantor_norm}, successor_norm, docamount). ``succ_size``: successor_norm ->
    global count. The nominal gate is what keeps a $1.1M arms-length sale to a small buyer from being
    re-merged as if it were a $0 re-deed into a controlled shell (block-3498 / P0133)."""
    out: list[str] = []
    for b in bbls:
        info = latest.get(b)
        if not info:
            continue
        ldoc, lgrantors, lgrantee, ldocamount = info
        if ldoc == doc:                                                   # held since the joint deed
            out.append(b)
        elif (lgrantors & grantee_norm) and succ_size.get(lgrantee, 10**9) <= successor_max \
                and _is_nominal(ldocamount, nominal_max):
            out.append(b)                                     # restructured into a shell (nominal $)
    return out


def _restructured_groups(conn, max_parcels: int, successor_max: int) -> dict[str, set[str]]:
    """Joint deeds (grantee G) -> the set of their bbls still co-owned by G (held or restructured
    into single-purpose successor LLCs). Returns ``{doc: {bbls}}`` for deeds keeping >= 2."""
    joint = pd.read_sql(_JOINT_SQL.format(max_parcels=int(max_parcels)), conn)
    joint = joint[joint["grantees"].apply(
        lambda gs: bool(gs) and not any(_INST_RE.search(x or "") for x in gs))]
    if joint.empty:
        return {}
    allb = sorted({b for bbls in joint["bbls"] for b in bbls})
    cur = conn.cursor()
    cur.execute(_LATEST_SQL, (allb,))
    latest = {bbl: (doc, {_norm(x) for x in (grs or [])}, _norm(gee), amt)
              for bbl, doc, grs, gee, amt in cur.fetchall()}
    keys = sorted({v[2] for v in latest.values() if v[2]})
    cur.execute(_SUCC_SIZE_SQL, (keys,))
    succ_size = {g: n for g, n in cur.fetchall()}
    groups: dict[str, set[str]] = {}
    for doc, bbls, grantees in zip(joint["doc"], joint["bbls"], joint["grantees"]):
        G = {_norm(x) for x in grantees}
        keep = _retained(str(doc), bbls, G, latest, succ_size, successor_max)
        if len(keep) >= 2:
            groups[str(doc)] = set(keep)
    return groups


def _groups_from(deeds: pd.DataFrame, lwc: pd.DataFrame) -> dict[str, set[int]]:
    """Pure mapper (DB-free, testable): each deed -> the set of lwc nodeids covering its co-conveyed
    buildings, keeping only deeds that reach >=2 distinct nodes. ``deeds`` has columns ``doc``,
    ``bbls``; ``lwc`` has ``nodeid``, ``bbls``."""
    bbl2nodes: dict[str, set[int]] = defaultdict(set)
    for nodeid, bbls in zip(lwc["nodeid"], lwc["bbls"]):
        for b in (bbls if bbls is not None else []):
            bbl2nodes[b].add(int(nodeid))

    groups: dict[str, set[int]] = {}
    for doc, bbls in zip(deeds["doc"], deeds["bbls"]):
        ids: set[int] = set()
        for b in (bbls if bbls is not None else []):
            ids |= bbl2nodes.get(b, set())
        if len(ids) >= 2:
            groups[str(doc)] = ids
    return groups


def deed_node_groups(conn, *, max_parcels: int = MAX_PARCELS,
                     successor_max: int = SUCCESSOR_MAX) -> dict[str, set[int]]:
    """Map each qualifying deed to the ``landlords_with_connections`` nodeids of its co-conveyed
    buildings. Two sources, unioned per deed: (A) buildings whose LATEST deed is a shared multi-parcel
    deed (held-since; the staleness guard), and (B) the linked-successor guard — joint purchases the
    grantee later restructured into per-building single-purpose LLCs (recovers the shell-game move
    the latest-deed rule alone drops)."""
    held = pd.read_sql(_deed_sql(max_parcels), conn)
    combined: dict[str, set[str]] = {str(d): set(b or []) for d, b in zip(held["doc"], held["bbls"])}
    for doc, bbls in _restructured_groups(conn, max_parcels, successor_max).items():
        combined.setdefault(doc, set()).update(bbls)
    deeds = pd.DataFrame({"doc": list(combined), "bbls": [list(v) for v in combined.values()]})
    lwc = pd.read_sql(
        "SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    return _groups_from(deeds, lwc)


def _hub_nodes(groups: dict[str, set[int]], hub_cap: int) -> set[int]:
    """Nodeids appearing in more than ``hub_cap`` distinct multi-parcel deeds — serial co-investor
    hubs whose transitive links would over-merge unrelated parties."""
    deed_count = Counter(n for ids in groups.values() for n in ids)
    return {n for n, c in deed_count.items() if c > hub_cap}


def deed_edges(conn, *, weight: float = SPLINK_WEIGHT, star_above: int = STAR_ABOVE,
               max_parcels: int = MAX_PARCELS, hub_cap: int = DEED_HUB_CAP,
               successor_max: int = SUCCESSOR_MAX) -> pd.DataFrame:
    """Co-conveyance cliques as ``[src, dst, weight]`` over lwc nodeids — one per multi-parcel deed
    (star above ``star_above``), with hub nodes dropped. Empty frame when nothing qualifies."""
    groups = deed_node_groups(conn, max_parcels=max_parcels, successor_max=successor_max)
    hubs = _hub_nodes(groups, hub_cap)
    rows: list[tuple[int, int]] = []
    for ids in groups.values():
        rows.extend(_clique_rows(ids - hubs, star_above))
    edges = pd.DataFrame(rows, columns=["src", "dst"]).drop_duplicates()
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at wow)
    import warnings; warnings.filterwarnings("ignore")
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    restr = _restructured_groups(conn, MAX_PARCELS, SUCCESSOR_MAX)
    g = deed_node_groups(conn)
    hubs = _hub_nodes(g, DEED_HUB_CAP)
    E = deed_edges(conn)
    conn.close()
    n = len(pd.unique(E[["src", "dst"]].values.ravel())) if len(E) else 0
    print(f"joint deeds (2005+) with >=2 co-owned parcels [held or restructured, bbl-level]: {len(restr):,}")
    print(f"deeds mapping to >=2 landlord nodes (held + restructured, post node-map): {len(g):,}")
    print(f"deed-hub nodes masked (in > {DEED_HUB_CAP} deeds): {len(hubs):,}")
    print(f"CONNECTED_BY_DEED edges: {len(E):,} over {n:,} nodes")
