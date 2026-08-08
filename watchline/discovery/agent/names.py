"""Comparing two party names without claiming they are the same party.

Implements decision P1-2. Used by the flagship ownership tool to say whether
``Building.dof_ownername`` (the DOF record) and the ``Landlord`` reached via
``APPARENT_CONTROL`` (an inference) appear to describe the same party.

**Why this module exists at all.** The two values cannot be string-compared. Real
pairs from the graph:

===========================  =========================  ===============
Recorded owner               Apparent controller        Reality
===========================  =========================  ===============
``'LIBERT, LARS PETER'``     ``'(LARS) PETER LIBERT'``  same person
``'ANGELO MARSILLO'``        ``'.ARSILLO ANGELO'``      same person, typo
``'3071 HULL REALTY LLC'``   ``',MARIA CROSS'``         genuinely different
===========================  =========================  ===============

Equality would report disagreement on all three. Since `CLAUDE.md` treats a
recorded-owner/apparent-controller *disagreement* as itself an interesting
finding, a comparison that cries disagreement constantly is worse than none.

**What this module deliberately does not do.** No edit distance, no similarity
score, no fuzzy matching, no threshold. A numeric closeness between two party
names is a quasi-identity claim, and this system must never make one (D2). Where
a score would guess, :attr:`OwnershipVerdict.INDETERMINATE` says so out loud.
``tests/test_names.py`` asserts no scoring function exists, so a future
"helpful" addition fails a test rather than passing review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "OwnershipVerdict",
    "NameComparison",
    "LEGAL_FORM_TOKENS",
    "normalize",
    "compare_names",
]


class OwnershipVerdict(StrEnum):
    """The outcome of comparing a recorded owner against an apparent controller.

    Three of these are comparison results. :attr:`NOT_COMPARABLE` is not a
    fourth opinion — it means there was nothing to compare, and it is the
    **majority** outcome: ``APPARENT_CONTROL`` reaches only 171,347 of 859,794
    buildings, so roughly 80% of lookups have no controller to compare against.
    Callers must render it as "the graph has no apparent controller for this
    building", never as a failed comparison or an empty result.
    """

    #: Normalized token sets are identical. The same party, written differently.
    AGREES = "agrees"
    #: No distinguishing token in common. Genuinely different parties as recorded
    #: — which is often the shell-entity pattern, and the interesting answer.
    DIFFERS = "differs"
    #: Some distinguishing tokens shared, others not. Cannot be resolved without
    #: judgment this system will not make. Says so rather than guessing.
    INDETERMINATE = "indeterminate"
    #: One or both sides absent. Nothing was compared.
    NOT_COMPARABLE = "not_comparable"


#: Legal-form tokens, which say what kind of entity something is rather than
#: which entity it is. They are **not stripped** — they still count toward set
#: equality, so ``'X REALTY LLC'`` and ``'X REALTY INC'`` never come back as
#: :attr:`OwnershipVerdict.AGREES`. They are excluded only from the *overlap*
#: test, because sharing ``'llc'`` is no evidence of shared identity.
#:
#: Without this, almost every company-vs-company pair would land in
#: INDETERMINATE on the strength of ``'llc'`` alone — which would drain the
#: verdict of meaning in exactly the cases users care about.
LEGAL_FORM_TOKENS: frozenset[str] = frozenset(
    {
        "llc",
        "lc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "lp",
        "llp",
        "lllp",
        "ltd",
        "limited",
        "plc",
        "pc",
        "pa",
    }
)

# Periods and apostrophes are removed rather than split on, so 'L.L.C.' becomes
# one token 'llc' and "O'BRIEN" becomes 'obrien'. Every other non-alphanumeric
# character becomes a separator, which handles the leading commas, leading
# periods, parentheses, slashes and asterisks the real data carries.
_INTRA_WORD = re.compile(r"[.'’]")
_SEPARATOR = re.compile(r"[^0-9a-z]+")


def _is_initial(token: str) -> bool:
    """A single *letter* — a middle initial.

    Alphabetic only. A single **digit** is a building number, not an initial:
    ``'5 HULL REALTY LLC'`` and ``'HULL REALTY LLC'`` are plausibly different
    entities, and NYC is full of single-digit addresses (1 Liberty Island,
    7 World Trade). Dropping the digit would merge them.
    """
    return len(token) == 1 and token.isalpha()


def _drop_one_sided_initials(
    left: set[str], right: set[str]
) -> tuple[set[str], set[str], tuple[str, ...]]:
    """Disregard a middle initial that appears on one side and not the other.

    ``'COX, AARON R'`` and ``'AARON COX'`` are the same person. Measured over
    every controlled building, 6,459 pairs — 20% of all indeterminate verdicts —
    differed by nothing else.

    **Only one-sided initials are dropped, and that restriction is the whole
    point.** An initial present on one side and absent on the other carries no
    contradicting information. An initial present on *both* sides can contradict:
    ``'JOHN A SMITH'`` and ``'JOHN B SMITH'`` may be father and son, and
    collapsing them would merge two people. So when both sides carry initials,
    nothing is dropped and the pair stays indeterminate — **by construction, not
    because the data happens to lack such a case today.** (It does lack one: 0 of
    the 6,459 have differing initials on each side. That measurement motivated
    the rule; it does not guarantee it.)

    Nothing is dropped if it would empty a side. A name that is *only* initials
    cannot be compared meaningfully, but ``NOT_COMPARABLE`` means "a side was
    absent" — inventing that state through our own normalization would be a
    different claim than the data supports.

    :returns: ``(effective_left, effective_right, disregarded_initials)``.
    """
    left_initials = {token for token in left if _is_initial(token)}
    right_initials = {token for token in right if _is_initial(token)}

    if left_initials and not right_initials and left - left_initials:
        return left - left_initials, right, tuple(sorted(left_initials))
    if right_initials and not left_initials and right - right_initials:
        return left, right - right_initials, tuple(sorted(right_initials))
    return left, right, ()


def normalize(raw: str | None) -> tuple[str, ...]:
    """Reduce a raw name to comparable tokens, in sorted order.

    Case-folded, punctuation-normalized, whitespace-collapsed. Sorted so that
    ``'LIBERT, LARS PETER'`` and ``'(LARS) PETER LIBERT'`` produce the same
    tuple — surname-first versus given-name-first is a formatting difference,
    not a different party.

    Numeric tokens are kept: ``'3071 HULL REALTY LLC'`` genuinely contains
    ``'3071'``, and dropping it would lose signal for the many NYC entities
    named after a building number.

    Returns an empty tuple for ``None``, an empty string, or a value with no
    alphanumeric content at all.
    """
    if not raw or not isinstance(raw, str):
        return ()
    collapsed = _INTRA_WORD.sub("", raw.casefold())
    tokens = (token for token in _SEPARATOR.split(collapsed) if token)
    return tuple(sorted(set(tokens)))


@dataclass(frozen=True)
class NameComparison:
    """A verdict plus the evidence behind it.

    The evidence is the point. A bare verdict reads as a determination; showing
    which tokens matched and which did not lets a caller present the comparison
    as an observation the reader can check. ``CLAUDE.md`` forbids emitting or
    implying a legal ownership determination, and "these two records share the
    tokens X and Y" is an observation where "these are the same party" would be
    a claim.
    """

    verdict: OwnershipVerdict
    #: Verbatim inputs, so a caller never has to reconstruct them.
    left_raw: str | None
    right_raw: str | None
    left_tokens: tuple[str, ...]
    right_tokens: tuple[str, ...]
    #: Tokens present on both sides, legal forms included.
    shared_tokens: tuple[str, ...]
    #: Tokens on one side only.
    left_only: tuple[str, ...]
    right_only: tuple[str, ...]
    #: Shared tokens that actually carry identity — ``shared_tokens`` minus
    #: :data:`LEGAL_FORM_TOKENS`. This is what the verdict is computed from.
    shared_distinguishing: tuple[str, ...]
    #: Middle initials disregarded because they appeared on one side only —
    #: see :func:`_drop_one_sided_initials`. Reported so a reader can see *why*
    #: two differently-written names were treated as matching, rather than
    #: having to infer it from an unexplained ``AGREES``.
    disregarded_initials: tuple[str, ...] = ()

    @property
    def comparable(self) -> bool:
        """Whether a comparison happened at all."""
        return self.verdict is not OwnershipVerdict.NOT_COMPARABLE


def compare_names(left: str | None, right: str | None) -> NameComparison:
    """Compare two party names and report a verdict with its evidence.

    The rule, in full:

    * either side absent → :attr:`~OwnershipVerdict.NOT_COMPARABLE`
    * a middle initial on one side only is disregarded
      (:func:`_drop_one_sided_initials`)
    * identical token sets → :attr:`~OwnershipVerdict.AGREES`
    * no shared *distinguishing* token → :attr:`~OwnershipVerdict.DIFFERS`
    * otherwise → :attr:`~OwnershipVerdict.INDETERMINATE`

    The verdict is symmetric: swapping the arguments cannot change it. The
    evidence is not — ``left_only`` and ``right_only`` swap with the arguments,
    which is intended, since a caller wants to know *which* record carried the
    unmatched tokens.

    ``left_tokens`` and ``right_tokens`` report the full normalized input, so
    the raw comparison stays traceable. Everything else — the shared and
    disjoint sets — is reported *after* any disregarded initial, so the evidence
    explains the verdict rather than appearing to contradict it.
    """
    left_tokens = normalize(left)
    right_tokens = normalize(right)

    left_set, right_set, disregarded = _drop_one_sided_initials(
        set(left_tokens), set(right_tokens)
    )
    shared = tuple(sorted(left_set & right_set))
    shared_distinguishing = tuple(token for token in shared if token not in LEGAL_FORM_TOKENS)

    common = {
        "left_raw": left,
        "right_raw": right,
        "left_tokens": left_tokens,
        "right_tokens": right_tokens,
        "shared_tokens": shared,
        "left_only": tuple(sorted(left_set - right_set)),
        "right_only": tuple(sorted(right_set - left_set)),
        "shared_distinguishing": shared_distinguishing,
        "disregarded_initials": disregarded,
    }

    if not left_tokens or not right_tokens:
        return NameComparison(verdict=OwnershipVerdict.NOT_COMPARABLE, **common)
    if left_set == right_set:
        return NameComparison(verdict=OwnershipVerdict.AGREES, **common)
    if not shared_distinguishing:
        return NameComparison(verdict=OwnershipVerdict.DIFFERS, **common)
    return NameComparison(verdict=OwnershipVerdict.INDETERMINATE, **common)
