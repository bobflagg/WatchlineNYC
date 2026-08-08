"""Address resolution via NYC DCP Geosupport. Implements D9 and D12.

Addresses resolve to a BBL through Geosupport, then to a `Building` by key
lookup on the existing uniqueness index — not by string-matching
`Building.address`, which is PLUTO-normalized, non-unique, sometimes lacking a
house number, and therefore a display field only.

Geosupport runs as a **sidecar** (decision D9), because ``python-geosupport``
requires the Linux/Windows Geosupport Desktop binaries while this project runs
natively on macOS. The sidecar is a thin pass-through: all interpretation lives
here, in version control and unit-tested, rather than in a container image.

**Release pinning matters.** :data:`REQUIRED_RELEASE` must match the release the
ingestion pipeline standardizes with, or agent-side and pipeline-side geocoding
disagree on exactly the edge cases that matter. :meth:`GeosupportClient.health`
checks it and fails loudly.

Everything below is calibrated against a real spike run — see
``specs/2026-07-30-phase-0-foundations/spike-findings.md``. Two findings shape
the design:

1. **``GRC '00'`` does not guarantee a BBL.** Geosupport can report success,
   echo a normalized street, and return an empty BBL structure (observed for
   ``456 West 24th Street``). Hence :attr:`GeocodeOutcome.NO_TAX_LOT` as a
   distinct outcome — a client that checked only the return code would pass
   ``None`` to a key lookup and report "building not found", which is a
   different and misleading answer.
2. **A resolved BBL is a candidate, not an answer.** ~2% of sampled addresses
   resolve to a different lot than the graph records for that address, because
   ``Building.address`` is one of several addresses on a lot rather than a unique
   identifier. Callers must confirm the BBL against the graph and show the
   graph's own address back, not present a geocoded BBL as agreed fact.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "REQUIRED_RELEASE",
    "MAX_CANDIDATES",
    "Borough",
    "GeocodeOutcome",
    "GeocodeResult",
    "GeosupportUnavailable",
    "GeosupportReleaseMismatch",
    "GeosupportClient",
    "compose_bbl",
    "interpret",
]

#: Geosupport Desktop Edition release. **Must** match the ingestion pipeline's
#: pin (its Dockerfile sets ``RELEASE=25b``). One constant, referenced by both
#: the client and the sidecar image, so the two cannot drift.
REQUIRED_RELEASE: str = os.environ.get("GEOSUPPORT_RELEASE", "25b")

#: Cap on disambiguation candidates surfaced to a caller. Geosupport returns up
#: to 10 similar street names; ``CLAUDE.md``'s ambiguity contract caps the list
#: at about 5. The true total is reported alongside, so a truncated list is
#: never mistaken for the whole set.
MAX_CANDIDATES: int = 5

#: BBL sentinel meaning "none". Geosupport writes this into
#: ``Condominium Billing BBL`` when there is no condo billing lot; treating it
#: as a real BBL would produce lookups for a building that cannot exist.
_NULL_BBL = "0000000000"

_DEFAULT_TIMEOUT = float(os.environ.get("GEOSUPPORT_TIMEOUT", "5.0"))
_DEFAULT_URL = os.environ.get("GEOSUPPORT_URL", "http://localhost:8080")


class Borough(StrEnum):
    """Borough codes, matching the leading digit of ``Building.bbl``.

    Verified against all 859,794 rows: 1 Manhattan, 2 Bronx, 3 Brooklyn,
    4 Queens, 5 Staten Island.
    """

    MANHATTAN = "1"
    BRONX = "2"
    BROOKLYN = "3"
    QUEENS = "4"
    STATEN_ISLAND = "5"

    @classmethod
    def from_name(cls, name: str) -> Borough:
        """Resolve a borough name as stored in ``Building.borough``."""
        try:
            return _BOROUGH_BY_NAME[name.strip().casefold()]
        except KeyError as exc:
            valid = ", ".join(sorted(_BOROUGH_BY_NAME))
            raise ValueError(f"Unknown borough {name!r}; expected one of: {valid}") from exc


_BOROUGH_BY_NAME: dict[str, Borough] = {
    "manhattan": Borough.MANHATTAN,
    "bronx": Borough.BRONX,
    "brooklyn": Borough.BROOKLYN,
    "queens": Borough.QUEENS,
    "staten island": Borough.STATEN_ISLAND,
}


class GeocodeOutcome(StrEnum):
    """Distinct outcomes, per D12. Not a boolean — each needs its own response.

    Collapsing these into "found / not found" would tell a user "no such
    address" when the real answer is "that street has ten near-matches, which
    did you mean?" or "that address exists but has no tax lot".
    """

    #: Geosupport returned a usable BBL.
    RESOLVED = "resolved"
    #: ``GRC '00'`` but the BBL structure was empty. The street and house number
    #: parsed; there is simply no tax lot for them.
    NO_TAX_LOT = "no_tax_lot"
    #: Street not recognized, and Geosupport offered similar names. This is the
    #: disambiguation path — an authoritative candidate list.
    STREET_AMBIGUOUS = "street_ambiguous"
    #: Street not recognized, with no similar names to offer.
    STREET_NOT_RECOGNIZED = "street_not_recognized"
    #: Input could not be parsed — no house number, too many digits, etc.
    INVALID_INPUT = "invalid_input"
    #: The sidecar could not be reached. Distinct from every result above: an
    #: outage must never be reported as "address not found".
    UNAVAILABLE = "unavailable"
    #: Recognized response shape, unrecognized return code. Fails closed.
    FAILED = "failed"


class GeosupportUnavailable(RuntimeError):
    """The sidecar is unreachable, timed out, or returned an unusable response."""


class GeosupportReleaseMismatch(RuntimeError):
    """The sidecar's Geosupport release differs from :data:`REQUIRED_RELEASE`.

    Raised loudly rather than warned about: a silent mismatch means agent-side
    and pipeline-side geocoding can disagree, and that disagreement surfaces as
    inexplicably missing buildings rather than as an error.
    """


@dataclass(frozen=True)
class GeocodeResult:
    """Outcome of one address resolution."""

    outcome: GeocodeOutcome
    #: 10-character BBL, present only when ``outcome`` is ``RESOLVED``.
    bbl: str | None = None
    #: Geosupport's canonical street name. Carries internal padding
    #: (``'WEST   24 STREET'``), so collapse whitespace before displaying it and
    #: never compare it to ``Building.address`` directly.
    normalized_street: str | None = None
    house_number: str | None = None
    borough: Borough | None = None
    #: Capped candidate list for ``STREET_AMBIGUOUS``, from the city's own
    #: street dictionary.
    candidates: tuple[str, ...] = ()
    #: How many candidates Geosupport actually offered, before capping.
    candidate_total: int = 0
    grc: str | None = None
    reason_code: str | None = None
    message: str | None = None

    @property
    def resolved(self) -> bool:
        return self.outcome is GeocodeOutcome.RESOLVED and self.bbl is not None

    @property
    def needs_disambiguation(self) -> bool:
        return self.outcome is GeocodeOutcome.STREET_AMBIGUOUS and bool(self.candidates)

    @property
    def candidates_truncated(self) -> bool:
        return self.candidate_total > len(self.candidates)


def compose_bbl(components: Any) -> str | None:
    """Build the graph's 10-character BBL from Geosupport's components.

    Geosupport returns BBL as a nested structure of ``Borough Code``,
    ``Tax Block``, and ``Tax Lot``. The graph stores a single 10-character
    string: borough digit, block zero-padded to 5, lot zero-padded to 4.
    Verified to be 10 characters on all 859,794 ``Building`` rows.

    Returns ``None`` for an absent, incomplete, or sentinel BBL — including the
    flat ``'0000000000'`` Geosupport writes when there is no condo billing lot.
    """
    if isinstance(components, str):
        flat = components.strip()
        return None if not flat or flat == _NULL_BBL else flat or None

    if not isinstance(components, dict):
        return None

    boro = str(components.get("Borough Code", "") or "").strip()
    block = str(components.get("Tax Block", "") or "").strip()
    lot = str(components.get("Tax Lot", "") or "").strip()

    if boro and block and lot:
        bbl = f"{boro}{block.zfill(5)}{lot.zfill(4)}"
        return None if bbl == _NULL_BBL else bbl

    # Some responses nest a pre-composed flat value under the same key.
    flat = str(components.get("BOROUGH BLOCK LOT (BBL)", "") or "").strip()
    if flat and flat != _NULL_BBL:
        return flat
    return None


def _first(response: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def interpret(
    response: dict[str, Any],
    *,
    house_number: str | None = None,
    borough: Borough | None = None,
) -> GeocodeResult:
    """Turn a raw Geosupport response into a structured outcome.

    Pure and hermetically testable — no HTTP. The GRC mapping is calibrated
    against observed behaviour (see the spike findings), not guessed:

    * ``'00'`` — success. **Still check for a BBL**: an empty BBL with a
      success code is a real, observed case.
    * ``'EE'`` — street dictionary could not match. ``List of Street Names``
      distinguishes ambiguous from simply unknown.
    * ``'13'`` — input could not be parsed (no house number, too many digits).

    An unrecognized code fails closed to :attr:`GeocodeOutcome.FAILED`.
    """
    grc = _first(response, "Geosupport Return Code (GRC)", "Geosupport Return Code")
    reason = _first(response, "Reason Code")
    message = _first(response, "Message")
    normalized_street = _first(
        response, "First Street Name Normalized", "BOE Preferred Street Name"
    )
    house = house_number or _first(response, "House Number - Display Format")

    raw_candidates = response.get("List of Street Names") or []
    candidates = tuple(
        str(name).strip() for name in raw_candidates if str(name).strip()
    )

    common = {
        "normalized_street": normalized_street,
        "house_number": house,
        "borough": borough,
        "grc": grc,
        "reason_code": reason,
        "message": message,
    }

    if grc == "00":
        bbl = compose_bbl(response.get("BOROUGH BLOCK LOT (BBL)"))
        if bbl:
            return GeocodeResult(outcome=GeocodeOutcome.RESOLVED, bbl=bbl, **common)
        # Success, but no tax lot exists for this address.
        return GeocodeResult(outcome=GeocodeOutcome.NO_TAX_LOT, **common)

    if grc == "EE":
        if candidates:
            return GeocodeResult(
                outcome=GeocodeOutcome.STREET_AMBIGUOUS,
                candidates=candidates[:MAX_CANDIDATES],
                candidate_total=len(candidates),
                **common,
            )
        return GeocodeResult(outcome=GeocodeOutcome.STREET_NOT_RECOGNIZED, **common)

    if grc == "13":
        return GeocodeResult(outcome=GeocodeOutcome.INVALID_INPUT, **common)

    logger.warning("Unrecognized Geosupport return code %r (message: %s)", grc, message)
    return GeocodeResult(outcome=GeocodeOutcome.FAILED, **common)


@dataclass
class GeosupportClient:
    """Client for the Geosupport sidecar.

    :param base_url: Sidecar root, from ``GEOSUPPORT_URL``.
    :param timeout: Per-request timeout in seconds.
    :param required_release: Release the sidecar must report.
    :param client: Optional ``httpx.Client``, for tests and connection reuse.

    **No retries.** A retry loop would turn a persistent outage into slow,
    repeated failure and mask it from the health check. Geocoding is
    deterministic, so a failed call is not going to succeed on a second attempt
    for any reason a retry would fix.
    """

    base_url: str = field(default_factory=lambda: _DEFAULT_URL)
    timeout: float = field(default_factory=lambda: _DEFAULT_TIMEOUT)
    required_release: str = field(default_factory=lambda: REQUIRED_RELEASE)
    client: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._owns_client = self.client is None
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> GeosupportClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        """Verify the sidecar is reachable and pinned to the right release.

        Call at startup. Failing loudly here is the point: an unreachable
        geocoder otherwise degrades into "address not found" for every query,
        which looks like a data gap rather than an outage.

        :raises GeosupportUnavailable: unreachable, timed out, or malformed.
        :raises GeosupportReleaseMismatch: reachable but wrong release.
        """
        payload = self._get("/health")
        release = str(payload.get("release", "")).strip()
        if not release:
            raise GeosupportUnavailable(
                f"Sidecar at {self.base_url} did not report a Geosupport release; "
                "cannot confirm it matches the ingestion pipeline"
            )
        if release != self.required_release:
            raise GeosupportReleaseMismatch(
                f"Sidecar reports Geosupport release {release!r} but this agent "
                f"requires {self.required_release!r}, the release the ingestion "
                "pipeline standardizes with. Differing releases disagree on edge "
                "cases, which surfaces as inexplicably missing buildings."
            )
        return payload

    def resolve(
        self,
        house_number: str,
        street_name: str,
        borough: Borough | str,
    ) -> GeocodeResult:
        """Resolve one address to a BBL.

        The caller supplies house number and street separately. Note that
        splitting a full address on the first space is **wrong in Queens**,
        where street names are routinely numeric (``'39 AVENUE'`` is a street,
        not house 39 of street "AVENUE") — see the spike findings.

        Returns :attr:`GeocodeOutcome.UNAVAILABLE` rather than raising on an
        outage, so a caller can distinguish it from "not found" and degrade
        deliberately.
        """
        resolved_borough = (
            borough if isinstance(borough, Borough) else Borough(str(borough))
        )
        try:
            response = self._post(
                "/resolve",
                {
                    "house_number": str(house_number).strip(),
                    "street_name": str(street_name).strip(),
                    "borough": resolved_borough.value,
                },
            )
        except GeosupportUnavailable as exc:
            logger.error("Geosupport sidecar unavailable: %s", exc)
            return GeocodeResult(
                outcome=GeocodeOutcome.UNAVAILABLE,
                house_number=str(house_number).strip(),
                borough=resolved_borough,
                message=str(exc),
            )
        return interpret(
            response,
            house_number=str(house_number).strip(),
            borough=resolved_borough,
        )

    # -- transport ---------------------------------------------------------

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        assert self.client is not None  # set in __post_init__
        url = f"{self.base_url}{path}"
        try:
            response = self.client.request(method, url, json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise GeosupportUnavailable(f"{method} {url} failed: {exc}") from exc
        except ValueError as exc:
            raise GeosupportUnavailable(f"{method} {url} returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise GeosupportUnavailable(
                f"{method} {url} returned {type(payload).__name__}, expected an object"
            )
        return payload
