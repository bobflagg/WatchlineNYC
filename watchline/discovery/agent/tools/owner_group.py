"""Owner-identity tools — the OwnerGroup layer.

The owner-identity partition: the differently-named landlord entities that a
precision-first record-linkage step inferred to be the **same owner** across
shell LLCs, materialized as ``(:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup)``.
This is a *different question* from the two grouping layers the agent already
knows:

* ``Portfolio`` (``landlord_portfolio``) — an operational/address nexus: buildings
  that run through a shared office, agent, or shell network. Recall-biased, and a
  shared office is **not** shared ownership (a management megaoffice ties together
  many unrelated owners).
* ``OwnerGroup`` (here) — inferred **owner identity**: one owner's buildings
  pulled together across their differently-named LLCs. Precision-first.

Everything here touches ``OwnerGroup`` — a derived element — so every result is
**Type II** and ships the canonical owner-group caveat automatically (owner
identity is an inference, never a legal ownership determination; wording lives in
:mod:`..caveats`). Figures (``member_count``/``building_count``) are read from the
node, not recomputed, and the group's ``composition``/``method``/``generated_at``
travel with the answer as provenance — an owner group is a specific resolution
run's output, not a standing fact.
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged

__all__ = [
    "owner_group_for_landlord",
    "owner_group_portfolio",
    "OWNER_GROUP_FOR_LANDLORD_DESCRIPTION",
    "OWNER_GROUP_PORTFOLIO_DESCRIPTION",
]

#: How many member-fragment names / building samples to surface. A large owner
#: group is summarized, not dumped (CLAUDE.md: compact large outputs to a summary
#: + stable ids); the precomputed counts carry the totals.
_SAMPLE_CAP = 15

OWNER_GROUP_FOR_LANDLORD_DESCRIPTION = (
    "Find the owner group a landlord belongs to, by actor_id — the set of "
    "differently-named landlord entities inferred to be the SAME OWNER (owner "
    "identity across shell LLCs). Returns the owner_group_id, the group's name, "
    "how many landlord fragments it unifies, and its total buildings. Call this to "
    "answer 'who really owns this' or 'are these the same owner', and to turn a "
    "landlord's actor_id into the unified owner. Returns no group for a landlord "
    "that stands alone (a singleton is its own owner). Distinct from portfolio "
    "(operational/address nexus) and manager (who runs the building). Owner "
    "identity is inferred, not a legal determination."
)

OWNER_GROUP_PORTFOLIO_DESCRIPTION = (
    "Show a unified owner's full holdings by owner_group_id: the landlord "
    "fragments it merges and the total distinct buildings across all their "
    "differently-named LLCs. This is the de-fragmented owner view — one operator's "
    "buildings scattered under many LLC names, pulled together into one owner. "
    "Reads precomputed figures. This grouping is an inference across "
    "differently-named LLCs, not a legal ownership determination."
)

_OWNER_GROUP_FOR_LANDLORD_CYPHER = (
    "MATCH (l:Landlord {actor_id: $actor_id}) "
    "OPTIONAL MATCH (l)-[:IN_OWNER_GROUP]->(o:OwnerGroup) "
    "RETURN l.actor_id AS actor_id, l.name AS name, "
    "CASE WHEN o IS NULL THEN NULL ELSE { "
    "  owner_group_id: o.owner_group_id, name: o.name, "
    "  member_count: o.member_count, building_count: o.building_count, "
    "  composition: o.composition, method: o.method, "
    "  generated_at: toString(o.generated_at) "
    "} END AS owner_group"
)

_OWNER_GROUP_PORTFOLIO_CYPHER = (
    "MATCH (o:OwnerGroup {owner_group_id: $owner_group_id}) "
    "OPTIONAL MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(o) "
    "WITH o, [ x IN collect(DISTINCT l.name) WHERE x IS NOT NULL ] AS member_names, "
    "     [ x IN collect(DISTINCT l.actor_id) WHERE x IS NOT NULL ] AS member_ids "
    "RETURN o.owner_group_id AS owner_group_id, o.name AS name, "
    "o.member_count AS member_count, o.building_count AS building_count, "
    "o.composition AS composition, o.method AS method, "
    "toString(o.generated_at) AS generated_at, member_names, member_ids"
)

# A bounded sample of the owner's buildings — capped in-query so a large owner
# never streams thousands of rows. Distinct bbls across the group's members.
_OWNER_GROUP_BUILDINGS_SAMPLE_CYPHER = (
    "MATCH (l:Landlord)-[:IN_OWNER_GROUP]->(:OwnerGroup {owner_group_id: $owner_group_id}) "
    "UNWIND l.bbls AS bbl "
    "WITH DISTINCT bbl LIMIT $cap "
    "MATCH (b:Building {bbl: bbl}) "
    "RETURN collect({bbl: b.bbl, address: b.address, borough: b.borough}) AS sample"
)


def _invalid(key_name: str, value: Any) -> dict[str, Any]:
    return {
        "found": False,
        key_name: value if isinstance(value, str) else repr(value),
        "reason": f"A {key_name} is required.",
    }


@tagged(["Landlord", "OwnerGroup", "IN_OWNER_GROUP"])
def owner_group_for_landlord(actor_id: str) -> dict[str, Any]:
    """Return the owner group a landlord belongs to. Type II — inferred identity.

    ``owner_group`` is ``None`` for a landlord in no multi-member group: a
    singleton is its own owner, which is a normal, complete answer — not an
    error. When present, it carries the group's precomputed ``member_count`` and
    ``building_count`` and the resolution run's ``composition``/``method``/
    ``generated_at``. The owner-group caveat travels with the result.
    """
    if not isinstance(actor_id, str) or not actor_id.strip():
        return _invalid("actor_id", actor_id)
    row = read(_OWNER_GROUP_FOR_LANDLORD_CYPHER, {"actor_id": actor_id.strip()}).single
    if row is None:
        return {
            "found": False,
            "actor_id": actor_id.strip(),
            "reason": f"No landlord in the discovery graph with actor_id "
            f"{actor_id.strip()}.",
        }
    owner_group = row["owner_group"]
    return {
        "found": True,
        "actor_id": row["actor_id"],
        "name": row["name"],
        "owner_group": owner_group,
        # A singleton is its own owner — say so, so the caller does not read a
        # null group as a lookup failure.
        "note": (
            None
            if owner_group is not None
            else "This landlord is in no multi-member owner group — on the "
            "current resolution it stands alone (its own owner)."
        ),
    }


@tagged(["Landlord", "OwnerGroup", "IN_OWNER_GROUP", "Building"])
def owner_group_portfolio(owner_group_id: str) -> dict[str, Any]:
    """Return a unified owner's holdings: the fragments it merges and its total
    buildings. Type II.

    The de-fragmented owner view — one owner's buildings across many
    differently-named LLCs, pulled together. ``member_count``/``building_count``
    are read from the ``OwnerGroup`` node (not recomputed); ``member_names`` and
    ``buildings_sample`` are capped summaries, with the totals carried by the
    counts. ``composition`` (``identity`` / ``deed_only`` / ``deed_bridged``)
    discloses how the group was assembled.
    """
    if not isinstance(owner_group_id, str) or not owner_group_id.strip():
        return _invalid("owner_group_id", owner_group_id)
    gid = owner_group_id.strip()
    row = read(_OWNER_GROUP_PORTFOLIO_CYPHER, {"owner_group_id": gid}).single
    if row is None:
        return {
            "found": False,
            "owner_group_id": gid,
            "reason": f"No owner group with id {gid}. Owner-group ids are "
            "regenerated each resolution run and are not stable across runs.",
        }
    sample = read(
        _OWNER_GROUP_BUILDINGS_SAMPLE_CYPHER, {"owner_group_id": gid, "cap": _SAMPLE_CAP}
    ).single
    member_names = row["member_names"]
    return {
        "found": True,
        "owner_group_id": row["owner_group_id"],
        "name": row["name"],
        "member_count": row["member_count"],
        "building_count": row["building_count"],
        "composition": row["composition"],
        # Capped summaries — the counts above are authoritative.
        "member_names": member_names[:_SAMPLE_CAP],
        "member_names_truncated": len(member_names) > _SAMPLE_CAP,
        "member_ids": row["member_ids"][:_SAMPLE_CAP],
        "buildings_sample": (sample["sample"] if sample else []),
        "provenance": {"method": row["method"], "generated_at": row["generated_at"]},
    }
