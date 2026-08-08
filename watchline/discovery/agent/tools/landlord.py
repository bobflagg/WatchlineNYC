"""Resolve a typed landlord name to a ``Landlord`` entity. Phase 2 (P2-3).

The name front door. Given a name a user typed, find the landlord it denotes —
or, when more than one plausibly matches, return a capped candidate list and let
the caller ask which was meant. **Never a fuzzy-match guess** (``CLAUDE.md``
ambiguity contract, decision D2).

Two things make this harder than an equality check, both from the survey:

* **The stored names are dirty** — ``',MARIA CROSS'``, ``'.ARSILLO ANGELO'``,
  ``'(LARS) PETER LIBERT'`` — with leading punctuation, parentheticals, and
  frequent surname-first ordering. So matching runs over a ``FULLTEXT`` index
  (``landlord_name_fulltext``), and both the query and every candidate are
  compared on normalized tokens via :mod:`..names`, never raw strings.
* **A search score is not an identity claim.** The fulltext relevance score is
  used only to *rank retrieval*; it is never returned as evidence that two names
  are the same party. Plausibility is decided with the same guardrail-safe
  verdict the ownership tool uses (:func:`compare_names`) — an exact normalized-
  token match is a resolution; anything short of that is a candidate to
  disambiguate, not a guess to commit to.

This tool is **Type II** — it touches ``Landlord``, an inferred-identity entity —
so the ``Landlord`` caveat travels with every result automatically. It stays
visible at ``public`` trust (Type II is not gated).
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..names import OwnershipVerdict, compare_names, normalize
from ..reliability import tagged

__all__ = ["resolve_landlord_name", "TOOL_DESCRIPTION", "MAX_CANDIDATES"]

TOOL_DESCRIPTION = (
    "Resolve the name of a landlord or owner to a specific entity in the graph. "
    "Call this whenever the user names a landlord, owner, or company by name "
    "rather than by id — for example 'what does Steven Croman own?' — to get the "
    "landlord's actor_id for the ownership and portfolio tools. Returns the "
    "resolved landlord when one clearly matches, or a short list of candidates to "
    "disambiguate when several do — never a single silent best guess."
)

#: Cap on candidates surfaced for disambiguation (CLAUDE.md caps at ~5).
MAX_CANDIDATES = 5

#: How many matches to pull from the fulltext index before classifying. Enough
#: to detect that several plausibly match without scanning the long tail of
#: weak single-token hits.
_FETCH_LIMIT = 25

#: Fulltext over Landlord.name, ranked by relevance (used for ordering only,
#: never returned). ``building_count`` is the size of the landlord's apparently-
#: controlled ``bbls`` list — a distinguishing detail for disambiguation.
_SEARCH_CYPHER = (
    "CALL db.index.fulltext.queryNodes('landlord_name_fulltext', $query) "
    "YIELD node, score "
    "WITH node, score ORDER BY score DESC LIMIT $limit "
    "RETURN node.actor_id AS actor_id, node.name AS name, node.bizaddr AS bizaddr, "
    "size(coalesce(node.bbls, [])) AS building_count"
)


def _candidate(row: dict[str, Any], query: str) -> dict[str, Any]:
    """One landlord match, with the evidence for how well it matches the query.

    The evidence is a :func:`compare_names` verdict — shared tokens, not a score
    — so a caller can see *why* a candidate is or is not a confident match.
    """
    comparison = compare_names(query, row["name"])
    return {
        "actor_id": row["actor_id"],
        "name": row["name"],
        "business_address": row["bizaddr"],
        "building_count": row["building_count"],
        "match": {
            "verdict": comparison.verdict.value,
            "shared_tokens": list(comparison.shared_tokens),
            "shared_distinguishing_tokens": list(comparison.shared_distinguishing),
        },
    }


@tagged(["Landlord"])
def resolve_landlord_name(name: str) -> dict[str, Any]:
    """Resolve ``name`` to a landlord, or to a capped candidate list.

    :param name: A landlord/owner name as a user typed it. Dirty, possibly
        surname-first, possibly punctuated — normalization handles it.

    Result classes, each a distinct ``status``:

    * ``resolved`` — exactly one candidate's normalized tokens match the query
      (an :attr:`~OwnershipVerdict.AGREES` verdict). The ``landlord`` field
      carries its ``actor_id`` for downstream tools.
    * ``needs_disambiguation`` — several plausibly match (several exact matches,
      or none exact). A list capped at :data:`MAX_CANDIDATES`, each with its
      name, business address, controlled-building count, and match evidence, plus
      the total considered. The caller asks which was meant — this tool never
      picks.
    * ``not_found`` — the fulltext search returned nothing.
    * ``invalid_input`` — the name had no usable tokens.

    ``reliability`` is attached automatically: Type II, with the ``Landlord``
    caveat.
    """
    if not isinstance(name, str) or not normalize(name):
        return {
            "status": "invalid_input",
            "query": name if isinstance(name, str) else repr(name),
            "message": "No searchable name was provided.",
        }

    query = " ".join(normalize(name))  # tokens are [0-9a-z], so injection-safe
    rows = read(_SEARCH_CYPHER, {"query": query, "limit": _FETCH_LIMIT}).records

    if not rows:
        return {
            "status": "not_found",
            "query": name,
            "candidates": [],
            "message": f"No landlord in the discovery graph matches {name!r}.",
        }

    candidates = [_candidate(row, name) for row in rows]
    exact = [c for c in candidates if c["match"]["verdict"] == OwnershipVerdict.AGREES.value]

    # Exactly one exact-token match is a resolution. Anything else — several
    # exact matches, or none exact — is disambiguated rather than guessed.
    if len(exact) == 1:
        return {
            "status": "resolved",
            "query": name,
            "landlord": exact[0],
            "message": f"Resolved {name!r} to landlord {exact[0]['actor_id']}.",
        }

    shortlist = (exact if len(exact) > 1 else candidates)[:MAX_CANDIDATES]
    considered = len(exact) if len(exact) > 1 else len(candidates)
    return {
        "status": "needs_disambiguation",
        "query": name,
        "candidates": shortlist,
        "candidate_total": considered,
        "candidates_truncated": considered > len(shortlist),
        "message": (
            f"{considered} landlords plausibly match {name!r}. Ask the user which "
            "they mean — do not assume."
        ),
    }
