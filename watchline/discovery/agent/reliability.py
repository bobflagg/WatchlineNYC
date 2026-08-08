"""Static Type I-IV reliability tagging, and structural caveat attachment.

Implements the taxonomy from ``discovery-schema-reference``, orthogonal to
query tier:

* **Type I** — built entirely from directly-sourced fields.
* **Type II** — touches ``Landlord``, ``Portfolio``, ``APPARENT_CONTROL``,
  ``CONNECTED_BY_NAME``, or ``CONNECTED_BY_ADDRESS`` anywhere in the query.
* **Type III** — Tier 4's own self-generated Cypher, not a pre-vetted template.
* **Type IV** — Type III plus web/registry search.

Two design rules from ``CLAUDE.md``, both enforced here rather than trusted:

1. **Tags are static.** A tool declares what it touches at definition time and
   the tag is computed then — never inferred from result contents at runtime.
   Runtime inference would mean a query returning no Type II rows looked Type I,
   so the caveat would vanish exactly when a user might over-read an empty
   result.
2. **A Type II tool cannot ship without caveat text.** The decorator raises at
   *import* time if the declared elements yield no caveat, so the failure is a
   startup crash during development rather than a missing disclaimer in
   production. This is what makes "every Type II touch ships its caveat"
   structural instead of aspirational.

**The Geosupport carve-out (decision D10).** Geosupport is a local,
deterministic, offline canonicalizer published by the same agency PLUTO derives
from, so a Geosupport-resolved address is Type I. That is deliberately *not* a
general licence for external calls: web and registry search remain Type IV and
Tier-4-only. The two are kept as distinct members of :class:`ExternalSource` so
the carve-out cannot be quietly widened.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .caveats import Caveat, DerivedElement, caveats_for

__all__ = [
    "ReliabilityType",
    "ExternalSource",
    "Reliability",
    "ReliabilityDeclarationError",
    "TYPE_II_ELEMENTS",
    "TYPE_I_ELEMENTS",
    "RELIABILITY_KEY",
    "reliability_of",
    "tagged",
]

#: Key added to a tool's output payload. Reserved — a tool returning this key
#: itself is a bug, since it would overwrite the tag.
RELIABILITY_KEY = "reliability"


class ReliabilityType(StrEnum):
    """Data-reliability tier. Ordered least to most caveated."""

    TYPE_I = "I"
    TYPE_II = "II"
    TYPE_III = "III"
    TYPE_IV = "IV"


class ExternalSource(StrEnum):
    """Sources outside the discovery graph, which are not interchangeable."""

    #: NYC DCP Geosupport, run locally. Deterministic, offline, city-official.
    #: Type I per D10 — see the module docstring.
    GEOSUPPORT = "geosupport"
    #: Open-web search. Type IV, Tier 4 only.
    WEB_SEARCH = "web_search"
    #: Corporate/registry lookups. Type IV, Tier 4 only. Kept separate from
    #: WEB_SEARCH because a registry-sourced identity link is a different,
    #: lower-confidence claim than the graph's structural CONNECTED_BY_* edges
    #: and must be labelled distinctly, never merged into "apparent control".
    REGISTRY_SEARCH = "registry_search"


#: External sources that do not raise the tag above Type I.
_TYPE_I_EXTERNAL: frozenset[ExternalSource] = frozenset({ExternalSource.GEOSUPPORT})

#: External sources restricted to Tier 4 and tagged Type IV.
_TIER_4_ONLY_EXTERNAL: frozenset[ExternalSource] = frozenset(
    {ExternalSource.WEB_SEARCH, ExternalSource.REGISTRY_SEARCH}
)

#: Graph elements whose presence anywhere in a query makes it Type II.
TYPE_II_ELEMENTS: frozenset[str] = frozenset(
    {
        "Landlord",
        "Portfolio",
        "APPARENT_CONTROL",
        "CONNECTED_BY_NAME",
        "CONNECTED_BY_ADDRESS",
        "MEMBER_OF",
        "IN_PORTFOLIO",
    }
)

#: Directly-sourced elements. Listed explicitly so a typo'd or unknown element
#: name is rejected rather than silently treated as Type I.
TYPE_I_ELEMENTS: frozenset[str] = frozenset(
    {
        "Building",
        "Actor",
        "Event",
        "HAS_EVENT",
        "REGISTERED_FOR",
        "PARTY_TO",
        "REFERENCES",
        "Building.dof_ownername",
    }
)

_KNOWN_ELEMENTS: frozenset[str] = TYPE_I_ELEMENTS | TYPE_II_ELEMENTS

# Graph elements that carry caveat text, mapped to the canonical caveat. Not
# every Type II element has one: MEMBER_OF and IN_PORTFOLIO are edges into a
# Portfolio, so the Portfolio caveat covers them.
_ELEMENT_CAVEATS: dict[str, DerivedElement] = {
    # Inferred *identity* — whether these records describe one party at all.
    # Distinct from APPARENT_CONTROL, which is inferred control of a building.
    "Landlord": DerivedElement.LANDLORD,
    "Portfolio": DerivedElement.PORTFOLIO,
    "MEMBER_OF": DerivedElement.PORTFOLIO,
    "IN_PORTFOLIO": DerivedElement.PORTFOLIO,
    "APPARENT_CONTROL": DerivedElement.APPARENT_CONTROL,
    "CONNECTED_BY_ADDRESS": DerivedElement.CONNECTED_BY_ADDRESS,
    "CONNECTED_BY_NAME": DerivedElement.CONNECTED_BY_NAME,
    "Building.dof_ownername": DerivedElement.DOF_OWNERNAME,
}


class ReliabilityDeclarationError(Exception):
    """Raised at import time when a tool's declaration is invalid.

    Deliberately raised during decoration rather than at call time: a missing
    caveat should break the build, not a user's answer.
    """


# Every Type II element must be able to produce a reliability caveat, or a tool
# touching it alone could not satisfy the Type-II-implies-caveat rule. Checked at
# import, so an element added to TYPE_II_ELEMENTS without accompanying caveat
# text fails immediately rather than whenever some tool first declares it.
_UNCOVERED_TYPE_II = TYPE_II_ELEMENTS - set(_ELEMENT_CAVEATS)
if _UNCOVERED_TYPE_II:  # pragma: no cover - guards a future edit
    raise ReliabilityDeclarationError(
        f"Type II elements with no canonical caveat: {sorted(_UNCOVERED_TYPE_II)}. "
        "Add wording to discovery-schema-reference and caveats.py, then map it in "
        "_ELEMENT_CAVEATS."
    )


@dataclass(frozen=True)
class Reliability:
    """A tool's static reliability declaration."""

    type: ReliabilityType
    elements: tuple[str, ...]
    caveats: tuple[Caveat, ...]
    external_sources: tuple[ExternalSource, ...] = ()

    @property
    def requires_tier_4(self) -> bool:
        """Whether this tool may only be exposed to a Tier-4 context.

        Advisory metadata for the tool-filtering layer. Capability gating is
        enforced there, on ``trust_level`` — never here, and never by prompt.
        """
        return self.type in {ReliabilityType.TYPE_III, ReliabilityType.TYPE_IV} or bool(
            set(self.external_sources) & _TIER_4_ONLY_EXTERNAL
        )

    def as_payload(self, *, long_form: bool = False) -> dict[str, Any]:
        """Serialize for inclusion in a tool result.

        :param long_form: Use long-form caveat text, for Tier-4 narrative
            output. Short form is the default, for inline Tier 1-3 results.
        """
        return {
            "type": self.type.value,
            "elements": list(self.elements),
            "external_sources": [source.value for source in self.external_sources],
            "requires_tier_4": self.requires_tier_4,
            "caveats": [
                {
                    "element": caveat.element.value,
                    "kind": caveat.kind.value,
                    "text": caveat.long if long_form else caveat.short,
                }
                for caveat in self.caveats
            ],
        }


