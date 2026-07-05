"""
watchline/fw/investigator.py

Watchline NYC -- AI Query Layer

Builds and exposes the LangGraph pipeline. All node logic lives in
dedicated modules; this file is the graph definition only.

Architecture (Charter Principle 17: AI as orchestrator, not reasoner):
  The LLM identifies intent and narrates results.
  The graph retrieves evidence and evaluates rules.
  Claims are never produced by the LLM -- only by defined Rules.

Pipeline nodes:
  identify_intent       -- LLM extracts entity and investigative intent
  select_rules          -- Maps intent to handler, resolves entity
  execute_traversal     -- Runs Cypher, applies rule evaluation
  present_results       -- LLM narrates graph data with Rule citations
  render_dashboard      -- Assembles self-contained HTML dashboard
  request_clarification -- Fires when entity cannot be resolved

Usage:
  from watchline.fw.investigator import build_pipeline

  graph  = build_pipeline()
  result = graph.invoke({"question": "Is 122 West 97th Street getting worse?"})
  print(result["answer"])
"""

from langgraph.graph import END, START, StateGraph

from watchline.fw.state    import WatchlineState
from watchline.fw.intent   import identify_intent
from watchline.fw.router   import (
    select_rules,
    execute_traversal,
    request_clarification,
    route_after_rules,
    route_after_traversal,
)
from watchline.fw.narrator  import present_results
from watchline.fw.renderer  import render_dashboard


def build_pipeline():
    """Build and compile the Watchline LangGraph pipeline."""
    builder = StateGraph(WatchlineState)

    builder.add_node("identify_intent",       identify_intent)
    builder.add_node("select_rules",          select_rules)
    builder.add_node("execute_traversal",     execute_traversal)
    builder.add_node("present_results",       present_results)
    builder.add_node("render_dashboard",      render_dashboard)
    builder.add_node("request_clarification", request_clarification)

    builder.add_edge(START, "identify_intent")
    builder.add_edge("identify_intent", "select_rules")

    builder.add_conditional_edges(
        "select_rules",
        route_after_rules,
        {
            "execute_traversal":     "execute_traversal",
            "request_clarification": "request_clarification",
        },
    )

    builder.add_conditional_edges(
        "execute_traversal",
        route_after_traversal,
        {
            "present_results":       "present_results",
            "request_clarification": "request_clarification",
        },
    )

    builder.add_edge("present_results",       "render_dashboard")
    builder.add_edge("render_dashboard",      END)
    builder.add_edge("request_clarification", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        #"Is 122 West 97th Street in Manhattan getting worse?"
        "Who controls 530 East 169th Street in the Bronx?"
    )
    print(f"\nQuestion: {question}\n" + "-" * 60)
    pipeline = build_pipeline()
    result   = pipeline.invoke({"question": question})
    print(result["answer"])
    if result.get("dashboard_html"):
        print(f"\n[Dashboard rendered: {len(result['dashboard_html'])} chars]")
    if result.get("error"):
        print(f"\n[Pipeline error: {result['error']}]")
