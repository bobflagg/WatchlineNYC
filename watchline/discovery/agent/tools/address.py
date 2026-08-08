"""Resolve a typed street address to a graph ``Building``. Phase 2 (P2-2, D9/D12).

The front door for everyone who does not already hold a BBL. Addresses resolve
through NYC DCP Geosupport (via the sidecar, decision D9), never by string
matching ``Building.address`` — which is PLUTO-normalized, non-unique, and
sometimes lacks a house number, so it is a display field only.

Three things the Phase 0 spike proved, each shaping this tool
(``specs/2026-07-30-phase-0-foundations/spike-findings.md``):

1. **A resolved BBL is a candidate, not an answer** (§6, D12). ~2% of addresses
   resolve to a different lot than the graph records. So every ``RESOLVED`` BBL
   is confirmed against the graph, and the graph's *own* stored address is what
   is handed back — a wrong match stays visible instead of being asserted.
2. **``GRC '00'`` does not guarantee a BBL** (§2). Success with an empty BBL is
   the real ``NO_TAX_LOT`` case; ``geocode.py`` already separates it, and this
   tool keeps it distinct from "no such building".
3. **The Queens numeric-street trap** (§5). ``'39 AVENUE'`` is a *street*, not
   house 39 of "AVENUE". Splitting on the first space is wrong there, so the
   split is a first attempt that retries with the whole string as the street
   name on a street-recognition failure.

Geosupport is **Type I** — a local, deterministic, offline, city-official
canonicalizer (decision D10), not the open-web search Type IV covers. So this
tool is visible at ``public`` trust like any other Tier 1 lookup.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import read
from ..geocode import Borough, GeocodeOutcome, GeocodeResult, GeosupportClient
from ..reliability import ExternalSource, tagged

__all__ = ["resolve_address", "TOOL_DESCRIPTION"]

TOOL_DESCRIPTION = (
    "Resolve a typed NYC street address to a specific building (its BBL). Call "
    "this whenever the user names a building by address rather than by BBL — for "
    "example 'who owns 115 Broad Street?' — to get the BBL the ownership and "
    "event tools need. Takes a street address and a borough name (Manhattan, "
    "Bronx, Brooklyn, Queens, or Staten Island). Returns the resolved building, "
    "or a capped list of candidate streets when the street is ambiguous — never "
    "a silent best guess."
)

#: Confirm a Geosupport-resolved BBL against the graph and hand back the graph's
#: own record. Type I (Building only); parameterized on $bbl.
_CONFIRM_CYPHER = (
    "MATCH (b:Building {bbl: $bbl}) "
    "RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough"
)

#: Leading house-number token: digits, optionally hyphenated (Queens house
#: numbers like ``232-05``). The rest is the street. This split is deliberately
#: provisional — see the numeric-street retry below.
_HOUSE_NUMBER = re.compile(r"^\s*(\d[\d-]*)\s+(\S.*)$")

#: Outcomes where the street itself was not recognized — the signal to retry a
#: numeric-street address whole (spike §5).
_STREET_FAILURES = frozenset(
    {GeocodeOutcome.STREET_AMBIGUOUS, GeocodeOutcome.STREET_NOT_RECOGNIZED}
)

#: A cached client, so the tool does not open an httpx connection per call.
#: Tests replace :func:`_client` (or monkeypatch ``read``) to stay hermetic.
_CLIENT: GeosupportClient | None = None


def _client() -> GeosupportClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GeosupportClient()
    return _CLIENT


def _split_address(address: str) -> tuple[str, str]:
    """Split into (house_number, street). ``house_number`` is ``''`` if none.

    Provisional by design: a leading number may be a house number *or* the start
    of a numbered street (``'39 AVENUE'``). The caller retries on a street
    failure rather than trusting this split.
    """
    match = _HOUSE_NUMBER.match(address)
    if match:
        return match.group(1), match.group(2).strip()
    return "", address.strip()


def _geocode(address: str, borough: Borough) -> GeocodeResult:
    """Resolve, retrying a numeric-street address whole on a street failure.

    Naive split sends ``'39 AVENUE'`` as house ``39`` / street ``AVENUE`` and
    Geosupport rejects the street. On any street-recognition failure where a
    house token was split off, retry once with the entire string as the street
    name (spike §5). Prefer the retry only when it does better; otherwise the
    first attempt's result — including its candidate list — is the more useful
    answer to surface.
    """
    house, street = _split_address(address)
    first = _client().resolve(house, street, borough)
    if first.outcome in _STREET_FAILURES and house:
        retry = _client().resolve("", address.strip(), borough)
        if retry.outcome not in _STREET_FAILURES:
            return retry
    return first


def _collapse(value: str | None) -> str | None:
    """Collapse Geosupport's internal padding (``'WEST   24 STREET'``)."""
    return " ".join(value.split()) if value else value