def reliability_of(
    touches: Iterable[str] = (),
    *,
    external_sources: Iterable[ExternalSource] = (),
    self_generated_cypher: bool = False,
) -> Reliability:
    """Compute a static reliability declaration.

    :param touches: Graph labels, relationship types, or qualified properties
        the query reads. Unknown names are rejected — a typo must not silently
        downgrade a tool to Type I.
    :param external_sources: Non-graph sources consulted.
    :param self_generated_cypher: True for Tier 4's own generated Cypher.
    :raises ReliabilityDeclarationError: on an unknown element name.
    """
    elements = tuple(sorted(set(touches)))
    unknown = sorted(set(elements) - _KNOWN_ELEMENTS)
    if unknown:
        raise ReliabilityDeclarationError(
            f"Unknown graph element(s) {unknown}. Declare only labels, "
            "relationship types, or qualified properties from "
            "graph_type.cypher; an unrecognized name would otherwise be "
            f"treated as Type I. Known: {sorted(_KNOWN_ELEMENTS)}"
        )

    sources = tuple(sorted(set(external_sources), key=lambda item: item.value))

    if set(sources) & _TIER_4_ONLY_EXTERNAL:
        tag = ReliabilityType.TYPE_IV
    elif self_generated_cypher:
        tag = ReliabilityType.TYPE_III
    elif set(elements) & TYPE_II_ELEMENTS:
        tag = ReliabilityType.TYPE_II
    else:
        tag = ReliabilityType.TYPE_I

    caveat_elements = {
        _ELEMENT_CAVEATS[element] for element in elements if element in _ELEMENT_CAVEATS
    }
    return Reliability(
        type=tag,
        elements=elements,
        caveats=caveats_for(caveat_elements),
        external_sources=sources,
    )


