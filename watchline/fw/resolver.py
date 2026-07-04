"""
watchline/fw/resolver.py

Entity resolution for the Watchline pipeline.
Resolves building addresses to BBLs and actor names to canonical Actor nodes.
"""

from watchline.fw.connections import neo4j_query, normalize_address


BUILDING_LOOKUP_CYPHER = """
MATCH (bld:Building)
WHERE ($bbl IS NOT NULL AND bld.bbl = $bbl)
   OR ($address IS NOT NULL AND $borough IS NOT NULL
       AND (toLower(bld.address) CONTAINS toLower($address)
            OR toLower($address) CONTAINS toLower(bld.address))
       AND bld.borough = $borough)
   OR ($address IS NOT NULL AND $borough IS NULL
       AND (toLower(bld.address) CONTAINS toLower($address)
            OR toLower($address) CONTAINS toLower(bld.address)))
RETURN bld.bbl      AS bbl,
       bld.address  AS address,
       bld.borough  AS borough,
       bld.residential_units AS units,
       bld.rs_units_current  AS rs_units,
       bld.rs_deregulating   AS rs_deregulating
LIMIT 1
"""

ACTOR_LOOKUP_CYPHER = """
MATCH (a:Actor)
WHERE toLower(a.display_name) CONTAINS toLower($actor_name)
RETURN a.canonical_id  AS canonical_id,
       a.display_name  AS display_name,
       a.actor_type    AS actor_type
LIMIT 1
"""


def resolve_building(intent: dict) -> tuple[dict | None, str | None]:
    """
    Resolve a building from intent fields (bbl, address, borough).

    Returns:
        (building_record, error_message)
        building_record is None if resolution fails.
    """
    raw_address = intent.get("address")
    normalized  = normalize_address(raw_address) if raw_address else None

    results = neo4j_query(
        BUILDING_LOOKUP_CYPHER,
        params={
            "bbl":     intent.get("bbl"),
            "address": normalized,
            "borough": intent.get("borough"),
        },
    )

    if not results:
        location = raw_address or intent.get("entity_raw", "unknown")
        borough  = intent.get("borough")
        suffix   = f" in {borough}" if borough else ""
        return None, (
            f"I couldn't find a building matching '{location}'{suffix} "
            f"in the Watchline database. Could you check the address "
            f"or provide the BBL?"
        )

    return results[0], None


def resolve_actor(intent: dict) -> tuple[dict | None, str | None]:
    """
    Resolve an actor from intent fields (actor_name).

    Returns:
        (actor_record, error_message)
        actor_record is None if resolution fails.
    """
    actor_name = intent.get("actor_name")
    if not actor_name:
        return None, (
            "I wasn't able to identify a landlord or owner name in your question. "
            "Could you provide a name to search for?"
        )

    results = neo4j_query(ACTOR_LOOKUP_CYPHER, params={"actor_name": actor_name})

    if not results:
        return None, (
            f"I couldn't find a landlord or ownership network matching "
            f"'{actor_name}' in the Watchline database."
        )

    return results[0], None
