"""
watchline/fw/connections.py

Shared connection factories for the LLM and Neo4j graph database.
"""

import os
import re

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from neo4j import GraphDatabase

load_dotenv()


def get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=2048,
    )


def neo4j_query(cypher: str, params: dict = None) -> list:
    """Run a read-only Cypher query and return results as a list of dicts."""
    driver = GraphDatabase.driver(
        os.environ["NEO4J_EPISTEMIC_URI"],
        auth=(
            os.environ["NEO4J_EPISTEMIC_USER"],
            os.environ["NEO4J_EPISTEMIC_PASSWORD"],
        ),
    )
    database = os.environ.get("NEO4J_EPISTEMIC_DATABASE", "neo4j")
    try:
        result = driver.execute_query(
            cypher,
            parameters_=params or {},
            database_=database,
        )
        return [dict(record) for record in result.records]
    finally:
        driver.close()


def normalize_address(address: str) -> str:
    """
    Normalize a street address for fuzzy matching against the graph.
    Strips ordinal suffixes (1st->1, 2nd->2, 169th->169) and uppercases.
    Graph addresses are stored as '530 EAST 169 STREET' not '530 East 169th Street'.
    """
    if not address:
        return address
    normalized = re.sub(
        r"(\d+)(st|nd|rd|th)\b", r"\1", address, flags=re.IGNORECASE
    )
    return normalized.upper().strip()
