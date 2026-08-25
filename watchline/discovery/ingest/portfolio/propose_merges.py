"""Propose curated same-owner merges — rank rare exact-name operators that are split
across portfolios, for HUMAN REVIEW before adding them to ``curated_owners.py``.

The resolution + corp-feedback loop leaves a residual: an operator whose fragments
share only a rare exact name (no shared corp/address bridge) stays >1 portfolio because
WCC never joins the separate components. This script surfaces those candidates from the
LIVE KG — every landlord name that spans >=2 portfolios — annotated with a name-rarity
proxy (distinct HPD identities for its surname+initial, via ``splink_source.name_freq``)
and the per-portfolio building sizes, ranked by total buildings (impact first).

It DECIDES NOTHING. A rare exact name across portfolios is usually one operator, but can
be two different people (a coincidental shared rare name, a Jr/Sr). Review each row
against the public record, then add the *verified* ones to
``curated_owners.CURATED_OWNERS`` — the script prints ready-to-paste stubs for the top
candidates. Names already curated are excluded.

Read-only: reads the discovery KG (Neo4j) and the ``wow`` Postgres. Run after a KG build.

Usage:
    uv run --extra ingest python -m watchline.discovery.ingest.portfolio.propose_merges
    uv run --extra ingest python -m ...propose_merges --max-identities 8 --top 40
"""
from __future__ import annotations

import argparse

import pandas as pd

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE
from watchline.discovery.ingest.portfolio import splink_source as ss
from watchline.discovery.ingest.portfolio.algorithms import MAX_SIZE
from watchline.discovery.ingest.portfolio.curated_owners import CURATED_OWNERS, _norm

# Names held by more distinct HPD identities than this are treated as too common to be
# one operator on name alone (JOHN SMITH), so they're filtered out of the proposal by
# default. Rare operators (Croman, Rashad, Kadden) sit far below it. Raise with --all-names.
DEFAULT_MAX_IDENTITIES = 8

# Landlord names spanning >=2 portfolios, with each portfolio's building count.
_SPAN_CYPHER = """
MATCH (l:Landlord)-[:MEMBER_OF]->(p:Portfolio)
WITH toUpper(trim(l.name)) AS name, collect(DISTINCT p) AS ps
WHERE size(ps) >= 2
UNWIND ps AS p
OPTIONAL MATCH (b:Building)-[:IN_PORTFOLIO]->(p)
WITH name, p.portfolio_id AS pid, count(DISTINCT b) AS bbls
WITH name, collect({pid: pid, bbls: bbls}) AS ports
RETURN name AS name,
       size(ports) AS n_portfolios,
       reduce(s = 0, x IN ports | s + x.bbls) AS total_bbls,
       [x IN ports | x.bbls] AS sizes
ORDER BY total_bbls DESC
"""


def _rarity_lookup(conn) -> dict[tuple[str, str], int]:
    """(last_name, first_initial) -> distinct HPD identity count."""
    nf = ss.name_freq(conn)
    return {(r.last_name, r.first_initial): int(r.identities) for r in nf.itertuples()}


def _split_name(name: str) -> tuple[str, str]:
    """Best-effort (surname, first_initial) from a KG full name, mirroring name_freq."""
    toks = _norm(name).split()
    if len(toks) < 2:
        return ("", "")
    return (toks[-1], toks[0][:1])


def propose(conn, driver, *, max_identities: int, min_stranded: int, top: int) -> pd.DataFrame:
    curated = {_norm(v) for o in CURATED_OWNERS for v in o.names}
    rarity = _rarity_lookup(conn)

    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as session:
        rows = session.run(_SPAN_CYPHER).data()

    out = []
    for r in rows:
        name = r["name"]
        if _norm(name) in curated:
            continue
        surname, init = _split_name(name)
        identities = rarity.get((surname, init))
        # Unknown rarity (name not in the person tables) is kept but flagged; a known
        # common name is dropped unless --all-names raised the cap past it.
        if identities is not None and identities > max_identities:
            continue
        sizes = sorted(r["sizes"], reverse=True)
        total = r["total_bbls"]
        stranded = total - (sizes[0] if sizes else 0)   # buildings away from the main
        if stranded < min_stranded:
            continue
        # A same-name split whose combined size fits under MAX_SIZE MUST be disconnected
        # components (Louvain never splits a <=MAX_SIZE component) — a clique collapses it
        # to ONE portfolio. Over MAX_SIZE it can't be one portfolio regardless; a clique
        # only unifies owner identity and minimizes the split.
        out.append({
            "name": name,
            "surname": surname,
            "identities": identities,          # None = unknown (org-ish / unmatched)
            "n_portfolios": r["n_portfolios"],
            "total_bbls": total,
            "stranded": stranded,
            "sizes": sizes,
            "kind": "curable" if total <= MAX_SIZE else "large",
        })
    if not out:
        return pd.DataFrame(out)
    # Rank by stranded buildings (impact of the split), most first.
    df = pd.DataFrame(out).sort_values(
        ["stranded", "total_bbls"], ascending=False).reset_index(drop=True)
    return df.head(top)


def _stub(name: str) -> str:
    slug = _norm(name).lower().replace(" ", "-")
    return (f'    CuratedOwner(\n'
            f'        owner_id="{slug}",\n'
            f'        label="{name.title()}",\n'
            f'        names=("{_norm(name)}",),\n'
            f'        evidence="TODO: verify same-owner via public record, then cite it here.",\n'
            f'    ),')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-identities", type=int, default=DEFAULT_MAX_IDENTITIES,
                    help="drop names held by more distinct HPD identities than this")
    ap.add_argument("--all-names", action="store_true",
                    help="disable the rarity filter (show every split name)")
    ap.add_argument("--min-stranded", type=int, default=3,
                    help="drop splits with fewer than this many buildings away from the main")
    ap.add_argument("--top", type=int, default=30, help="rows to show")
    args = ap.parse_args()

    conn, driver = pg_conn(), neo4j_driver()
    try:
        df = propose(conn, driver,
                     max_identities=10**9 if args.all_names else args.max_identities,
                     min_stranded=args.min_stranded, top=args.top)
    finally:
        conn.close(); driver.close()

    if df.empty:
        print("No rare exact-name splits found — nothing to propose.")
        return

    n_curable = int((df["kind"] == "curable").sum())
    print(f"\n{len(df)} candidate same-owner merges (rare names split across portfolios)."
          f"\n  'kind'=curable  -> combined <= MAX_SIZE ({MAX_SIZE}); a clique collapses it to ONE"
          f" portfolio ({n_curable} here)."
          f"\n  'kind'=large    -> combined > MAX_SIZE; stays >=2 by the cap, a clique only unifies"
          f" identity + minimizes the split."
          f"\n  'identities'    -> distinct HPD people sharing the surname+initial (? = unknown);"
          f" >1 means VERIFY it's one person.\nReview each against the public record before"
          f" curating.\n")
    show = df.copy()
    show["identities"] = show["identities"].map(lambda v: "?" if v is None else v)
    print(show[["name", "kind", "identities", "n_portfolios", "total_bbls", "stranded", "sizes"]]
          .to_string(index=False))

    print("\n--- ready-to-paste stubs for the top candidates (VERIFY before keeping) ---\n")
    for name in df["name"].head(min(8, len(df))):
        print(_stub(name))


if __name__ == "__main__":
    main()
