"""Two ways to compare the v2 owner layer against WoW's portfolios.

Default (``main``): per-OPERATOR fragmentation demo — resolve records -> entities with
Splink, then show how many separate Portfolios the *current KG* scatters those same
buildings across (Croman 4->1, etc.).

``--divergence`` (``wow_divergence``): POPULATION-scale partition divergence — how much,
and in which direction, the two *materialized* groupings differ over the buildings both
systems group. Reads the shipped layers (WoW ``wow.wow_portfolios`` in Postgres + v2
``IN_OWNER_GROUP`` in Neo4j); it does NOT re-run the ~1-min Splink resolve. This is a
DIVERGENCE measure (how far apart / which way), NOT an accuracy measure (who is right) —
there is no ground truth here; adjudication (the blind eval) is what decides who is right.

  uv run --extra ingest python -m watchline.discovery.ingest.portfolio.compare_kg
  uv run --extra ingest python -m watchline.discovery.ingest.portfolio.compare_kg --divergence
"""
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("splink").setLevel(logging.ERROR)

import argparse
from collections import defaultdict

import pandas as pd

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE
from watchline.discovery.ingest.portfolio import splink_source as ss
from watchline.discovery.ingest.portfolio.eval.build_gold import TARGET_WHERE, NBR_WHERE

KG_FRAGMENTATION = """
UNWIND $bbls AS bbl
MATCH (b:Building {bbl: bbl})
OPTIONAL MATCH (b)-[:IN_PORTFOLIO]->(p:Portfolio)
RETURN count(DISTINCT b) AS in_kg, count(DISTINCT p) AS kg_portfolios
"""

# v2 owner-group membership by building, over the MATERIALIZED ownership layer (IN_OWNER_GROUP
# is multi-member only, so this is exactly the v2 "grouped" universe — singletons are their own
# owner and excluded, matching WoW's multi-building-portfolio restriction below).
_V2_GROUPS = """
MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
UNWIND l.bbls AS bbl
RETURN og.owner_group_id AS g, collect(DISTINCT bbl) AS bbls
"""


def wow_divergence(conn, driver) -> dict:
    """Partition divergence of the v2 owner layer vs WoW portfolios, over the buildings BOTH
    systems group (multi-building WoW portfolios ∩ multi-member v2 owner-groups).

    Returns counts in BOTH directions — this is divergence, not accuracy:
      - ``v2_merges`` / ``v2_merges_bldgs``: v2 owner-groups that span >=2 WoW portfolios
        (v2 unifies what WoW split — the expected de-fragmentation of one owner's LLCs).
      - ``v2_splits`` / ``v2_splits_bldgs``: WoW portfolios that span >=2 v2 owner-groups
        (WoW merged what v2 keeps apart — the flip side of the three-layer thesis: v2 does
        not glue owners on a shared management office). Co-op/condo buildings are dropped by
        v2 entirely, so they are OUT of this shared universe — the splits are genuine
        partition differences, not co-op/condo artifacts.
      - ``agree``: v2 groups mapping 1:1 to a single WoW portfolio.
    Neither direction is a quality claim; which divergences are improvements is what the
    blind eval (not yet run) decides.
    """
    bbl_wow, wow_size = {}, defaultdict(int)
    with conn.cursor() as cur:
        cur.execute("SELECT orig_id, bbls FROM wow.wow_portfolios WHERE array_length(bbls,1) >= 2")
        for pid, bbls in cur.fetchall():
            for b in (bbls or []):
                bbl_wow[b.strip()] = pid
                wow_size[pid] += 1

    bbl_v2 = {}
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        for r in s.run(_V2_GROUPS):
            for b in r["bbls"]:
                bbl_v2[str(b).strip()] = r["g"]

    both = set(bbl_wow) & set(bbl_v2)
    v2_to_wow, wow_to_v2 = defaultdict(set), defaultdict(set)
    for b in both:
        v2_to_wow[bbl_v2[b]].add(bbl_wow[b])
        wow_to_v2[bbl_wow[b]].add(bbl_v2[b])

    merge_groups = {g for g, ps in v2_to_wow.items() if len(ps) >= 2}
    split_ports = {p for p, gs in wow_to_v2.items() if len(gs) >= 2}
    return {
        "wow_portfolios": len(wow_size), "wow_bbls": sum(wow_size.values()),
        "v2_groups": len(set(bbl_v2.values())), "v2_bbls": len(bbl_v2),
        "shared_universe": len(both),
        "v2_merges": len(merge_groups),
        "v2_merges_bldgs": sum(1 for b in both if bbl_v2[b] in merge_groups),
        "v2_splits": len(split_ports),
        "v2_splits_bldgs": sum(1 for b in both if bbl_wow[b] in split_ports),
        "agree": len(v2_to_wow) - len(merge_groups),
    }


