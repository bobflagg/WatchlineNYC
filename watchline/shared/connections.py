import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


NEO4J_DISCOVERY_DATABASE   = os.environ.get("NEO4J_DISCOVERY_DATABASE",   "discovery")



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