def tagged(
    touches: Iterable[str] = (),
    *,
    external_sources: Iterable[ExternalSource] = (),
    self_generated_cypher: bool = False,
    long_form: bool = False,
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Declare a tool's reliability and attach its caveats to every result.

    The declaration is validated when the module is imported, so a Type II tool
    with no caveat text fails at startup rather than shipping a result with no
    disclaimer.

    The wrapped function must return a mapping. The tag is added under
    :data:`RELIABILITY_KEY`, and the decorated function exposes ``.reliability``
    for static inspection by the tool-filtering layer.

    Example::

        @tagged(["Building", "APPARENT_CONTROL", "Building.dof_ownername"])
        def lookup_building_ownership(bbl: str) -> dict:
            ...

    :raises ReliabilityDeclarationError: at decoration time, for an unknown
        element or a Type II declaration with no caveat.
    """
    declaration = reliability_of(
        touches,
        external_sources=external_sources,
        self_generated_cypher=self_generated_cypher,
    )

    needs_caveat = declaration.type in {
        ReliabilityType.TYPE_II,
        ReliabilityType.TYPE_III,
        ReliabilityType.TYPE_IV,
    }
    has_reliability_warning = any(
        caveat.is_reliability_warning for caveat in declaration.caveats
    )
    if needs_caveat and not has_reliability_warning:
        raise ReliabilityDeclarationError(
            f"Type {declaration.type.value} tool declares {list(declaration.elements)} "
            "but yields no reliability caveat. Every derived element must ship "
            "its canonical caveat text (CLAUDE.md). If the element genuinely "
            "has no caveat in discovery-schema-reference, that gap must be "
            "resolved there rather than worked around here."
        )

    def decorate(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = func(*args, **kwargs)
            if not isinstance(result, dict):
                raise TypeError(
                    f"{func.__qualname__} must return a dict so its reliability "
                    f"tag can be attached; got {type(result).__name__}"
                )
            if RELIABILITY_KEY in result:
                raise ReliabilityDeclarationError(
                    f"{func.__qualname__} returned a {RELIABILITY_KEY!r} key, "
                    "which would overwrite its reliability tag"
                )
            return {**result, RELIABILITY_KEY: declaration.as_payload(long_form=long_form)}

        wrapper.reliability = declaration  # type: ignore[attr-defined]
        return wrapper

    return decorate
