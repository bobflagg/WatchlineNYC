"""Sample questions for the sidebar, using real anchors from the discovery graph.

These mirror the anchors in ``tests/fixtures/example_queries.json`` — concrete
BBLs, landlords, and portfolios that resolve against the ``watchline-discovery``
graph. Kept as a plain curated list (no coupling to the test tree); update if the
anchors change. No Streamlit import, so it is trivially testable.
"""

from __future__ import annotations

#: Tier 1–3 questions — answerable on any thread.
SAMPLE_QUESTIONS: list[str] = [
    "Who owns the building at BBL 1000050010, and how confident is that?",
    "How many residential units are in the building at BBL 1000050010?",
    "How many open HPD violations does BBL 2028100045 have?",
    "How many eviction filings were there in the Bronx in 2025?",
    "What are the sister buildings of BBL 1000050010?",
    "Does the registered landlord match the DOF-recorded owner for BBL 1000050010?",
    "Show the apparent-control network for portfolio PF-20260729T002106Z-1176.",
]

#: Tier 4 — only meaningful on a vetted thread (runs a deep investigation).
VETTED_SAMPLE_QUESTIONS: list[str] = [
    "Build a referral-ready case file on landlord ACT-LL-42357 (GLEN BROWN): "
    "patterns of neglect across their portfolio, worst buildings first.",
    "Build a referral-ready case file on landlord ACT-LL-105699 (STEVEN CROMAN): "
    "patterns of neglect across their portfolio, worst buildings first. Corroborate with public reporting and any enforcement or litigation history."
]


def sample_questions(trust_level: str) -> list[str]:
    """The sample questions to offer; the deep one only on a vetted thread."""
    if trust_level == "vetted":
        return [*SAMPLE_QUESTIONS, *VETTED_SAMPLE_QUESTIONS]
    return list(SAMPLE_QUESTIONS)
