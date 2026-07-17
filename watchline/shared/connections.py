import os

import psycopg2
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_EVIDENTIARY_DATABASE = os.environ.get("NEO4J_EVIDENTIARY_DATABASE", "evidentiary")
NEO4J_DISCOVERY_DATABASE   = os.environ.get("NEO4J_DISCOVERY_DATABASE",   "discovery")

# --- pg_conn() hang guardrails ----------------------------------------------
# Added after a 24h+ silent hang in acris_mortgages step 3: pg_conn() used to
# set no connect timeout and no TCP keepalives, so once a connection's socket
# went stale mid-run (a long crfn lookup against an unindexed column, or a
# network blip on a multi-hour session), the client blocked forever on
# recv() -- no error, no CPU usage, nothing in pg_stat_activity to show
# anything was even happening.
#
# connect_timeout and keepalives are safe to enable unconditionally: they
# only affect the initial handshake and genuinely idle/dead sockets, never a
# query that's actively streaming rows, so they cannot kill a healthy
# long-running pipeline step.
#
# statement_timeout is a blunter tool -- every FETCH on a named/server-side
# cursor is its own statement, so it bounds a single slow fetch rather than
# an entire multi-hour ingestion run, but several of this codebase's queries
# do a full sort before the first row can stream out (e.g. acris_deeds' and
# acris_mortgages' DISTINCT ON ... ORDER BY), and there's no timing data for
# every existing pipeline's queries under production load. Left OFF by
# default (0 = disabled, Postgres's own default) so this change can't
# silently break an existing pipeline; set PG_STATEMENT_TIMEOUT_MS to opt in
# for a given run once a step's expected duration is known.
PG_CONNECT_TIMEOUT      = int(os.environ.get("PG_CONNECT_TIMEOUT", "10"))       # seconds, initial TCP connect
PG_STATEMENT_TIMEOUT_MS = int(os.environ.get("PG_STATEMENT_TIMEOUT_MS", "0"))   # 0 = no timeout
PG_KEEPALIVES_IDLE      = int(os.environ.get("PG_KEEPALIVES_IDLE", "30"))       # seconds idle before probing starts
PG_KEEPALIVES_INTERVAL  = int(os.environ.get("PG_KEEPALIVES_INTERVAL", "10"))   # seconds between probes
PG_KEEPALIVES_COUNT     = int(os.environ.get("PG_KEEPALIVES_COUNT", "5"))       # failed probes before giving up on the connection


def pg_conn():
    kwargs = dict(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        connect_timeout=PG_CONNECT_TIMEOUT,
        keepalives=1,
        keepalives_idle=PG_KEEPALIVES_IDLE,
        keepalives_interval=PG_KEEPALIVES_INTERVAL,
        keepalives_count=PG_KEEPALIVES_COUNT,
    )
    if PG_STATEMENT_TIMEOUT_MS:
        kwargs["options"] = f"-c statement_timeout={PG_STATEMENT_TIMEOUT_MS}"
    return psycopg2.connect(**kwargs)


def neo4j_driver():
    """Return a driver for the shared Neo4j instance.

    Open sessions with the appropriate database constant:
        driver.session(database=NEO4J_EVIDENTIARY_DATABASE)
        driver.session(database=NEO4J_DISCOVERY_DATABASE)
    """
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
