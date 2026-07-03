#!/usr/bin/env python3
"""
Test script to verify both Neo4j Knowledge Graphs are up and running.
"""

from neo4j import GraphDatabase

# Connection settings
DOMAIN_URI = "bolt://localhost:7687"
EPISTEMIC_URI = "bolt://localhost:7688"
USERNAME = "neo4j"
PASSWORD = "watchline"


def test_domain_kg():
    print("Testing Domain KG (bolt://localhost:7687)...")
    try:
        driver = GraphDatabase.driver(DOMAIN_URI, auth=(USERNAME, PASSWORD))
        with driver.session() as session:
            result = session.run("MATCH (n:Portfolio) RETURN count(n) as number_of_portfolios;")
            record = result.single()
            count = record["number_of_portfolios"]
            print(f"  ✅ Connected successfully — {count} Portfolio node(s) found.")
        driver.close()
    except Exception as e:
        print(f"  ❌ Failed to connect: {e}")


def test_epistemic_kg():
    print("Testing Epistemic KG (bolt://localhost:7688)...")
    try:
        driver = GraphDatabase.driver(EPISTEMIC_URI, auth=(USERNAME, PASSWORD))
        with driver.session() as session:
            result = session.run("MATCH (n:Building) RETURN count(n) as number_of_buildings;")
            record = result.single()
            count = record["number_of_buildings"]
            print(f"  ✅ Connected successfully — {count} Building node(s) found.")
        driver.close()
    except Exception as e:
        print(f"  ❌ Failed to connect: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Neo4j Knowledge Graph Connection Test")
    print("=" * 50)
    test_domain_kg()
    test_epistemic_kg()
    print("=" * 50)
    print("Done.")
