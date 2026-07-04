"""
watchline/fw/state.py

Shared LangGraph state definition for the Watchline pipeline.
"""

from typing import Optional
from typing_extensions import TypedDict


class WatchlineState(TypedDict):
    question:              str
    intent:                dict   # entity type, identifiers, intent category
    traversal_results:     dict   # raw data + rule_evaluation returned from Neo4j
    answer:                str    # final plain-language answer
    needs_clarification:   bool   # routing flag
    clarification_request: str    # what to ask the user
    error:                 Optional[str]  # pipeline error message
    dashboard_html:        Optional[str]  # rendered HTML dashboard