def print_divergence(d: dict) -> None:
    print(f"WoW multi-building portfolios:        {d['wow_portfolios']:>6}  ({d['wow_bbls']} bbls)")
    print(f"v2 multi-member owner-groups:         {d['v2_groups']:>6}  ({d['v2_bbls']} bbls)")
    print(f"shared universe (grouped in BOTH):    {d['shared_universe']:>6}  buildings")
    print()
    print("  (divergence, not accuracy — how far apart and which way the two groupings differ, not who is right)")
    print(f"v2 MERGES what WoW splits:  {d['v2_merges']:>5} v2 groups span >=2 WoW portfolios  ({d['v2_merges_bldgs']} bldgs)")
    print(f"v2 SPLITS what WoW merges:  {d['v2_splits']:>5} WoW portfolios span >=2 v2 groups  ({d['v2_splits_bldgs']} bldgs)")
    print(f"agree (1:1 on the rest):    {d['agree']:>5} v2 groups map to a single WoW portfolio")


def divergence_main():
    conn = pg_conn()
    driver = neo4j_driver()
    try:
        print_divergence(wow_divergence(conn, driver))
    finally:
        conn.close()
        driver.close()


def main():
    conn = pg_conn()
    df = pd.concat([ss.extract(conn, TARGET_WHERE),
                    ss.extract(conn, NBR_WHERE),
                    ss.extract(conn, "random() < 0.012")], ignore_index=True)
    degs = ss.address_degrees(conn)
    conn.close()
    df = df[df.contact_kind == "person"].drop_duplicates("unique_id").reset_index(drop=True)

    linker, preds = ss.fit(df, addr_degrees=degs)
    clusters = ss.cluster(linker, preds, threshold=0.9)
    port = ss.build_portfolios(df, clusters)
    print(f"records {len(df)} -> {len(port)} resolved entities "
          f"({(port.n_records > 1).sum()} multi-record)\n")

    try:
        driver = neo4j_driver()
    except Exception as e:
        print(f"(KG comparison skipped — no Neo4j: {type(e).__name__})")
        print(port[port.n_bbls >= 3][["name", "n_records", "n_bbls"]].head(12).to_string(index=False))
        return

    hdr = f"{'resolved entity':<20}{'recs':>5}{'Splink bbls':>13}{'in KG':>7}{'KG portfolios':>15}"
    print(hdr); print("-" * len(hdr))
    with driver.session(database=NEO4J_DISCOVERY_DATABASE) as s:
        for key in ["CROMAN", "RASHAD", "CASTELLANO", "KADDEN"]:
            for _, r in port[port.name.str.contains(key)].head(2).iterrows():
                if r.n_bbls < 3:
                    continue
                rec = s.run(KG_FRAGMENTATION, bbls=r.bbls).single()
                print(f"{r['name'][:19]:<20}{r.n_records:>5}{r.n_bbls:>13}"
                      f"{rec['in_kg']:>7}{rec['kg_portfolios']:>15}")
    driver.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--divergence", action="store_true",
                    help="population-scale v2-vs-WoW partition divergence over the materialized "
                         "layers (divergence, not accuracy); skips the per-operator Splink resolve")
    args = ap.parse_args()
    divergence_main() if args.divergence else main()
