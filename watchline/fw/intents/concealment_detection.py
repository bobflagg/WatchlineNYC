"""
watchline/fw/intents/concealment_detection.py

Intent: ConcealmentDetection
Rule:   Uses existing RUL-00003 (name-based connections) and RUL-00004
        (address-based connections) — no new rule.

A portfolio assembled primarily through address-based connections rather than
name-based connections is a structural concealment signal: buildings are held
under different entity names at the same registered business address, rather
than by a consistently-named registrant. The ratio of address to name
connections is the primary indicator.

Concealment flag: addr_edges > 10 × name_edges
                  (or: addr_edges >= 2 when name_edges == 0)
"""

import re

from watchline.fw.intents.base import IntentHandler

_ADDR_NAME_RATIO_THRESHOLD = 10   # address connections must exceed name × this
_ADDR_MIN_WHEN_ZERO_NAME   = 2    # minimum addr connections to flag when name == 0

# Regex for parsing the Evidence node summary
_EDGE_COUNT_PATTERN = re.compile(
    r"(\d+) address-based and (\d+) name-based"
)


def _parse_edge_counts(evidence_summary: str | None) -> tuple[int, int]:
    """Return (addr_edges, name_edges) from Evidence.summary, or (0, 0)."""
    if not evidence_summary:
        return 0, 0
    m = _EDGE_COUNT_PATTERN.search(evidence_summary)
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


_CYPHER = """
MATCH (a:Actor {canonical_id: $canonical_id})

// Current active IdentityAssertion — aggregate before continuing
OPTIONAL MATCH (ia:IdentityAssertion)-[:RESOLVES_TO]->(a)
WHERE ia.superseded_by IS NULL

OPTIONAL MATCH (ia)-[:ASSERTS_IDENTITY_OF]->(io:IdentityObservation)

WITH a, ia,
  count(DISTINCT io)            AS distinct_names,
  collect(DISTINCT io.raw_name) AS observed_names

// Current active PBC Claim (valid_to IS NULL = not superseded)
OPTIONAL MATCH (c:Claim {
  subject_id:            a.canonical_id,
  interpretive_concept:  "ProbableBeneficialControl"
})
WHERE c.valid_to IS NULL

OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(ev:Evidence)

WITH a, ia, distinct_names, observed_names,
  c.claim_text  AS pbc_claim,
  ev.summary    AS evidence_summary

// Portfolio size (separate step to avoid cross-product with io nodes)
OPTIONAL MATCH (bc:Relationship {relationship_type: "BeneficialControl"})-[:INVOLVES_ACTOR]->(a)
OPTIONAL MATCH (bc)-[:INVOLVES_BUILDING]->(b:Building)

RETURN a.display_name              AS name,
       a.canonical_id              AS canonical_id,
       ia.confidence               AS confidence,
       ia.rationale                AS rationale,
       distinct_names,
       observed_names,
       pbc_claim,
       evidence_summary,
       count(DISTINCT b.bbl)       AS portfolio_size
"""


class ConcealmentDetectionHandler(IntentHandler):

    intent_category = "ConcealmentDetection"
    entity_class    = "actor"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"canonical_id": intent["canonical_id"]}

    def evaluate(self, raw_results: list) -> dict | None:
        if not raw_results:
            return {
                "interpretive_status":   "Inferred",
                "insufficient_data":     True,
                "concealment_flagged":   False,
                "addr_edges":            0,
                "name_edges":            0,
                "addr_name_ratio":       None,
                "threshold_statement":   (
                    "A portfolio satisfies the concealment signal if address-based "
                    "HPD registration connections exceed name-based connections by "
                    f"more than {_ADDR_NAME_RATIO_THRESHOLD}×, indicating that "
                    "buildings are linked through a shared business address rather "
                    "than a consistently-named registrant."
                ),
            }

        r                = raw_results[0]
        evidence_summary = r.get("evidence_summary") or ""
        addr_edges, name_edges = _parse_edge_counts(evidence_summary)
        portfolio_size   = int(r.get("portfolio_size") or 0)
        distinct_names   = int(r.get("distinct_names") or 0)
        observed_names   = [n for n in (r.get("observed_names") or []) if n]

        # Concealment flag
        if name_edges == 0:
            concealment_flagged = addr_edges >= _ADDR_MIN_WHEN_ZERO_NAME
        else:
            concealment_flagged = addr_edges > _ADDR_NAME_RATIO_THRESHOLD * name_edges

        addr_name_ratio = (
            round(addr_edges / name_edges, 1) if name_edges > 0
            else None  # undefined when name_edges == 0
        )

        # Name diversity: distinct entity names per building
        name_diversity = (
            round(distinct_names / portfolio_size, 2)
            if portfolio_size > 0 else None
        )

        insufficient = (addr_edges + name_edges == 0)

        return {
            "interpretive_status":   "Inferred",
            "insufficient_data":     insufficient,
            "concealment_flagged":   concealment_flagged,
            "addr_edges":            addr_edges,
            "name_edges":            name_edges,
            "addr_name_ratio":       addr_name_ratio,
            "distinct_names":        distinct_names,
            "observed_names":        observed_names,
            "portfolio_size":        portfolio_size,
            "name_diversity":        name_diversity,
            "confidence":            r.get("confidence") or "—",
            "rationale":             r.get("rationale") or "—",
            "threshold_statement":   (
                "A portfolio satisfies the concealment signal if address-based "
                "HPD registration connections exceed name-based connections by "
                f"more than {_ADDR_NAME_RATIO_THRESHOLD}×. This indicates that "
                "buildings are linked through a shared business address rather than "
                "a consistently-named registrant — a structural pattern associated "
                "with LLC fragmentation. Rules RMT-001 (RUL-00003) and RMT-002 "
                "(RUL-00004) define the name-based and address-based connection "
                "types respectively."
            ),
        }
