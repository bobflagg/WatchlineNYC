"""
watchline/fw/intents/mortgage_concealment.py

Intent: MortgageBasedConcealment
Rule:   MBC-001 v1.0 (RUL-00017)

A building satisfies MBC-001 if its most recent ACRIS DeedTransfer has a
grantee name, a Mortgage event exists on the same building within a
purchase-money window of that deed (-14 to +60 days), and the mortgagor
name(s) on that mortgage share no name token with the deed's grantee
name(s). Under normal purchase-money financing the buyer of record and the
borrower of record are the same party; a mismatch means someone else
financed the purchase, a classic nominee/straw-buyer signal.

Calibration (verified against live evidentiary data 2026-07-17): 2.9% of
matched purchase-money pairs show zero name overlap -- low and
well-discriminated relative to OwnershipNameDiscrepancy's 71%, because both
compared names come from the SAME ACRIS self-reporting convention on the
SAME closing package, not two independently-sourced datasets. Confidence:
Medium (see RUL-00017 amendment_notes for the full breakdown).

Entity class: building. Evaluates only the building's most recent deed
transfer (matching the OC-001 precedent), not its full transaction history.
"""

import re

from watchline.fw.intents.base import IntentHandler


# ---------------------------------------------------------------------------
# Cypher
# ---------------------------------------------------------------------------

_CYPHER = """
MATCH (b:Building {bbl: $bbl})

OPTIONAL MATCH (b)-[:HAS_EVENT]->(d:Event {event_type: 'DeedTransfer', source_name: 'ACRIS'})
WHERE d.event_date IS NOT NULL AND d.grantee_names IS NOT NULL
WITH b, d
ORDER BY d.event_date DESC
WITH b, collect(d)[0] AS latest_deed

OPTIONAL MATCH (b)-[:HAS_EVENT]->(m:Event {event_type: 'Mortgage', source_name: 'ACRIS'})
WHERE latest_deed IS NOT NULL AND m.event_date IS NOT NULL AND m.mortgagor_names IS NOT NULL
  AND duration.inDays(latest_deed.event_date, m.event_date).days >= -14
  AND duration.inDays(latest_deed.event_date, m.event_date).days <= 60
WITH b, latest_deed, m,
     CASE WHEN m IS NOT NULL
          THEN abs(duration.inDays(latest_deed.event_date, m.event_date).days)
          ELSE null END AS gap
ORDER BY gap ASC
WITH b, latest_deed, collect(m)[0] AS nearest_mortgage

RETURN
  b.bbl               AS bbl,
  b.address           AS address,
  b.borough           AS borough,
  b.residential_units AS residential_units,
  latest_deed.event_date    AS deed_date,
  latest_deed.grantee_names AS grantee_names,
  latest_deed.grantor_names AS grantor_names,
  latest_deed.doc_amount    AS deed_amount,
  nearest_mortgage.event_date      AS mortgage_date,
  nearest_mortgage.mortgagor_names AS mortgagor_names,
  nearest_mortgage.mortgagee_names AS mortgagee_names,
  nearest_mortgage.doc_amount      AS mortgage_amount
"""

# ---------------------------------------------------------------------------
# Token normalization (matches ownership_name_discrepancy.py's approach --
# not shared code, this codebase's convention is self-contained modules)
# ---------------------------------------------------------------------------

def _norm_tokens(name: str | None) -> set:
    if not name:
        return set()
    cleaned = re.sub(r"[^A-Za-z\s]", " ", name.upper())
    return {t for t in cleaned.split() if len(t) > 1}


# ---------------------------------------------------------------------------
# Rule metadata
# Charter §11: Rules are first-class objects stored in the graph.
# _load_rule_from_graph() fetches live metadata from RUL-00017 at runtime.
# Fallback constants are used only if the graph is unavailable.
# ---------------------------------------------------------------------------

_RULE_ID       = "MBC-001"
_RULE_VERSION  = "1.0"
_GRAPH_RULE_ID = "RUL-00017"

_THRESHOLD_STATEMENT_FALLBACK = (
    "A building satisfies Watchline Rule MBC-001 (Mortgage-Based Concealment) "
    "if: (1) its most recent ACRIS DeedTransfer has a grantee name on record; "
    "AND (2) a Mortgage event exists on the same building recorded within -14 "
    "to +60 days of that deed (its purchase-money mortgage); AND (3) the "
    "mortgagor name(s) on that mortgage share no name token in common with "
    "the deed's grantee name(s). A building with no deed transfer, or with a "
    "deed but no mortgage recorded in the purchase-money window, is "
    "insufficient_data. This finding is Medium confidence."
)

_rule_cache: dict | None = None


