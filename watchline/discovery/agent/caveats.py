"""Canonical caveat text for derived graph elements. The **only** copy.

``CLAUDE.md`` requires one canonical short/long pair per derived element,
reused everywhere that element appears, never written bespoke per query. This
module is that single copy, and
``tests/test_caveats.py::TestTextMatchesSkillExactly`` diffs every string
against ``.claude/skills/discovery-schema-reference/SKILL.md`` so the two
cannot drift apart silently.

Short form goes inline on Tier 1-3 results; long form goes in Tier-4 narrative
output.

**Why this is enforced rather than encouraged.** The caveats are the difference
between "this landlord controls 40 buildings" and "an algorithm inferred that
this landlord may control 40 buildings, and it has not been verified." The first
is a legal claim this system must never make. Duplicated wording drifts, and
drifted wording gets weaker, so the text lives here and
:mod:`watchline.discovery.agent.reliability` attaches it structurally rather
than relying on each tool author to remember.

The ``dof_ownername`` entry is deliberately different in kind: it is an
*interpretation* note, not a reliability warning. That record is fully reliable
— it is just frequently a shell LLC.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "CaveatKind",
    "Caveat",
    "DerivedElement",
    "CAVEATS",
    "caveat_for",
    "caveats_for",
    "short_forms",
    "long_forms",
]


class CaveatKind(StrEnum):
    """Whether a caveat warns about reliability or explains interpretation."""

    #: The element is inferred and may be wrong. Attaches to Type II elements.
    RELIABILITY = "reliability"
    #: The record is reliable, but reading it naively misleads. Attaches to
    #: directly-sourced fields that are commonly misread — currently only
    #: ``dof_ownername``, which is usually a shell entity.
    INTERPRETATION = "interpretation"


class DerivedElement(StrEnum):
    """Graph elements that carry mandatory caveat text.

    The first five are the Type II elements from
    ``discovery-schema-reference``. ``DOF_OWNERNAME`` is Type I and carries an
    interpretation note instead.

    Declaration order determines output order, so it runs from the most
    primitive derived element to the most composed: a ``Portfolio`` is a
    cluster *of* ``Landlord`` entities, so ``Landlord`` comes first.
    """

    LANDLORD = "Landlord"
    PORTFOLIO = "Portfolio"
    APPARENT_CONTROL = "APPARENT_CONTROL"
    CONNECTED_BY_ADDRESS = "CONNECTED_BY_ADDRESS"
    CONNECTED_BY_NAME = "CONNECTED_BY_NAME"
    DOF_OWNERNAME = "Building.dof_ownername"


@dataclass(frozen=True)
class Caveat:
    """One canonical caveat. Immutable, because it must not be edited in place."""

    element: DerivedElement
    short: str
    long: str
    kind: CaveatKind

    @property
    def is_reliability_warning(self) -> bool:
        return self.kind is CaveatKind.RELIABILITY


# Text below is verbatim from discovery-schema-reference/SKILL.md. Do not
# reword it here — change the skill and this module together, or the drift test
# fails. Line breaks are normalized to single spaces on load.
CAVEATS: dict[DerivedElement, Caveat] = {
    DerivedElement.LANDLORD: Caveat(
        element=DerivedElement.LANDLORD,
        short="Landlord identity is inferred from matching records, not verified.",
        long=(
            "This landlord is a curated entity assembled by matching public "
            "records that appear to describe the same party. It has not been "
            "independently verified. Records for the same party may be split "
            "across separate landlord entities, and records for different "
            "parties may be merged into one, so the name, business address, "
            "and list of associated buildings may each be incomplete or "
            "overstated."
        ),
        kind=CaveatKind.RELIABILITY,
    ),
    DerivedElement.PORTFOLIO: Caveat(
        element=DerivedElement.PORTFOLIO,
        short="Portfolio grouping is algorithmically inferred, not verified.",
        long=(
            "This portfolio was identified by a graph-clustering algorithm "
            "that groups landlord records sharing business addresses or names. "
            "It has not been independently verified. Buildings may be grouped "
            "together that are not actually under common control, and "
            "buildings under common control may be split across separate "
            "portfolios."
        ),
        kind=CaveatKind.RELIABILITY,
    ),
    DerivedElement.APPARENT_CONTROL: Caveat(
        element=DerivedElement.APPARENT_CONTROL,
        short="Apparent controller, not a confirmed legal owner.",
        long=(
            "This is the graph's inferred determination of who apparently "
            "controls this building, built by combining property registration "
            "and ownership records. It is not a legal determination of "
            "ownership and may not reflect the current, legally accountable "
            "party."
        ),
        kind=CaveatKind.RELIABILITY,
    ),
    DerivedElement.CONNECTED_BY_ADDRESS: Caveat(
        element=DerivedElement.CONNECTED_BY_ADDRESS,
        short="Connection inferred from a shared business address.",
        long=(
            "This connection is inferred because these records share a "
            "business address. This can both under- and over-connect: "
            "unrelated parties may share a mailing address, such as an "
            "accountant's or attorney's office, while inconsistent address "
            "formatting for the same location may fail to link records that "
            "should be connected. This has not been independently verified."
        ),
        kind=CaveatKind.RELIABILITY,
    ),
    DerivedElement.CONNECTED_BY_NAME: Caveat(
        element=DerivedElement.CONNECTED_BY_NAME,
        short="Connection inferred from a matching name.",
        long=(
            "This connection is inferred because these records share a "
            "matching name. This can both under- and over-connect: common "
            "names may link unrelated people, while inconsistent name "
            "formatting for the same person may fail to link records that "
            "should be connected. This has not been independently verified."
        ),
        kind=CaveatKind.RELIABILITY,
    ),
    DerivedElement.DOF_OWNERNAME: Caveat(
        element=DerivedElement.DOF_OWNERNAME,
        short="Recorded owner — may be a shell entity.",
        long=(
            "This is the deed-of-record owner exactly as filed with NYC "
            "Department of Finance. It is a reliable, directly-sourced record, "
            "but is frequently a shell LLC or holding entity and may not "
            "reflect who actually controls the building day to day. See "
            "'apparent controller' for the graph's inference of actual control."
        ),
        kind=CaveatKind.INTERPRETATION,
    ),
}


def caveat_for(element: DerivedElement | str) -> Caveat:
    """Return the canonical caveat for one element.

    :raises KeyError: for an element with no caveat, which is deliberate — a
        tool asking for caveat text for something undocumented should fail
        loudly rather than silently emit nothing.
    """
    key = element if isinstance(element, DerivedElement) else DerivedElement(element)
    return CAVEATS[key]


def caveats_for(elements: object) -> tuple[Caveat, ...]:
    """Return caveats for an iterable of elements, in a stable order.

    Ordered by :class:`DerivedElement` declaration rather than by the caller's
    iteration order, so identical output is produced regardless of how a tool
    happened to accumulate its element set.
    """
    wanted = {
        item if isinstance(item, DerivedElement) else DerivedElement(item)
        for item in elements  # type: ignore[attr-defined]
    }
    return tuple(CAVEATS[element] for element in DerivedElement if element in wanted)


def short_forms(elements: object) -> tuple[str, ...]:
    """Short-form caveat text, for inline Tier 1-3 results."""
    return tuple(caveat.short for caveat in caveats_for(elements))


def long_forms(elements: object) -> tuple[str, ...]:
    """Long-form caveat text, for Tier-4 narrative output."""
    return tuple(caveat.long for caveat in caveats_for(elements))
