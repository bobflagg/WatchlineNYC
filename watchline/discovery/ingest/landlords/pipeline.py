"""
Watchline Discovery KG — landlords_with_connections build (Postgres prep step)
watchline/discovery/ingest/landlords/pipeline.py

Builds the WoW landlord-graph table `landlords_with_connections` from `wow_landlords`,
using WoW's own algorithm (vendored `landlords_with_connections.sql`). This lets the whole
KG derive from JustFix's `justfixwow` dump — which already ships `wow.wow_landlords` — with
NO separate Who Owns What build to maintain, and stays in sync with JustFix by construction.

Why this step exists:
    `hpd_registrations` (Actor identity) and `portfolio` (clustering + Splink) both read
    `landlords_with_connections`, keyed on `nodeid`. The JustFix dump provides the *inputs*
    (`wow.wow_landlords`) but not this derived graph table, so we materialize it here.

Schema resolution (no qualification needed downstream):
    We run WoW's SQL unqualified, exactly as WoW does. The table lands in the connecting
    user's default schema — in `justfixwow` that's the `wow` schema (search_path is
    "$user",public and the user is `wow`), which is also where `wow_landlords` lives and
    where every pipeline's unqualified `landlords_with_connections` read resolves. (Against
    a plain `wow` database with no `wow` schema, the same default lands it in `public` — also
    correct there.) So this one build makes `PGDATABASE=justfixwow` work end-to-end.

Run order:  schema -> [THIS] -> buildings -> hpd_registrations -> events -> portfolio.
Idempotent: the SQL drops and rebuilds the table, so re-running is safe.

Usage:
    uv run python -m watchline.discovery.ingest.landlords.pipeline
    uv run python -m watchline.discovery.ingest.landlords.pipeline --verify-only
"""

import argparse
import time
from pathlib import Path

from watchline.shared.connections import pg_conn

SQL_PATH = Path(__file__).parent / "landlords_with_connections.sql"

# WoW's landlords_with_connections over the current wow_landlords dump has this many
# nodes; used only as a sanity signal (warn, don't fail) since the dump can change.
EXPECTED_ROWS_HINT = 118_493


def _counts(cur) -> tuple[int, int]:
    cur.execute("SELECT count(*) FROM wow_landlords")
    src = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM landlords_with_connections")
    return src, cur.fetchone()[0]


def build(conn) -> int:
    """Run the vendored SQL, materializing landlords_with_connections. Returns row count."""
    sql = SQL_PATH.read_text()
    with conn.cursor() as cur:
        print("Building landlords_with_connections from wow_landlords (pg_trgm self-join) ...")
        t0 = time.perf_counter()
        cur.execute(sql)
        conn.commit()
        src, rows = _counts(cur)
        cur.execute("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.oid = to_regclass('landlords_with_connections')")
        schema = cur.fetchone()[0]
    dt = time.perf_counter() - t0
    print(f"  wrote {schema}.landlords_with_connections: {rows:,} nodes "
          f"from {src:,} wow_landlords rows  ({dt:.1f}s)")
    if abs(rows - EXPECTED_ROWS_HINT) > EXPECTED_ROWS_HINT * 0.1:
        print(f"  NOTE: expected ~{EXPECTED_ROWS_HINT:,} nodes for the reference dump; "
              f"got {rows:,} — verify the wow_landlords source if this is unexpected.")
    return rows


def verify(conn) -> None:
    """Read-only check that the table exists, is non-empty, and carries edge info."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('landlords_with_connections')")
        if cur.fetchone()[0] is None:
            raise SystemExit("landlords_with_connections not found — run the build first.")
        src, rows = _counts(cur)
        cur.execute("SELECT count(*) FROM landlords_with_connections "
                    "WHERE name_match_info IS NOT NULL OR bizaddr_match_info IS NOT NULL")
        with_edges = cur.fetchone()[0]
    print(f"landlords_with_connections: {rows:,} nodes ({with_edges:,} with connections) "
          f"from {src:,} wow_landlords rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-only", action="store_true",
                    help="only report the existing table, don't rebuild")
    args = ap.parse_args()
    conn = pg_conn()
    try:
        (verify if args.verify_only else build)(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