def _load_rule_from_graph() -> dict:
    """
    Load MBC-001 Rule metadata from the graph (Charter §11).
    Cached in module scope after first load.
    Falls back to hardcoded constants if graph is unavailable.
    """
    global _rule_cache
    if _rule_cache is not None:
        return _rule_cache
    try:
        from watchline.fw.connections import neo4j_query
        results = neo4j_query(
            "MATCH (r:Rule {rule_id: $rule_id}) "
            "RETURN r.name AS name, r.version AS version, "
            "r.threshold_description AS threshold_description, "
            "r.authority AS authority, r.effective_date AS effective_date, "
            "r.author AS author, "
            "r.falsification_conditions AS falsification_conditions",
            params={"rule_id": _GRAPH_RULE_ID},
        )
        if results:
            r = dict(results[0])
            if r.get("effective_date") and not isinstance(r["effective_date"], str):
                r["effective_date"] = str(r["effective_date"])
            _rule_cache = r
            return _rule_cache
    except Exception:
        pass
    _rule_cache = {
        "name":                     _RULE_ID,
        "version":                  _RULE_VERSION,
        "threshold_description":    _THRESHOLD_STATEMENT_FALLBACK,
        "authority":                "Watchline editorial judgment",
        "effective_date":           "2026-07-17",
        "author":                   "Watchline NYC project team",
        "falsification_conditions": "",
    }
    return _rule_cache


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class MortgageBasedConcealmentHandler(IntentHandler):

    intent_category = "MortgageBasedConcealment"
    entity_class    = "building"

    def get_cypher(self) -> str:
        return _CYPHER

    def get_params(self, intent: dict) -> dict:
        return {"bbl": intent["bbl"]}

    def _insufficient(self, rule: dict, reason: str, **extra) -> dict:
        return {
            "rule_id":              _RULE_ID,
            "rule_version":         rule.get("version", _RULE_VERSION),
            "concealment_flagged":  None,
            "insufficient_data":    True,
            "reason":               reason,
            "deed_date":            extra.get("deed_date"),
            "grantee_names":        extra.get("grantee_names"),
            "mortgage_date":        extra.get("mortgage_date"),
            "mortgagor_names":      extra.get("mortgagor_names"),
            "token_overlap":        None,
            "confidence":           "Medium",
            "interpretive_status":  "Inferred",
            "threshold_statement":  rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":            rule.get("authority", ""),
            "effective_date":       rule.get("effective_date", ""),
            "author":               rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }

    def evaluate(self, raw_results: list) -> dict | None:
        rule = _load_rule_from_graph()

        if not raw_results:
            return self._insufficient(rule, "building_not_resolved")

        row = raw_results[0]
        deed_date       = row.get("deed_date")
        grantee_names   = row.get("grantee_names")
        mortgage_date   = row.get("mortgage_date")
        mortgagor_names = row.get("mortgagor_names")

        if not deed_date or not grantee_names:
            return self._insufficient(rule, "no_deed_transfer")

        if not mortgage_date or not mortgagor_names:
            return self._insufficient(
                rule, "no_contemporaneous_mortgage",
                deed_date=deed_date, grantee_names=grantee_names,
            )

        g_tokens = _norm_tokens(grantee_names)
        m_tokens = _norm_tokens(mortgagor_names)
        if not g_tokens or not m_tokens:
            return self._insufficient(
                rule, "unparseable_names",
                deed_date=deed_date, grantee_names=grantee_names,
                mortgage_date=mortgage_date, mortgagor_names=mortgagor_names,
            )

        token_overlap = bool(g_tokens & m_tokens)
        concealment_flagged = not token_overlap

        return {
            "rule_id":                  _RULE_ID,
            "rule_version":             rule.get("version", _RULE_VERSION),
            "concealment_flagged":      concealment_flagged,
            "insufficient_data":        False,
            "reason":                   None,
            "deed_date":                deed_date,
            "grantee_names":            grantee_names,
            "grantor_names":            row.get("grantor_names"),
            "deed_amount":              row.get("deed_amount"),
            "mortgage_date":            mortgage_date,
            "mortgagor_names":          mortgagor_names,
            "mortgagee_names":          row.get("mortgagee_names"),
            "mortgage_amount":          row.get("mortgage_amount"),
            "token_overlap":            token_overlap,
            "confidence":               "Medium",
            "interpretive_status":      "Inferred",
            "threshold_statement":      rule.get("threshold_description", _THRESHOLD_STATEMENT_FALLBACK),
            "authority":                rule.get("authority", ""),
            "effective_date":           rule.get("effective_date", ""),
            "author":                   rule.get("author", ""),
            "falsification_conditions": rule.get("falsification_conditions", ""),
        }
