"""Curated same-owner overrides — human-verified merges the resolution can't reach.

Mechanism B leaves a residual the model *cannot* close: an operator's records that
share only an EXACT, RARE full name — different management shell, different office,
**no shared corp and no shared address** — form a separate connected component, so
WCC never joins them and the operator shows as >1 portfolio. Threshold 0.999 plus the
corp-feedback loop can't bridge these: there is no address or corp signal, only the
name, and the model was trained (on the stratified same-name slice) to distrust name
similarity precisely so it never fuses two different people who share a name.

Concrete case (verified 2026-08): Steven Croman's main 126-bbl portfolio registers
under CENTENNIAL PROPERTIES NY; a 9-bbl remnant registers under ROCKSOLID
PM/MANAGEMENT/VENTURES with **zero** co-registration to Centennial. Only the rare
exact name "STEVEN CROMAN" ties them — a human judgement the resolver can't make.

This module is the human-in-the-loop backstop: a small, hand-verified table of "these
landlord nodes are the same real owner." Each entry force-emits a weight-100
``CONNECTED_BY_SPLINK`` clique between the matching ``landlords_with_connections``
nodes, so the existing WCC+Louvain merges them exactly as it would a model-derived
clique. Edges only ADD → this can only MERGE fragments, never split a portfolio.

**PRECISION IS A HUMAN'S RESPONSIBILITY HERE.** Add an entry only after verifying the
records are the same person (ownership docs, a shared principal, corroborating public
record) — NOT merely because two nodes share a name. Populate it from the ranked
candidates surfaced by ``propose_merges.py`` and record the verifying evidence in each
entry's ``evidence`` field.

Provenance: curated edges carry ``method=CURATED_METHOD`` so they are distinguishable
from model-derived ``splink-fellegi-sunter`` edges in the graph. All seed entries merge
within one surname, so ``verify_splink``'s "0 cross-surname edges" invariant still holds;
if you ever add a cross-surname entry (e.g. a maiden/married name), whitelist curated
edges in that check.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from watchline.discovery.ingest.portfolio.splink_bridge import _norm, SPLINK_WEIGHT, STAR_ABOVE

# Provenance stamped on curated edges, to distinguish them from model-derived ones.
CURATED_METHOD = "curated-same-owner"


@dataclass(frozen=True)
class CuratedOwner:
    """One verified real owner and the name variants that identify its landlord nodes.

    A ``landlords_with_connections`` node joins this owner when its normalized name is
    one of ``names`` and — if ``bbl_allow`` is non-empty — it touches at least one of
    those BBLs (a disambiguator for a name that is *not* unique; leave empty when the
    name alone is safe, as it is for every seed here)."""

    owner_id: str                    # stable slug, e.g. "steven-croman"
    label: str                       # display name
    names: tuple[str, ...]           # normalized full-name variants (matched via _norm)
    evidence: str                    # WHY this merge is verified-safe (human note + source)
    bbl_allow: tuple[str, ...] = ()  # optional: restrict to nodes touching these BBLs


# ---------------------------------------------------------------------------
# The curated table. Add rows ONLY after human verification; cite the evidence.
# Seeded from the 2026-08 diagnosis (propose_merges.py + HPD corp-footprint checks).
# ---------------------------------------------------------------------------
CURATED_OWNERS: tuple[CuratedOwner, ...] = (
    CuratedOwner(
        owner_id="steven-croman",
        label="Steven Croman",
        names=("STEVEN CROMAN", "STEVE CROMAN"),
        evidence=(
            "Single notorious operator. WCC leaves a 9-building remnant registered under "
            "ROCKSOLID PM/MANAGEMENT/VENTURES, tied to his 126-bbl CENTENNIAL PROPERTIES NY "
            "main only by the rare exact name. Verified 2026-08 via HPD corp footprints: "
            "ROCKSOLID 9 bbls, CENTENNIAL 123 bbls, 0 buildings shared — no corp/address "
            "bridge for the resolver to use."
        ),
    ),
    CuratedOwner(
        owner_id="divya-rashad",
        label="Divya Rashad",
        names=("DIVYA RASHAD",),
        evidence=(
            "Single operator split 3 ways in the KG (236 + 2 + 1 = 239 bbls) by the same "
            "exact-name / no-bridge gap. 'DIVYA RASHAD' is rare and unambiguous — distinct "
            "from the unrelated PRASHAD / RAMPRASHAD families a substring search catches."
        ),
    ),
    CuratedOwner(
        owner_id="zachary-kadden",
        label="Zachary Kadden",
        names=("ZACHARY KADDEN", "ZACH KADDEN"),
        evidence=(
            "Single operator (ZACH == ZACHARY) split across 4 components (298 + 177 + 19 + 2 "
            "= 496 bbls). Rare surname. NOTE: 496 > MAX_SIZE (300), so even fully merged this "
            "stays >=2 size-forced portfolios; the clique minimizes the split and unifies the "
            "owner identity, it cannot make Kadden a single portfolio."
        ),
    ),
)


def _match_groups(lwc: pd.DataFrame,
                  owners: tuple[CuratedOwner, ...] = CURATED_OWNERS) -> dict[str, set[int]]:
    """Pure matcher (DB-free, testable): map each curated owner to the lwc nodeids it
    claims. ``lwc`` has columns ``nodeid``, ``name``, ``bbls`` (list of bbl strings)."""
    n = lwc["name"].map(_norm)
    groups: dict[str, set[int]] = {}
    for owner in owners:
        variants = {_norm(v) for v in owner.names}
        sel = lwc[n.isin(variants)]
        if owner.bbl_allow:
            allow = set(owner.bbl_allow)
            sel = sel[sel["bbls"].map(
                lambda bs: bool(allow & set(bs if bs is not None else [])))]
        ids = {int(x) for x in sel["nodeid"].tolist()}
        if ids:
            groups[owner.owner_id] = ids
    return groups


def _clique_rows(ids, star_above: int) -> list[tuple[int, int]]:
    """Pure edge-shape helper: a full clique for a group, or a hub-and-spoke star above
    ``star_above`` to bound edges. Mirrors ``splink_bridge.splink_edges``."""
    ids = sorted(ids)
    if len(ids) < 2:
        return []
    if len(ids) <= star_above:
        return list(combinations(ids, 2))
    return [(ids[0], d) for d in ids[1:]]


def curated_node_groups(conn) -> dict[str, set[int]]:
    """Map each curated owner to the set of ``landlords_with_connections`` nodeids it
    claims. Same ``(name, bbl)`` explode/normalize convention as ``splink_bridge``."""
    lwc = pd.read_sql(
        "SELECT nodeid, name, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    return _match_groups(lwc)


def curated_edges(conn, *, weight: float = SPLINK_WEIGHT,
                  star_above: int = STAR_ABOVE) -> pd.DataFrame:
    """Force-merge cliques for the curated owners as ``[src, dst, weight]`` over lwc
    nodeids — same clique/star shape as ``splink_bridge.splink_edges`` so WCC+Louvain
    consume them identically. Returns an empty frame when nothing matches."""
    rows: list[tuple[int, int]] = []
    for ids in curated_node_groups(conn).values():
        rows.extend(_clique_rows(ids, star_above))
    edges = pd.DataFrame(rows, columns=["src", "dst"])
    edges["weight"] = float(weight)
    return edges


if __name__ == "__main__":  # read-only sanity run (PGDATABASE must point at wow)
    from watchline.shared.connections import pg_conn
    conn = pg_conn()
    g = curated_node_groups(conn)
    E = curated_edges(conn)
    conn.close()
    for oid, ids in g.items():
        print(f"  {oid:<18} {len(ids):>3} nodes")
    print(f"curated: {len(E):,} CONNECTED_BY_SPLINK edges over "
          f"{len(pd.unique(E[['src', 'dst']].values.ravel())) if len(E) else 0} nodes")
