import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from watchline.fw.explorer import build_agent, ProvenanceTracker           # DeedWatch deep agent (messages in, streamed tokens out)
from watchline.fw.investigator import build_pipeline  # Watchline pipeline (question in, answer out)
from watchline.discovery.agent.pipeline import build_pipeline as build_explore_pipeline  # Discovery Explore pipeline (question in, Lead out)

state = {}


def content_to_text(content) -> str:
    """Normalize LangChain message content to a plain string.

    OpenAI models stream/store content as a `str`. Anthropic (ChatAnthropic)
    uses a list of content blocks, e.g.:
        [{"type": "text", "text": "..."}]
    and during streaming may also emit non-text blocks (tool_use deltas,
    thinking deltas) that carry no displayable text. We keep only text and
    join it, so every client receives a clean string.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in ("text", "text_delta", None):
                    parts.append(block.get("text", ""))
                # tool_use / thinking / input_json_delta blocks: skip
        return "".join(parts)
    return str(content)


@asynccontextmanager
async def lifespan(app):
    async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as cp:
        # DeedWatch: multi-turn deep agent, persisted via the sqlite checkpointer.
        tracker = ProvenanceTracker()
        state["deedwatch"] = build_agent(tracker, cp)
        # Investigator: single-shot pipeline, no checkpointer / no memory.
        state["investigator"] = build_pipeline()
        # Discovery Explore: single-shot pipeline, but checkpointed -- a
        # session's full state (including explore_trace, the complete
        # tool-call log) is persisted keyed by session_id, satisfying
        # Charter Principle 18's transparency requirement durably rather
        # than only in-memory for the duration of one request.
        state["explore"] = build_explore_pipeline(checkpointer=cp)
        yield
    # connection closes automatically on shutdown


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    thread_id: str


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# --------------------------------------------------------------------------- #
# DeedWatch deep agent  -- token streaming + tool events
# --------------------------------------------------------------------------- #
async def deedwatch_events(message: str, thread_id: str):
    graph = state["deedwatch"]
    # The config passed here overrides build_graph's .with_config(); set
    # recursion_limit explicitly so it doesn't fall back to the default 25.
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50,
    }
    inputs = {"messages": [HumanMessage(content=message)]}

    try:
        async for event in graph.astream_events(inputs, config, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                text = content_to_text(event["data"]["chunk"].content)
                if text:
                    yield sse({"type": "token", "content": text})
            elif kind == "on_tool_start":
                name = event["name"]
                node = event["metadata"].get("langgraph_node", "")
                yield sse({
                    "type": "tool_start",
                    "name": name,
                    "run_id": event["run_id"],
                    "input": event["data"].get("input"),
                    "subagent": node if "explorer" in node else None,
                })
            elif kind == "on_tool_end":
                yield sse({"type": "tool_end", "name": event["name"],
                           "run_id": event["run_id"],
                           "output": str(event["data"].get("output"))})
    except Exception as e:
        yield sse({"type": "error", "message": str(e)})
    yield sse({"type": "done"})


# --------------------------------------------------------------------------- #
# Investigator pipeline  -- node-level progress + final answer
# --------------------------------------------------------------------------- #
# This graph differs from DeedWatch in three ways that change how we stream:
#   1. Input key is `question` (a str), not `messages`.
#   2. The answer lives in state["answer"]; it is produced by .invoke() inside
#      a node, so there are no streamed model tokens to forward.
#   3. No checkpointer / no multi-turn memory -- thread_id is ignored here.
# So we stream node-completion events for progress (which also drive the
# client's collapsible activity panel) and emit the answer once when the
# answer-producing node finishes.
_INVESTIGATOR_NODE_LABELS = {
    "identify_intent":       "Identifying intent",
    "select_rules":          "Selecting traversal rules",
    "execute_traversal":     "Querying the knowledge graph",
    "present_results":       "Composing the answer",
    "render_dashboard":      "Rendering dashboard",
    "request_clarification": "Preparing a clarification",
}


def _investigator_note(node: str, out: dict) -> str | None:
    """Extract a human-readable one-line summary from a node's output dict."""
    if not isinstance(out, dict):
        return None

    if node == "identify_intent":
        intent   = out.get("intent") or {}
        category = intent.get("intent_category", "")
        entity   = intent.get("entity_raw") or intent.get("actor_name") or ""
        if not category:
            return None
        return f"{category} · {entity}" if entity else category

    elif node in ("select_rules", "execute_traversal"):
        tr  = out.get("traversal_results") or {}
        if not isinstance(tr, dict):
            return None
        re_ = tr.get("resolved_entity") or {}
        tt  = tr.get("traversal_type", "")
        raw = tr.get("raw_results") or []
        rc  = len(raw) if isinstance(raw, list) else 0

        if re_.get("bbl"):
            addr = re_.get("address", "—")
            bbl  = re_["bbl"]
            note = f"Resolved: {addr} (BBL {bbl})"
            if rc:
                note += f" · {rc} record{'s' if rc != 1 else ''}"
            return note
        if re_.get("canonical_id"):
            note = f"Actor: {re_.get('display_name', '—')}"
            if rc:
                note += f" · {rc} record{'s' if rc != 1 else ''}"
            return note
        return tt or None

    elif node == "render_dashboard":
        return "Dashboard ready"

    return None


