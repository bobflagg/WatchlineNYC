"""Who owns this building? The flagship Tier-1 tool.

``CLAUDE.md`` calls this the single most common Tier-1 query in the system and
says to get it right first. The rule it must follow, verbatim from the design:

    Always return **both** ``Building.dof_ownername`` (Type I, "recorded owner,"
    may be a shell LLC) and the ``Landlord`` reached via ``APPARENT_CONTROL``
    (Type II, "apparent controller"), clearly labeled. Never silently pick one.
    When they disagree, that disagreement is itself the interesting answer —
    surface it, don't hide it.

**Three facts measured in Phase 0 shape this tool more than anything else.**

1. ``APPARENT_CONTROL`` reaches only 171,347 of 859,794 buildings. **A building
   with no apparent controller is the majority result, not an error.** It returns
   a complete, successful answer carrying the recorded owner.
2. The two values cannot be string-compared — see
   :mod:`watchline.discovery.agent.names`. Comparison is a verdict with
   evidence, never a determination.
3. ``APPARENT_CONTROL`` is currently 1:1: every controlled building has exactly
   one controller. ``graph_type.cypher`` does **not** constrain that, so this
   tool returns a *collection* and never indexes ``[0]``. No fixture can
   exercise a multi-controller path, so nothing here claims to test one.

Also: 1,863 buildings have a null ``dof_ownername``, and some of those *do* have
a controller — so "controller present, recorded owner absent" is a real shape,
and it compares as ``NOT_COMPARABLE``.

``address`` and ``borough`` are returned for readability only. ``address`` is
PLUTO-normalized, non-unique, sometimes lacks a house number, and is sometimes
the literal string ``'Unknown'``. It is never a lookup key — that is what
``bbl`` is for, and from Phase 2, what Geosupport resolves to.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import read
from ..names import OwnershipVerdict, compare_names
from ..reliability import ReliabilityType, tagged

__all__ = [
    "lookup_building_ownership",
    "TOOL_DESCRIPTION",
    "RECORDED_OWNER_LABEL",
    "APPARENT_CONTROLLER_LABEL",
]

#: What the model is told about this tool. Kept separate from the developer
#: docstring and written to be prescriptive about *when* to call it — a
#: description that states the trigger condition measurably improves should-call
#: behaviour over one that only says what the tool does.
TOOL_DESCRIPTION = (
    "Look up who owns a specific NYC building by its BBL. Call this whenever the "
    "user asks who owns, controls, or is the landlord of a particular building. "
    "Returns two distinct answers that must both be reported: the recorded owner "
    "filed with the Department of Finance, and the apparent controller inferred "
    "by the graph. Takes a 10-digit BBL, not an address."
)

#: How the two answers are labelled in output. These are *labels*, not caveat
#: text — the caveats come from :mod:`..caveats` via the reliability decorator
#: and are never written here.
RECORDED_OWNER_LABEL = "recorded owner"
APPARENT_CONTROLLER_LABEL = "apparent controller"

_RECORDED_OWNER_SOURCE = "NYC Department of Finance, via Building.dof_ownername"
_APPARENT_CONTROLLER_SOURCE = "Inferred by the discovery graph, via APPARENT_CONTROL"

#: BBL is borough digit + 5-digit block + 4-digit lot. Verified 10 characters on
#: all 859,794 Building rows, with the borough digit in 1-5.
_BBL_PATTERN = re.compile(r"^[1-5][0-9]{9}$")

# Pattern comprehension rather than OPTIONAL MATCH: it yields [] for a building
# with no controller, where OPTIONAL MATCH + collect() would yield a row of
# nulls that the caller has to filter. Validated against the live graph
# 2026-07-31 for all three result classes.
_OWNERSHIP_CYPHER = """MATCH (b:Building {bbl: $bbl})
RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
       b.dof_ownername AS recorded_owner,
       [ (l:Landlord)-[ac:APPARENT_CONTROL]->(b) | {
           actor_id: l.actor_id, name: l.name, bizaddr: l.bizaddr,
           method: ac.method, run_id: ac.run_id
       } ] AS apparent_controllers"""


def _not_found(bbl: str, reason: str) -> dict[str, Any]:
    """An explicit not-found result.

    Distinct from an empty payload: a caller must be able to tell "no such
    building" from "building exists, nothing known about its ownership".
    """
    return {
        "bbl": bbl,
        "found": False,
        "reason": reason,
        "recorded_owner": None,
        "apparent_controllers": [],
        "verdict": None,
    }


def _describe_comparison(recorded: str | None, controller_name: str | None) -> dict[str, Any]:
    """Compare one controller against the recorded owner, with its evidence.

    The evidence is what keeps this an observation rather than a claim. A caller
    can show *which* tokens matched, so a reader can judge for themselves —
    which is the difference between reporting and determining.
    """
    comparison = compare_names(recorded, controller_name)
    return {
        "verdict": comparison.verdict.value,
        "shared_tokens": list(comparison.shared_tokens),
        "shared_distinguishing_tokens": list(comparison.shared_distinguishing),
        "recorded_owner_only_tokens": list(comparison.left_only),
        "apparent_controller_only_tokens": list(comparison.right_only),
    }


@tagged(["Building", "Building.dof_ownername", "APPARENT_CONTROL", "Landlord"])
def lookup_building_ownership(bbl: str) -> dict[str, Any]:
    """Return both ownership answers for a building, clearly labelled.

    :param bbl: 10-character BBL — borough digit, 5-digit block, 4-digit lot.
        This is the key; addresses are resolved to a BBL in Phase 2.

    Returns a payload carrying:

    * ``recorded_owner`` — ``Building.dof_ownername`` **verbatim**, labelled as
      the DOF record. Reliable, directly sourced, and frequently a shell entity.
    * ``apparent_controllers`` — a list (see the module docstring on cardinality)
      of inferred controllers, each with the ``method`` and ``run_id`` of the
      heuristic run that produced it, and its own comparison against the
      recorded owner.
    * ``verdict`` — a convenience summary for the ordinary case. ``None`` when
      there is more than one controller, since one verdict cannot describe
      several comparisons; read the per-controller ``comparison`` then.
    * ``reliability`` — attached automatically: Type II, with the ``Landlord``,
      ``APPARENT_CONTROL`` and ``dof_ownername`` caveats.

    Neither name is cleaned, title-cased, or reordered. The graph's exact record
    is what is citable, and the messiness is itself informative.
    """
    if not isinstance(bbl, str) or not _BBL_PATTERN.match(bbl.strip()):
        return _not_found(
            bbl if isinstance(bbl, str) else repr(bbl),
            "Not a valid BBL. Expected 10 digits: borough (1-5), 5-digit block, "
            "4-digit lot — for example '1000050010'.",
        )

    bbl = bbl.strip()
    result = read(_OWNERSHIP_CYPHER, {"bbl": bbl})
    row = result.single
    if row is None:
        return _not_found(bbl, f"No building in the discovery graph with BBL {bbl}.")

    recorded_owner_name = row["recorded_owner"]
    controllers: list[dict[str, Any]] = []
    for raw in row["apparent_controllers"]:
        controllers.append(
            {
                "actor_id": raw["actor_id"],
                "name": raw["name"],
                "label": APPARENT_CONTROLLER_LABEL,
                "business_address": raw["bizaddr"],
                "source": _APPARENT_CONTROLLER_SOURCE,
                "reliability_type": ReliabilityType.TYPE_II.value,
                # Provenance travels with the answer for the same reason
                # portfolios surface their run: this came from one heuristic
                # run and is not a standing fact about the world.
                "provenance": {"method": raw["method"], "run_id": raw["run_id"]},
                "comparison": _describe_comparison(recorded_owner_name, raw["name"]),
            }
        )

    # A single verdict describes a single comparison. With no controller there
    # is nothing to compare; with several, one verdict would be a fiction.
    if not controllers:
        verdict: str | None = OwnershipVerdict.NOT_COMPARABLE.value
    elif len(controllers) == 1:
        verdict = controllers[0]["comparison"]["verdict"]
    else:
        verdict = None

    return {
        "bbl": row["bbl"],
        "found": True,
        # Display fields. Never match on these — see the module docstring.
        "address": row["address"],
        "borough": row["borough"],
        "recorded_owner": (
            None
            if recorded_owner_name is None
            else {
                "name": recorded_owner_name,
                "label": RECORDED_OWNER_LABEL,
                "source": _RECORDED_OWNER_SOURCE,
                "reliability_type": ReliabilityType.TYPE_I.value,
            }
        ),
        "apparent_controllers": controllers,
        "verdict": verdict,
        "controller_count": len(controllers),
    }
