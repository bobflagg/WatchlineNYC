import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
import psycopg2

load_dotenv()


def pg_conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def neo4j_driver():
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )


NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