async def investigator_events(message: str, thread_id: str):
    graph = state["investigator"]
    inputs = {"question": message}
    answer_emitted = False

    try:
        async for event in graph.astream_events(inputs, version="v2"):
            kind = event["event"]

            # Node start -> a progress step the client can show in its panel.
            if kind == "on_chain_start":
                node = event.get("name", "")
                if node in _INVESTIGATOR_NODE_LABELS:
                    yield sse({
                        "type":   "tool_start",
                        "name":   _INVESTIGATOR_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "input":  None,
                    })

            # Node end -> close the step, and if it produced the answer, send it.
            elif kind == "on_chain_end":
                node = event.get("name", "")
                if node in _INVESTIGATOR_NODE_LABELS:
                    out  = event["data"].get("output") or {}
                    note = _investigator_note(node, out)
                    yield sse({
                        "type":   "tool_end",
                        "name":   _INVESTIGATOR_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "output": note,
                    })

                    # Emit the dashboard HTML when render_dashboard finishes.
                    # The dashboard Summary tab is the answer -- no plain-text
                    # token stream is emitted for the investigator pipeline.
                    # Base64-encoded to guarantee the JSON payload is safe
                    # regardless of embedded quotes or special characters.
                    if node == "render_dashboard" and isinstance(out, dict):
                        dashboard_html = out.get("dashboard_html")
                        if dashboard_html:
                            import base64
                            yield sse({
                                "type":     "dashboard",
                                "encoding": "base64",
                                "html":     base64.b64encode(
                                                dashboard_html.encode("utf-8")
                                            ).decode("ascii"),
                            })
                            answer_emitted = True

                    # Clarification path: no dashboard, surface the text answer.
                    elif node == "request_clarification" and isinstance(out, dict):
                        if out.get("answer") and not answer_emitted:
                            yield sse({"type": "token",
                                       "content": content_to_text(out["answer"])})
                            answer_emitted = True

        # Fallback: pipeline finished without a dashboard or clarification.
        if not answer_emitted:
            yield sse({"type": "error",
                       "message": "The pipeline finished without producing a dashboard."})
    except Exception as e:
        yield sse({"type": "error", "message": str(e)})
    yield sse({"type": "done"})


# --------------------------------------------------------------------------- #
# Discovery Explore pipeline -- node-level progress + a Lead (not a dashboard)
# --------------------------------------------------------------------------- #
# Same shape as investigator_events (question in, no streamed model tokens --
# explore_loop's internal agent.invoke() call is synchronous, so the whole
# node is one opaque step, not a token stream). Two real differences:
#   1. Four nodes, not six, and no clarification path -- see pipeline.py's
#      module docstring for why Explore has no identify_intent/clarification
#      gate.
#   2. The terminal artifact is a "lead" event (lead_id + the LeadProposal
#      dict) instead of a rendered HTML dashboard -- Explore mode has no
#      renderer.py equivalent in Phase 1 (design doc §9: the "investigate in
#      evidentiary" affordance is a Streamlit-side concern, task 5.9).
# thread_id IS meaningful here, unlike investigator -- it's passed through as
# session_id and is also the checkpointer's key (see build_explore_pipeline
# in lifespan()).
_EXPLORE_NODE_LABELS = {
    "resolve_entity": "Resolving entity",
    "explore_loop":   "Investigating (bounded agentic search)",
    "propose_lead":   "Synthesizing findings into a Lead",
    "persist_lead":   "Validating and writing the Lead",
}


def _explore_note(node: str, out: dict) -> str | None:
    """Extract a human-readable one-line summary from a node's output dict."""
    if not isinstance(out, dict):
        return None

    if node == "resolve_entity":
        entity = out.get("resolved_entity")
        if entity:
            label = entity.get("address") or entity.get("name") or entity.get("bbl")
            return f"Resolved: {label}"
        return "No confident match -- handing off to the Explore agent"

    elif node == "explore_loop":
        if out.get("error"):
            return None
        trace = out.get("explore_trace") or []
        return f"{len(trace)} tool call{'s' if len(trace) != 1 else ''} made"

    elif node == "propose_lead":
        proposal = out.get("lead_proposal")
        if not proposal:
            return None
        return f"{proposal.get('suggested_intent')} · {proposal.get('priority')} priority"

    elif node == "persist_lead":
        if out.get("lead_id"):
            return f"Lead written: {out['lead_id']}"
        return None

    return None


