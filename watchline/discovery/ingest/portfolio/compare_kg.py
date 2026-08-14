"""End-to-end check of the two-stage pipeline: resolve records -> entities with
Splink, aggregate entities into portfolios, then show how many separate portfolios
the *current KG* scatters those same buildings across.

  uv run --extra ingest python -m watchline.discovery.ingest.portfolio.compare_kg
"""
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("splink").setLevel(logging.ERROR)

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
    main()
