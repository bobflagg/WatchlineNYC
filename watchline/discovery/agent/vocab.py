"""Canonical vocabulary for ``Event`` fields. Implements decision D6.

Every event query in this system goes through here. That is not tidiness — the
raw vocabularies collide in ways that produce **wrong numbers rather than
errors**, which is the worst failure mode available:

1. ``event_type`` is not unique to a source. ``'Violation'`` is emitted by both
   HPD and DOB, and ``'Mortgage'``-family types all come from ACRIS.
2. ``violation_class`` is a *repurposed* field meaning something different per
   source — HPD hazard class, DOB code, ECB class *or* hazard label, HPD
   complaint urgency, vacate-order cause, litigation case type, Marshal
   property type, ACRIS document type. Only HPD ``Violation`` uses A/B/C/I.
3. Those code spaces **overlap**. Filtering ``violation_class = 'C'`` without a
   source returns 2,547,016 HPD rows *and* 179,658 DOB rows, which mean
   completely different things.
4. ``status`` casing is consistent per event type but differs *between* types:
   HPD ``Complaint`` uses ``'OPEN'``/``'CLOSE'`` while HPD ``Violation`` uses
   ``'Open'``/``'Close'``. So ``status = 'Open'`` silently returns none of the
   32,055 open complaints.
5. ``HPD-Litigations.status`` is not a controlled vocabulary at all — it embeds
   a date (``'GRANTED - 02/08/2022'``, ``'Exempt- 08/29/2022'``,
   ``'DENIED , 10/31/2016'``), giving 1,580 distinct values with inconsistent
   separators and casing. It reduces to 10 outcomes once the date is stripped.

Consequently: **no tool may filter on ``status`` or ``violation_class`` without
also constraining ``source_name``.** :func:`require_pair` makes that a
signature-level requirement rather than a matter of discipline.

All vocabularies below were derived from the live graph on **2026-07-31** by
full scan of all 42,296,617 ``Event`` nodes. Counts in comments are from that
run and will drift; the *values* are what matter.
``tests/integration/test_vocab_drift.py`` re-derives them and fails on change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Source",
    "EventType",
    "Status",
    "ClassScheme",
    "VocabularyError",
    "VALID_PAIRS",
    "OPEN_STATUSES",
    "HPD_IMMEDIATELY_HAZARDOUS",
    "HPD_HAZARD_CLASSES",
    "HPD_INFORMATIONAL_CLASSES",
    "HPD_VIOLATION_CLASSES",
    "hpd_hazard_filter",
    "RawFilter",
    "require_pair",
    "canonical_status",
    "is_open",
    "status_filter",
    "canonical_class",
    "class_filter",
    "class_schemes_for",
    "expected_raw_statuses",
    "expected_raw_classes",
]


class VocabularyError(ValueError):
    """Raised on an invalid source/type pair or a misuse of the vocabulary."""


class Source(StrEnum):
    """``Event.source_name`` values. Exhaustive as of 2026-07-31."""

    ACRIS = "ACRIS"
    DOB = "DOB"
    ECB = "ECB"
    HPD = "HPD"
    HPD_LITIGATIONS = "HPD-Litigations"
    MARSHAL = "Marshal"


class EventType(StrEnum):
    """``Event.event_type`` values. Exhaustive as of 2026-07-31."""

    COMPLAINT = "Complaint"
    COURT_FILING = "CourtFiling"
    DEED_TRANSFER = "DeedTransfer"
    EVICTION = "Eviction"
    JUDGMENT = "Judgment"
    MORTGAGE = "Mortgage"
    MORTGAGE_ASSIGNMENT = "MortgageAssignment"
    MORTGAGE_SATISFACTION = "MortgageSatisfaction"
    VACATE_ORDER = "VacateOrder"
    VIOLATION = "Violation"


#: The only ``(source_name, event_type)`` combinations that exist. Eleven pairs
#: — note ACRIS accounts for four of them, and that both HPD and DOB emit
#: ``Violation``. Event counts as of 2026-07-31 in comments.
VALID_PAIRS: frozenset[tuple[Source, EventType]] = frozenset(
    {
        (Source.ACRIS, EventType.DEED_TRANSFER),  # 3,018,093
        (Source.ACRIS, EventType.MORTGAGE),  # 3,551,213
        (Source.ACRIS, EventType.MORTGAGE_ASSIGNMENT),  # 1,926,946
        (Source.ACRIS, EventType.MORTGAGE_SATISFACTION),  # 2,258,402
        (Source.DOB, EventType.VIOLATION),  # 2,267,700
        (Source.ECB, EventType.JUDGMENT),  # 1,699,561
        (Source.HPD, EventType.COMPLAINT),  # 16,143,104
        (Source.HPD, EventType.VACATE_ORDER),  # 8,732
        (Source.HPD, EventType.VIOLATION),  # 11,082,793
        (Source.HPD_LITIGATIONS, EventType.COURT_FILING),  # 239,367
        (Source.MARSHAL, EventType.EVICTION),  # 100,706
    }
)


class Status(StrEnum):
    """Canonical status outcomes.

    Deliberately *not* collapsed to open/closed. A dismissed violation is not a
    resolved one, and an ECB judgment merely sitting unpaid is not one that was
    actually satisfied — for accountability work those differences are often the
    story. Use :data:`OPEN_STATUSES` / :func:`is_open` for the common
    "outstanding right now" filter.
    """

    OPEN = "OPEN"
    PENDING = "PENDING"
    CLOSED = "CLOSED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    DENIED = "DENIED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"
    GRANTED = "GRANTED"
    EXEMPT = "EXEMPT"
    WITHDRAWN = "WITHDRAWN"
    SETTLED = "SETTLED"
    POSSESSION = "POSSESSION"
    EVICTED = "EVICTED"
    #: The property is null in the graph. Distinct from UNKNOWN: "never
    #: recorded" and "recorded but unrecognizable" are different facts, and
    #: conflating them hides which one you are looking at.
    NOT_RECORDED = "NOT_RECORDED"
    #: Present but not in any documented vocabulary. Never silently dropped.
    UNKNOWN = "UNKNOWN"


#: Statuses meaning "outstanding right now". Everything else is some flavour of
#: concluded. This is the set behind "open violations" in the example queries.
OPEN_STATUSES: frozenset[Status] = frozenset({Status.OPEN, Status.PENDING})


# Raw -> canonical, keyed by (source, event_type) because the same raw string
# can mean different things across types, and casing differs between them.
#
# Keys are stored lowercase; lookup normalizes. For HPD-Litigations the key is
# the leading token with trailing punctuation removed, since the raw value
# carries a trailing date.
_STATUS_MAP: dict[tuple[Source, EventType], dict[str, Status]] = {
    (Source.HPD, EventType.COMPLAINT): {
        "open": Status.OPEN,  # 32,055 — note UPPERCASE in the graph
        "close": Status.CLOSED,  # 16,111,049
    },
    (Source.HPD, EventType.VIOLATION): {
        "open": Status.OPEN,  # 2,879,872 — Titlecase in the graph
        "close": Status.CLOSED,  # 8,202,921
    },
    (Source.HPD, EventType.VACATE_ORDER): {
        "active": Status.OPEN,  # 4,492
        "rescinded": Status.RESCINDED,  # 4,240
    },
    (Source.DOB, EventType.VIOLATION): {
        "active": Status.OPEN,  # 545,439
        "resolved": Status.RESOLVED,  # 632,363
        "dismissed": Status.DISMISSED,  # 1,088,885
    },
    (Source.ECB, EventType.JUDGMENT): {
        "active": Status.OPEN,  # 267,167
        # Note the raw value is RESOLVE, not RESOLVED.
        "resolve": Status.RESOLVED,  # 1,432,391
        "unknown": Status.UNKNOWN,  # 3 — the graph literally stores "Unknown"
    },
    (Source.HPD_LITIGATIONS, EventType.COURT_FILING): {
        "closed": Status.CLOSED,  # 229,555
        "pending": Status.PENDING,  # 7,103
        "granted": Status.GRANTED,  # 2,203
        "exempt": Status.EXEMPT,  # 243
        "denied": Status.DENIED,  # 103
        # An application on file is outstanding, so it counts as pending.
        "application": Status.PENDING,  # 72
        "withdrawn/abandoned": Status.WITHDRAWN,  # 49
        "rejected": Status.REJECTED,  # 35
        "rescinded": Status.RESCINDED,  # 3
        "settlement": Status.SETTLED,  # 1
    },
    (Source.MARSHAL, EventType.EVICTION): {
        "possession": Status.POSSESSION,  # 97,535
        # 'P' is a documented abbreviation of POSSESSION in the Marshal feed.
        "p": Status.POSSESSION,  # 1,220
        "eviction": Status.EVICTED,  # 1,852
        # 'EAST' (99 rows) is not a status — almost certainly a misaligned
        # column in the source extract. Deliberately absent, so it resolves to
        # UNKNOWN rather than being guessed at.
    },
    # ACRIS events carry no status at all (all four types, 10,754,654 rows).
    (Source.ACRIS, EventType.DEED_TRANSFER): {},
    (Source.ACRIS, EventType.MORTGAGE): {},
    (Source.ACRIS, EventType.MORTGAGE_ASSIGNMENT): {},
    (Source.ACRIS, EventType.MORTGAGE_SATISFACTION): {},
}


class ClassScheme(StrEnum):
    """What ``violation_class`` actually encodes, per source and type.

    The field name is misleading everywhere except HPD ``Violation``.
    """

    HPD_HAZARD = "hpd_hazard"
    DOB_CODE = "dob_code"
    ECB_CLASS_NUMBER = "ecb_class_number"
    ECB_HAZARD = "ecb_hazard"
    HPD_COMPLAINT_URGENCY = "hpd_complaint_urgency"
    HPD_VACATE_CAUSE = "hpd_vacate_cause"
    LITIGATION_CASE_TYPE = "litigation_case_type"
    MARSHAL_PROPERTY_TYPE = "marshal_property_type"
    ACRIS_DOCUMENT_TYPE = "acris_document_type"


# ECB Judgment is the only pair with two schemes in one field, so the value is
# a tuple everywhere for uniformity.
_CLASS_SCHEMES: dict[tuple[Source, EventType], tuple[ClassScheme, ...]] = {
    (Source.HPD, EventType.VIOLATION): (ClassScheme.HPD_HAZARD,),
    (Source.DOB, EventType.VIOLATION): (ClassScheme.DOB_CODE,),
    (Source.ECB, EventType.JUDGMENT): (
        ClassScheme.ECB_CLASS_NUMBER,
        ClassScheme.ECB_HAZARD,
    ),
    (Source.HPD, EventType.COMPLAINT): (ClassScheme.HPD_COMPLAINT_URGENCY,),
    (Source.HPD, EventType.VACATE_ORDER): (ClassScheme.HPD_VACATE_CAUSE,),
    (Source.HPD_LITIGATIONS, EventType.COURT_FILING): (ClassScheme.LITIGATION_CASE_TYPE,),
    (Source.MARSHAL, EventType.EVICTION): (ClassScheme.MARSHAL_PROPERTY_TYPE,),
    (Source.ACRIS, EventType.DEED_TRANSFER): (ClassScheme.ACRIS_DOCUMENT_TYPE,),
    (Source.ACRIS, EventType.MORTGAGE): (ClassScheme.ACRIS_DOCUMENT_TYPE,),
    (Source.ACRIS, EventType.MORTGAGE_ASSIGNMENT): (ClassScheme.ACRIS_DOCUMENT_TYPE,),
    (Source.ACRIS, EventType.MORTGAGE_SATISFACTION): (ClassScheme.ACRIS_DOCUMENT_TYPE,),
}


@dataclass(frozen=True)
class HpdViolationClass:
    """One HPD violation class, with the severity claim stated explicitly."""

    code: str
    label: str
    #: 1 = least severe, on HPD's hazard scale. ``None`` for classes that are
    #: not on that scale at all, so nothing can order by it by accident.
    severity: int | None
    #: Whether this class represents a physical condition found on inspection.
    #: ``False`` for administrative notices, which must be excluded from
    #: hazard-severity aggregates.
    is_hazard: bool
    description: str


#: HPD violation classes, per HPD's published definitions.
#:
#: **Correction on record:** the ``discovery-example-queries`` skill described
#: Class A as "immediately hazardous". It is not — Class A is *non*-hazardous
#: and Class C is immediately hazardous. Answering a life-safety question with
#: Class A rows would report non-hazardous conditions as immediate hazards,
#: which for a tenant-safety tool is the most consequential kind of wrong.
HPD_VIOLATION_CLASSES: dict[str, HpdViolationClass] = {
    "A": HpdViolationClass(
        "A",
        "non-hazardous",
        severity=1,
        is_hazard=True,
        description="Non-hazardous condition found on inspection.",
    ),  # 2,537,166
    "B": HpdViolationClass(
        "B",
        "hazardous",
        severity=2,
        is_hazard=True,
        description="Hazardous condition found on inspection.",
    ),  # 5,194,171
    "C": HpdViolationClass(
        "C",
        "immediately hazardous",
        severity=3,
        is_hazard=True,
        description="Immediately hazardous condition found on inspection. The "
        "most serious class, and the one meant by 'life-safety violation'.",
    ),  # 2,547,016
    "I": HpdViolationClass(
        "I",
        "informational / administrative",
        # Not on the hazard scale at all — deliberately unranked rather than
        # ranked zero, so it cannot be compared against A/B/C.
        severity=None,
        is_hazard=False,
        description="Informational or administrative order posted against the "
        "property rather than a defect found on inspection — e.g. an open "
        "Order to Repair/Vacate, a vacant-property notice, or an invalid or "
        "failed property registration. Because no hazard was found, these do "
        "not carry the correction-period and certification requirements that "
        "A/B/C violations do. Exclude from hazard-severity counts; useful on "
        "its own as a red flag for invalid registrations and unresolved "
        "orders.",
    ),  # 804,440
}

#: The code to use for "immediately hazardous", for callers that would otherwise
#: hardcode a letter.
HPD_IMMEDIATELY_HAZARDOUS: str = "C"

#: The hazard scale. **This is the correct default for any severity count,
#: ranking, or "worst landlord"-style aggregate.** Class I is excluded because
#: it records an administrative notice, not a condition in the building —
#: including it inflates a number that reads as a count of physical hazards.
#: This matches the convention used by HPD's Alternative Enforcement Program
#: and public worst-landlord rankings.
HPD_HAZARD_CLASSES: frozenset[str] = frozenset({"A", "B", "C"})

#: Administrative classes, excluded from hazard counts but meaningful alone:
#: a building with unresolved orders or an invalid registration is its own
#: red flag pattern.
HPD_INFORMATIONAL_CLASSES: frozenset[str] = frozenset({"I"})

#: ECB class values, split by scheme. The hazard scheme covers only 602,640 of
#: 1,699,561 ECB judgments (~35%) — an aggregate filtered on hazard is therefore
#: covering a *minority* of ECB data and must say so.
_ECB_CLASS_NUMBER_VALUES: frozenset[str] = frozenset(
    {"class - 1", "class - 2", "class - 3"}
)
_ECB_HAZARD_VALUES: frozenset[str] = frozenset({"hazardous", "non-hazardous"})


# Raw values observed per pair, for the drift detector and for building filters.
# Stored as the exact strings in the graph, since that is what a query must
# match. HPD-Litigations status is excluded — it is unbounded (1,580 values) and
# is matched by prefix instead.
_RAW_STATUSES: dict[tuple[Source, EventType], tuple[str, ...]] = {
    (Source.HPD, EventType.COMPLAINT): ("OPEN", "CLOSE"),
    (Source.HPD, EventType.VIOLATION): ("Open", "Close"),
    (Source.HPD, EventType.VACATE_ORDER): ("Active", "Rescinded"),
    (Source.DOB, EventType.VIOLATION): ("Active", "Resolved", "Dismissed"),
    (Source.ECB, EventType.JUDGMENT): ("ACTIVE", "RESOLVE", "Unknown"),
    (Source.MARSHAL, EventType.EVICTION): ("POSSESSION", "EVICTION", "P", "EAST"),
}

_RAW_CLASSES: dict[tuple[Source, EventType], tuple[str, ...]] = {
    (Source.HPD, EventType.VIOLATION): ("A", "B", "C", "I"),
    # DOB's codebook, all 56 observed values. Enumerated rather than passed
    # through so that a code from another source — HPD's 'I', say — is reported
    # as unrecognized instead of being silently accepted as a valid DOB code.
    # Note the overlap with HPD on 'A', 'B', 'C', which is the collision that
    # makes source_name mandatory. Genuinely new DOB codes will surface as
    # drift; that is the intended signal, not a false alarm.
    (Source.DOB, EventType.VIOLATION): (
        "7S", "A", "ACC1", "ACH1", "ACJ1", "AEUHAZ1", "B", "BENCH", "C",
        "CLOS", "CMQ", "COMPBLD", "CS", "E", "EARCX", "EB", "EGNCY", "EGRADE",
        "ES", "EVCAT1", "EVCAT5", "FISP", "FISPFCS", "FISPHAZ", "FISPNRF",
        "HBLVIO", "HVCAT5", "HVIOS", "IMD", "IMEGNCY", "JVCAT5", "JVIOS",
        "L1198", "LANDMK", "LANDMRK", "LBLVIO", "LL10/80", "LL10/81", "LL1080",
        "LL1081", "LL11/98", "LL1198", "LL16", "LL2604", "LL2604E", "LL2604S",
        "LL5", "LL6291", "P", "PA", "RWNRF", "UB", "UB*", "V*", "VCAT1", "Z",
    ),
    # ACRIS document-type codes. 'DEED COR', 'DEED, LE' etc. carry spaces and
    # commas, so they must not be split or trimmed on those characters.
    (Source.ACRIS, EventType.DEED_TRANSFER): (
        "CONDEED", "DEED", "DEED COR", "DEED, LE", "DEED, RC", "DEED, TS",
        "DEEDO", "DEEDP",
    ),
    (Source.ACRIS, EventType.MORTGAGE): ("MTGE",),
    (Source.ACRIS, EventType.MORTGAGE_ASSIGNMENT): ("ASST",),
    (Source.ACRIS, EventType.MORTGAGE_SATISFACTION): ("SAT",),
    (Source.HPD, EventType.COMPLAINT): (
        "EMERGENCY",
        "NON EMERGENCY",
        "IMMEDIATE EMERGENCY",
        "HAZARDOUS",
        "REFERRAL",
    ),
    (Source.HPD, EventType.VACATE_ORDER): (
        "Fire Damage",
        "Illegal Occupancy",
        "Habitability",
    ),
    (Source.ECB, EventType.JUDGMENT): (
        "CLASS - 1",
        "CLASS - 2",
        "CLASS - 3",
        "Hazardous",
        "Non-Hazardous",
        "Unknown",
    ),
    (Source.MARSHAL, EventType.EVICTION): ("RESIDENTIAL", "COMMERCIAL"),
    # Housing Court case types. Note the source data's own inconsistencies,
    # reproduced verbatim because that is what a query must match:
    # 'Harrassment' is misspelled upstream, and 'lead' is capitalized in
    # 'Access Warrant - Non-Lead' but not in 'Access Warrant - lead'.
    (Source.HPD_LITIGATIONS, EventType.COURT_FILING): (
        "7A",
        "Access Warrant - Non-Lead",
        "Access Warrant - lead",
        "CONH",
        "Comp Supplemental Cases",
        "Comprehensive",
        "Failure to Register Only",
        "False Certification Non-Lead",
        "HLD - Other Case Type",
        "Heat Supplemental Cases",
        "Heat and Hot Water",
        "Lead False Certification",
        "Tenant Action",
        "Tenant Action/Harrassment",
    ),
}


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def require_pair(source: str | Source, event_type: str | EventType) -> tuple[Source, EventType]:
    """Validate and coerce a ``(source_name, event_type)`` pair.

    This is decision D6 enforced at the signature: every event tool takes a
    source, so ``status``/``violation_class`` can never be interpreted without
    one. Rejects pairs that do not exist, such as ``('DOB', 'Complaint')``.

    :raises VocabularyError: on an unknown value or an impossible combination.
    """
    if source is None or event_type is None:
        raise VocabularyError(
            "source_name and event_type are both required; status and "
            "violation_class cannot be interpreted without a source"
        )
    try:
        resolved_source = Source(source)
    except ValueError as exc:
        valid = ", ".join(sorted(s.value for s in Source))
        raise VocabularyError(f"Unknown source_name {source!r}; expected one of: {valid}") from exc
    try:
        resolved_type = EventType(event_type)
    except ValueError as exc:
        valid = ", ".join(sorted(t.value for t in EventType))
        raise VocabularyError(f"Unknown event_type {event_type!r}; expected one of: {valid}") from exc

    if (resolved_source, resolved_type) not in VALID_PAIRS:
        emitted = sorted(t.value for s, t in VALID_PAIRS if s is resolved_source)
        raise VocabularyError(
            f"{resolved_source.value!r} does not emit {resolved_type.value!r}; "
            f"it emits: {', '.join(emitted)}"
        )
    return resolved_source, resolved_type


def _normalize(raw: str) -> str:
    return raw.strip().casefold()


def _status_key(source: Source, raw: str) -> str:
    """Reduce a raw status to its lookup key.

    HPD-Litigations values carry a trailing date with inconsistent separators
    (``'GRANTED - 02/08/2022'``, ``'Exempt- 08/29/2022'``, ``'DENIED ,
    10/31/2016'``), so the leading token is taken and trailing punctuation
    stripped. Other sources use the value as-is, case-folded.
    """
    text = raw.strip()
    if source is Source.HPD_LITIGATIONS:
        text = text.split(" ", 1)[0].rstrip("-,;: ")
    return _normalize(text)


def canonical_status(
    source: str | Source, event_type: str | EventType, raw: str | None
) -> Status:
    """Map a raw ``Event.status`` to a canonical :class:`Status`.

    Case-insensitive by construction. ``None`` becomes
    :attr:`Status.NOT_RECORDED`; an unrecognized value becomes
    :attr:`Status.UNKNOWN` — never dropped, never guessed.
    """
    resolved_source, resolved_type = require_pair(source, event_type)
    if raw is None or not str(raw).strip():
        return Status.NOT_RECORDED
    mapping = _STATUS_MAP.get((resolved_source, resolved_type), {})
    return mapping.get(_status_key(resolved_source, str(raw)), Status.UNKNOWN)


def is_open(source: str | Source, event_type: str | EventType, raw: str | None) -> bool:
    """Whether a raw status means "outstanding right now"."""
    return canonical_status(source, event_type, raw) in OPEN_STATUSES


@dataclass(frozen=True)
class RawFilter:
    """How to match a canonical value against the raw column in Cypher.

    Two match modes because the data needs both: most sources have a small
    closed set of exact values, while ``HPD-Litigations.status`` embeds a date
    and must be matched by prefix.
    """

    #: Exact raw values, already uppercased for case-insensitive comparison.
    exact: tuple[str, ...] = ()
    #: Raw prefixes, already uppercased.
    prefixes: tuple[str, ...] = ()
    #: Whether a null in the column should match.
    match_null: bool = False

    def __bool__(self) -> bool:
        return bool(self.exact or self.prefixes or self.match_null)

    def to_cypher(self, column: str, param: str = "vals") -> tuple[str, dict[str, object]]:
        """Build a predicate fragment and its parameters.

        Comparison is via ``toUpper`` rather than exact string equality, so a
        casing change in the pipeline degrades to still-correct results instead
        of silently returning zero rows. There is no index on ``status`` or
        ``violation_class``, so this costs nothing in plan terms.

        :param column: The qualified column, e.g. ``"e.status"``.
        :param param: Base name for generated parameters.
        :returns: ``(fragment, params)``. Fragment is ``"false"`` when nothing
            can match, which keeps callers from having to special-case it.
        """
        clauses: list[str] = []
        params: dict[str, object] = {}
        if self.exact:
            clauses.append(f"toUpper({column}) IN ${param}_exact")
            params[f"{param}_exact"] = list(self.exact)
        for index, prefix in enumerate(self.prefixes):
            name = f"{param}_prefix_{index}"
            clauses.append(f"toUpper({column}) STARTS WITH ${name}")
            params[name] = prefix
        if self.match_null:
            clauses.append(f"{column} IS NULL")
        if not clauses:
            return "false", {}
        return "(" + " OR ".join(clauses) + ")", params


def status_filter(
    source: str | Source,
    event_type: str | EventType,
    statuses: Status | set[Status] | frozenset[Status],
) -> RawFilter:
    """Raw-value filter matching the given canonical status(es).

    This is what makes a canonical query correct across sources: asking for
    :attr:`Status.OPEN` produces ``'OPEN'`` for HPD complaints and ``'Open'``
    for HPD violations, without the caller knowing that difference exists.
    """
    resolved_source, resolved_type = require_pair(source, event_type)
    wanted = {statuses} if isinstance(statuses, Status) else set(statuses)

    if Status.NOT_RECORDED in wanted and not wanted - {Status.NOT_RECORDED}:
        return RawFilter(match_null=True)

    mapping = _STATUS_MAP.get((resolved_source, resolved_type), {})
    keys = [key for key, canonical in mapping.items() if canonical in wanted]

    if resolved_source is Source.HPD_LITIGATIONS:
        # Raw values are '<TOKEN>[-,] <date>' or a bare token, so prefix match.
        return RawFilter(
            prefixes=tuple(sorted(key.upper() for key in keys)),
            match_null=Status.NOT_RECORDED in wanted,
        )

    raw_values = _RAW_STATUSES.get((resolved_source, resolved_type), ())
    exact = tuple(
        sorted(
            value.upper()
            for value in raw_values
            if _status_key(resolved_source, value) in keys
        )
    )
    return RawFilter(exact=exact, match_null=Status.NOT_RECORDED in wanted)


def class_schemes_for(
    source: str | Source, event_type: str | EventType
) -> tuple[ClassScheme, ...]:
    """Which scheme(s) ``violation_class`` uses for this pair.

    Returns more than one only for ECB ``Judgment``, which mixes a numeric class
    scheme and a hazard scheme in the same column.
    """
    resolved_source, resolved_type = require_pair(source, event_type)
    return _CLASS_SCHEMES.get((resolved_source, resolved_type), ())


def canonical_class(
    source: str | Source, event_type: str | EventType, raw: str | None
) -> tuple[ClassScheme | None, str | None]:
    """Interpret a raw ``violation_class`` for this pair.

    :returns: ``(scheme, value)``. ``scheme`` is ``None`` when the value is not
        recognized for this pair, and ``value`` is ``None`` when the column is
        null. Returning the scheme alongside the value is the point — a bare
        ``'C'`` is meaningless without knowing it came from HPD's hazard scheme
        rather than DOB's code list.
    """
    resolved_source, resolved_type = require_pair(source, event_type)
    if raw is None or not str(raw).strip():
        return None, None

    text = str(raw).strip()
    normalized = _normalize(text)
    schemes = _CLASS_SCHEMES.get((resolved_source, resolved_type), ())

    # ECB is the split-scheme case; decide which one this value belongs to.
    if (resolved_source, resolved_type) == (Source.ECB, EventType.JUDGMENT):
        if normalized in _ECB_CLASS_NUMBER_VALUES:
            return ClassScheme.ECB_CLASS_NUMBER, text
        if normalized in _ECB_HAZARD_VALUES:
            return ClassScheme.ECB_HAZARD, text
        return None, text

    known = _RAW_CLASSES.get((resolved_source, resolved_type))
    if known is not None and normalized not in {_normalize(v) for v in known}:
        return None, text
    return (schemes[0] if schemes else None), text


def class_filter(
    source: str | Source, event_type: str | EventType, codes: str | set[str] | frozenset[str]
) -> RawFilter:
    """Raw-value filter for ``violation_class``, scoped to one source.

    A source is mandatory (via :func:`require_pair`), which is what stops
    ``'C'`` from matching both HPD's immediately-hazardous class and DOB's
    unrelated code ``'C'``.
    """
    require_pair(source, event_type)
    wanted = {codes} if isinstance(codes, str) else set(codes)
    if not wanted:
        raise VocabularyError("At least one class code is required")
    return RawFilter(exact=tuple(sorted(code.strip().upper() for code in wanted)))


def hpd_hazard_filter(codes: str | set[str] | frozenset[str] | None = None) -> RawFilter:
    """Filter for HPD violation classes on the hazard scale.

    Defaults to A/B/C — **excluding Class I**, which is an administrative
    notice rather than a condition found on inspection. Any severity count,
    ranking, or life-safety aggregate should use this rather than
    :func:`class_filter`, so the 804,440 informational rows cannot inflate a
    number readers will take as a count of physical hazards.

    Pass *codes* explicitly for a narrower slice, e.g.
    ``{HPD_IMMEDIATELY_HAZARDOUS}`` for life-safety only. To include Class I
    deliberately — a class *breakdown* legitimately shows all four — use
    :func:`class_filter` instead and say so in the output.

    :raises VocabularyError: if *codes* includes a non-hazard class, since that
        is almost always a mistake rather than an intent.
    """
    wanted = set(HPD_HAZARD_CLASSES) if codes is None else (
        {codes} if isinstance(codes, str) else set(codes)
    )
    wanted = {code.strip().upper() for code in wanted}
    non_hazard = wanted - HPD_HAZARD_CLASSES
    if non_hazard:
        raise VocabularyError(
            f"{sorted(non_hazard)} is not on HPD's hazard scale "
            f"({sorted(HPD_HAZARD_CLASSES)}). Class I is an administrative "
            "notice, not an inspected condition — use class_filter() if you "
            "genuinely want it, and disclose that in the output."
        )
    return class_filter(Source.HPD, EventType.VIOLATION, wanted)


def expected_raw_statuses() -> dict[tuple[Source, EventType], tuple[str, ...]]:
    """Raw status values this module claims exist. For the drift detector."""
    return dict(_RAW_STATUSES)


def expected_raw_classes() -> dict[tuple[Source, EventType], tuple[str, ...]]:
    """Raw class values this module claims exist. For the drift detector."""
    return dict(_RAW_CLASSES)