def _base(address: str, borough_name: str, result: GeocodeResult) -> dict[str, Any]:
    """Fields common to every non-error outcome."""
    return {
        "input_address": address,
        "borough": borough_name,
        "geosupport_outcome": result.outcome.value,
        "geosupport_display": _collapse(result.normalized_street),
    }


@tagged(["Building"], external_sources=[ExternalSource.GEOSUPPORT])
def resolve_address(address: str, borough: str) -> dict[str, Any]:
    """Resolve ``address`` in ``borough`` to a graph building.

    :param address: A typed street address, e.g. ``'115 Broad Street'``.
    :param borough: A borough name — Manhattan, Bronx, Brooklyn, Queens, or
        Staten Island.

    Every outcome is a distinct, complete result under ``status``:

    * ``resolved`` — Geosupport returned a BBL **and** the graph has that
      building. Carries the verbatim stored ``Building.address`` (a resolved BBL
      is a candidate; the graph's record is what is citable) and the
      Geosupport-canonical display form.
    * ``geocoded_but_absent`` — a valid NYC tax lot with no ``Building`` node.
      Its own answer, never conflated with "no such building".
    * ``no_tax_lot`` — the street and house parsed, but no tax lot exists.
    * ``street_ambiguous`` — a capped candidate list from the city's own street
      dictionary, with the true total; the disambiguation path, never a guess.
    * ``street_not_recognized`` / ``invalid_input`` — distinct, actionable.
    * ``geocoder_unavailable`` — the sidecar could not be reached. Never reported
      as "not found", which would look like a data gap rather than an outage.
    * ``invalid_borough`` — the borough name was not one of the five.

    ``reliability`` is attached automatically: Type I, via the Geosupport
    carve-out (D10), so this tool is visible at ``public`` trust.
    """
    if not isinstance(address, str) or not address.strip():
        return {"status": "invalid_input", "input_address": address, "resolved": False,
                "message": "No address was provided."}
    if not isinstance(borough, str) or not borough.strip():
        return {"status": "invalid_borough", "input_address": address, "resolved": False,
                "message": "A borough name is required (Manhattan, Bronx, Brooklyn, "
                           "Queens, or Staten Island)."}
    try:
        resolved_borough = Borough.from_name(borough)
    except ValueError:
        return {"status": "invalid_borough", "input_address": address, "resolved": False,
                "message": f"{borough!r} is not a NYC borough. Expected Manhattan, "
                           "Bronx, Brooklyn, Queens, or Staten Island."}

    address = address.strip()
    result = _geocode(address, resolved_borough)
    base = _base(address, borough.strip(), result)

    if result.outcome is GeocodeOutcome.RESOLVED:
        return _confirm_against_graph(base, result)

    if result.outcome is GeocodeOutcome.NO_TAX_LOT:
        return {**base, "status": "no_tax_lot", "resolved": False,
                "message": "That street and house number parsed, but Geosupport "
                           "has no tax lot (BBL) for them."}

    if result.outcome is GeocodeOutcome.STREET_AMBIGUOUS:
        return {**base, "status": "street_ambiguous", "resolved": False,
                "candidates": list(result.candidates),
                "candidate_total": result.candidate_total,
                "candidates_truncated": result.candidates_truncated,
                "message": "The street name was not recognized; these are the "
                           "closest matches from NYC's street dictionary. Ask the "
                           "user which they meant."}

    if result.outcome is GeocodeOutcome.STREET_NOT_RECOGNIZED:
        return {**base, "status": "street_not_recognized", "resolved": False,
                "message": "The street name was not recognized and Geosupport "
                           "offered no close matches."}

    if result.outcome is GeocodeOutcome.INVALID_INPUT:
        return {**base, "status": "invalid_input", "resolved": False,
                "message": "The address could not be parsed — it may be missing a "
                           "house number, or be a street reference rather than a "
                           "single address."}

    if result.outcome is GeocodeOutcome.UNAVAILABLE:
        return {**base, "status": "geocoder_unavailable", "resolved": False,
                "message": "The address geocoder is unavailable, so this address "
                           "could not be resolved. This is not the same as 'no "
                           "such address' — try again once the geocoder is back."}

    # FAILED, or any code geocode.py could not classify. Fail closed.
    return {**base, "status": "failed", "resolved": False,
            "message": "The address could not be resolved."}


def _confirm_against_graph(base: dict[str, Any], result: GeocodeResult) -> dict[str, Any]:
    """Confirm a resolved BBL exists in the graph (D12), or report absence."""
    row = read(_CONFIRM_CYPHER, {"bbl": result.bbl}).single
    if row is None:
        return {**base, "status": "geocoded_but_absent", "resolved": False,
                "bbl": result.bbl,
                "message": f"Geosupport resolved this to BBL {result.bbl}, but the "
                           "discovery graph has no building for that lot."}
    return {**base, "status": "resolved", "resolved": True,
            "bbl": row["bbl"],
            # Display fields, from the graph's own record — never a lookup key.
            "address": row["address"],
            "graph_borough": row["borough"],
            "message": "Resolved to a building in the discovery graph."}