async def explore_events(message: str, thread_id: str):
    graph = state["explore"]
    inputs = {"question": message, "session_id": thread_id}
    config = {"configurable": {"thread_id": thread_id}}
    lead_emitted = False
    # astream_events' per-node "output" is that node's own return value only,
    # not the accumulated graph state -- persist_lead returns just
    # {"lead_id": ...}, not lead_proposal (that came from the earlier
    # propose_lead node). Track it here rather than widening persist_lead's
    # return contract for the SSE layer's convenience.
    captured_lead_proposal = None

    try:
        async for event in graph.astream_events(inputs, config, version="v2"):
            kind = event["event"]

            if kind == "on_chain_start":
                node = event.get("name", "")
                if node in _EXPLORE_NODE_LABELS:
                    yield sse({
                        "type":   "tool_start",
                        "name":   _EXPLORE_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "input":  None,
                    })

            elif kind == "on_chain_end":
                node = event.get("name", "")
                if node in _EXPLORE_NODE_LABELS:
                    out  = event["data"].get("output") or {}
                    note = _explore_note(node, out)
                    yield sse({
                        "type":   "tool_end",
                        "name":   _EXPLORE_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "output": note,
                    })

                    if not isinstance(out, dict):
                        continue

                    if node == "propose_lead" and out.get("lead_proposal"):
                        captured_lead_proposal = out["lead_proposal"]

                    # persist_lead succeeded -- the Lead is the answer.
                    # validated_targets (kind/id/label) is persist_lead's own
                    # output, unlike lead_proposal's raw ids -- it's what the
                    # UI's "investigate in evidentiary" hand-off (task 5.9)
                    # needs, since only Building.bbl is safe to hand off
                    # directly (Reconciliation Principle 3).
                    if node == "persist_lead" and out.get("lead_id"):
                        yield sse({
                            "type":             "lead",
                            "lead_id":          out["lead_id"],
                            "lead_proposal":    captured_lead_proposal,
                            "validated_targets": out.get("validated_targets"),
                        })
                        lead_emitted = True

                    # An error from any node (resolve_entity never sets one,
                    # but explore_loop/propose_lead/persist_lead all can --
                    # see pipeline.py's conditional edges) ends the session.
                    elif out.get("error") and not lead_emitted:
                        yield sse({"type": "error", "message": out["error"]})
                        lead_emitted = True

        if not lead_emitted:
            yield sse({"type": "error",
                       "message": "The Explore pipeline finished without producing a Lead."})
    except Exception as e:
        yield sse({"type": "error", "message": str(e)})
    yield sse({"type": "done"})


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
# Dispatch table: one stream generator per graph.
_GRAPHS = {
    "deedwatch": deedwatch_events,
    "investigator": investigator_events,
    "explore": explore_events,
}


@app.post("/stream")
async def stream(req: ChatRequest):
    """DeedWatch deep agent (default, multi-turn)."""
    return StreamingResponse(
        deedwatch_events(req.message, req.thread_id),
        media_type="text/event-stream",
    )


@app.post("/stream/{graph_name}")
async def stream_named(graph_name: str, req: ChatRequest):
    """Stream from a named graph: 'deedwatch', 'investigator', or 'explore'."""
    generator = _GRAPHS.get(graph_name)
    if generator is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown graph '{graph_name}'. Available: {list(_GRAPHS)}",
        )
    return StreamingResponse(
        generator(req.message, req.thread_id),
        media_type="text/event-stream",
    )


@app.get("/history/{thread_id}")
async def history(thread_id: str):
    """
    Message history for the persisted DeedWatch graph specifically -- this
    endpoint's shape (a `messages` list) doesn't generalize to `explore`,
    which is also checkpointed (task 5.8) but has no `messages` key in its
    state (ExploreState has resolved_entity/explore_trace/lead_proposal/...
    instead). Inspecting a past Explore session means reading that
    checkpoint's ExploreState directly, not this endpoint -- a natural
    follow-up, not yet built.
    """
    graph = state["deedwatch"]
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    return {
        "messages": [
            {"type": m.type, "content": content_to_text(m.content)}
            for m in snapshot.values.get("messages", [])
        ]
    }
