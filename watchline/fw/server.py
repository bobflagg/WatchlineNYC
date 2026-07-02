import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from watchline.fw.explorer import build_agent, ProvenanceTracker           # DeedWatch deep agent (messages in, streamed tokens out)
from watchline.fw.investigator import build_pipeline  # Watchline pipeline (question in, answer out)

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
    "identify_intent": "Identifying intent",
    "select_rules": "Selecting traversal rules",
    "execute_traversal": "Querying the knowledge graph",
    "present_results": "Composing the answer",
    "request_clarification": "Preparing a clarification",
}


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
                        "type": "tool_start",
                        "name": _INVESTIGATOR_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "input": message if node == "identify_intent" else None,
                    })

            # Node end -> close the step, and if it produced the answer, send it.
            elif kind == "on_chain_end":
                node = event.get("name", "")
                if node in _INVESTIGATOR_NODE_LABELS:
                    out = event["data"].get("output") or {}
                    note = None
                    if isinstance(out, dict):
                        # Surface a resolved BBL or traversal type as the step result.
                        tr = out.get("traversal_results") or {}
                        if isinstance(tr, dict) and tr.get("resolved_building"):
                            rb = tr["resolved_building"]
                            note = f"Resolved {rb.get('address')} (BBL {rb.get('bbl')})"
                        elif isinstance(tr, dict) and tr.get("traversal_type"):
                            note = tr["traversal_type"]
                    yield sse({
                        "type": "tool_end",
                        "name": _INVESTIGATOR_NODE_LABELS[node],
                        "run_id": event["run_id"],
                        "output": note or "done",
                    })

                    # Emit the final answer as a single token block when ready.
                    if isinstance(out, dict) and out.get("answer") and not answer_emitted:
                        yield sse({"type": "token",
                                   "content": content_to_text(out["answer"])})
                        answer_emitted = True

        # Fallback: if no node surfaced an answer (shouldn't happen), say so.
        if not answer_emitted:
            yield sse({"type": "error",
                       "message": "The pipeline finished without producing an answer."})
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
    """Stream from a named graph: 'deedwatch' or 'investigator'."""
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
    """History is only meaningful for the persisted DeedWatch graph."""
    graph = state["deedwatch"]
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    return {
        "messages": [
            {"type": m.type, "content": content_to_text(m.content)}
            for m in snapshot.values.get("messages", [])
        ]
    }
