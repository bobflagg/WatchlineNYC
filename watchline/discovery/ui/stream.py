"""Pure glue between the agent's stream and the UI (v1.0, UI-5).

Maps ``agent.stream(..., stream_mode=["messages","updates","custom"])`` onto typed
UI events and extracts the **sanitized** evidence behind an answer. No Streamlit
import — this is where the logic lives so it is hermetically testable; the app
file only renders these events.

Observed stream shapes (verified against the live agent):

* ``("messages", (chunk, metadata))`` — Anthropic content is a *list of blocks*;
  ``{"type":"text","text":...}`` blocks from the ``model`` node are answer tokens.
  ``tool_use``/``input_json_delta`` blocks are tool-call construction — skipped.
* ``("updates", {node: delta})`` — the ``model`` node's delta carries the complete
  ``AIMessage`` (with ``tool_calls``); ``tools`` carries the ``ToolMessage`` (the
  structured payload); middleware nodes carry ``resolved_reference`` / ``last_result``.
* ``("custom", {...})`` — ``investigation_progress`` events from a deep run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .cost import Cost, Usage, estimate_cost, usage_from_messages

__all__ = [
    "Token", "ToolStart", "ToolResult", "Answer", "Evidence",
    "run_turn", "extract_evidence", "to_markdown", "web_search_note", "display_safe",
]

#: A ``$`` not already backslash-escaped. Streamlit's markdown renders ``$…$`` as
#: KaTeX math, so a report full of dollar amounts renders as garbled TeX.
_UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")


def display_safe(text: str) -> str:
    """Escape ``$`` so Streamlit renders literal dollars, not KaTeX math.

    Render-boundary only — the stored transcript and the downloaded Markdown keep
    raw ``$`` (other renderers don't do inline math, and a ``.md`` should read
    naturally). Touches only ``$``; headers, bold, and lists still render."""
    return _UNESCAPED_DOLLAR.sub(r"\\$", text or "")


def web_search_note(count: int) -> str:
    """The panel/export line when web searches ran but returned no usable sources."""
    return f"Web searches performed: {count} (no sources returned)"

#: Tool-call args worth surfacing in a one-line summary — identifiers and the
#: model-authored query, never a result body.
_SUMMARY_KEYS = ("bbl", "actor_id", "portfolio_id", "borough", "source_name",
                 "event_type", "status", "violation_class", "query", "name")


# --------------------------------------------------------------------------- #
# Typed UI events
# --------------------------------------------------------------------------- #

@dataclass
class Token:
    """A slice of the streamed answer text."""
    text: str


@dataclass
class ToolStart:
    """A tool call began. ``depth`` 0 is the top-level agent; ≥1 is inside a deep
    investigation."""
    name: str
    summary: str = ""
    depth: int = 0


@dataclass
class ToolResult:
    """A tool call returned. ``detail`` is a size/summary, never a raw body."""
    name: str
    detail: str = ""
    depth: int = 0


@dataclass
class Evidence:
    """The sanitized basis for an answer — what the panel shows."""
    caveats: list[dict] = field(default_factory=list)     # {tool, element, text}
    citations: list[dict] = field(default_factory=list)   # {tool, source_name?, run_id?}
    web_sources: list[dict] = field(default_factory=list)  # {title?, url?, ...}
    web_searches: int = 0                                  # web searches performed this turn
    resolved_reference: dict | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.caveats or self.citations or self.web_sources
                    or self.web_searches or self.resolved_reference)


@dataclass
class Answer:
    """Terminal event: the authoritative final text and its evidence."""
    text: str
    evidence: Evidence


# --------------------------------------------------------------------------- #
# Small helpers (pure)
# --------------------------------------------------------------------------- #

def _text_from_content(content: Any) -> str:
    """Answer text from a message's content (Anthropic blocks or a plain string)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _summarize_args(args: dict[str, Any] | None) -> str:
    parts = []
    for key in _SUMMARY_KEYS:
        value = (args or {}).get(key)
        if value:
            text = " ".join(str(value).split())
            parts.append(f"{key}={text[:50]}" + ("…" if len(text) > 50 else ""))
    return ", ".join(parts)


def _payload(content: Any) -> dict | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            obj = json.loads(content)
        except (ValueError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None
    return None


def _result_detail(content: Any) -> str:
    payload = _payload(content)
    if payload is None:
        return ""
    for key in ("row_count", "count", "member_count", "building_count"):
        if isinstance(payload.get(key), int):
            return f"{payload[key]} row(s)"
    if payload.get("found") is False:
        return "not found"
    for value in payload.values():
        if isinstance(value, list):
            return f"{len(value)} item(s)"
    return "ok"


def _find_run_id(payload: dict) -> str | None:
    if payload.get("run_id"):
        return payload["run_id"]
    for controller in payload.get("apparent_controllers") or []:
        run_id = (controller.get("provenance") or {}).get("run_id")
        if run_id:
            return run_id
    for portfolio in payload.get("portfolios") or []:
        if portfolio.get("run_id"):
            return portfolio["run_id"]
    return (payload.get("provenance") or {}).get("run_id")


def _final_answer(messages: list) -> str:
    """The last assistant message that is prose, not a tool call."""
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai" and not getattr(message, "tool_calls", None):
            text = _text_from_content(getattr(message, "content", None))
            if text.strip():
                return text
    return ""


# --------------------------------------------------------------------------- #
# Evidence extraction
# --------------------------------------------------------------------------- #

def extract_evidence(messages: list, resolved_reference: dict | None) -> Evidence:
    """Pull the sanitized evidence from a turn's tool results.

    Only names, caveat text, source/run provenance, and web-source snippets are
    surfaced — never a raw ``raw_record`` or a full result body.
    """
    caveats: list[dict] = []
    citations: list[dict] = []
    web_sources: list[dict] = []
    web_searches = 0
    seen_caveat: set[tuple] = set()
    seen_cite: set[tuple] = set()

    for message in messages:
        if getattr(message, "type", None) != "tool":
            continue
        payload = _payload(getattr(message, "content", None))
        if not payload:
            continue
        tool = getattr(message, "name", None) or "tool"

        for caveat in (payload.get("reliability") or {}).get("caveats") or []:
            # Caveat text is canonical per graph element (caveats.py), so dedupe by
            # (element, text) — the same caveat surfaced by two tools shows once.
            key = (caveat.get("element"), caveat.get("text"))
            if caveat.get("text") and key not in seen_caveat:
                seen_caveat.add(key)
                caveats.append({"tool": tool, "element": caveat.get("element"),
                                "text": caveat.get("text")})

        source_name = payload.get("source_name")
        run_id = _find_run_id(payload)
        if source_name or run_id:
            key = (tool, source_name, run_id)
            if key not in seen_cite:
                seen_cite.add(key)
                citations.append({"tool": tool, "source_name": source_name, "run_id": run_id})

        if tool == "deep_investigation":
            for citation in payload.get("citations") or []:
                inner = citation.get("tool")
                key = ("deep_investigation", inner, None)
                if inner and key not in seen_cite:
                    seen_cite.add(key)
                    citations.append({"tool": f"deep_investigation → {inner}",
                                      "source_name": None, "run_id": None})
            web_sources.extend(payload.get("web_sources") or [])
            web_searches += payload.get("web_search_count") or 0

    return Evidence(caveats=caveats, citations=citations, web_sources=web_sources,
                    web_searches=web_searches, resolved_reference=resolved_reference or None)


# --------------------------------------------------------------------------- #
# Markdown export (pure) — the copy/download document
# --------------------------------------------------------------------------- #

def to_markdown(question: str, answer: str, evidence: Evidence | None) -> str:
    """A self-contained Markdown record of a turn: the question, the answer, and
    its evidence. Used by the UI's copy/download control."""
    lines = ["# Watchline NYC — Discovery", ""]
    if question:
        lines += [f"**Question:** {question}", ""]
    lines += [(answer or "").strip() or "_(no answer returned)_", ""]

    if evidence and not evidence.is_empty:
        lines.append("## Evidence")
        rr = evidence.resolved_reference
        if rr:
            lines.append(
                f"- **Resolved reference:** {rr.get('type')} `{rr.get('id')}` "
                f"(via {rr.get('via')})")
        if evidence.citations:
            lines += ["", "### Citations (graph-verified)"]
            for c in evidence.citations:
                bits = [f"`{c['tool']}`"]
                if c.get("source_name"):
                    bits.append(f"source **{c['source_name']}**")
                if c.get("run_id"):
                    bits.append(f"run `{c['run_id']}`")
                lines.append("- " + " · ".join(bits))
        if evidence.caveats:
            lines += ["", "### Caveats"]
            for c in evidence.caveats:
                lines.append(f"- _{c['element']}_ — {c['text']}")
        if evidence.web_sources:
            lines += ["", "### Web sources (lower confidence, never treated as ownership)"]
            for w in evidence.web_sources:
                title = w.get("title") or w.get("url") or "source"
                url = w.get("url")
                lines.append(f"- [{title}]({url})" if url else f"- {title}")
        elif evidence.web_searches:
            lines += ["", "### Web sources (lower confidence, never treated as ownership)",
                      f"- {web_search_note(evidence.web_searches)}"]
        lines.append("")

    lines += ["---", "_Generated by Watchline NYC — Discovery._"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The stream → UI events generator
# --------------------------------------------------------------------------- #

def run_turn(agent, text: str, config: dict) -> Iterator[Token | ToolStart | ToolResult | Answer | Cost]:
    """Stream one turn, yielding UI events live, then an ``Answer`` and a ``Cost``.

    ``Cost`` is terminal (strictly after ``Answer``): it is summed from the
    ``AIMessage``\\ s collected off the ``updates`` stream, which carry
    ``usage_metadata``. A Tier-4 investigation's internal usage never reaches the
    parent stream, so it arrives separately as a ``kind:"usage"`` custom event and
    is folded in via ``deep_usages`` (populated in the ``custom`` branch)."""
    messages: list = []
    seen: set[int] = set()
    resolved_reference: dict | None = None
    tokens: list[str] = []
    deep_usages: list = []

    for mode, payload in agent.stream(
        {"messages": [{"role": "user", "content": text}]},
        config=config,
        stream_mode=["messages", "updates", "custom"],
    ):
        if mode == "messages":
            chunk, metadata = payload
            if (metadata or {}).get("langgraph_node") == "model":
                piece = _text_from_content(getattr(chunk, "content", None))
                if piece:
                    tokens.append(piece)
                    yield Token(piece)

        elif mode == "updates":
            for _node, delta in (payload or {}).items():
                if not delta:
                    continue
                if "resolved_reference" in delta:
                    resolved_reference = delta["resolved_reference"]
                for message in delta.get("messages") or []:
                    if id(message) in seen:
                        continue
                    seen.add(id(message))
                    messages.append(message)
                    for call in getattr(message, "tool_calls", None) or []:
                        yield ToolStart(call.get("name", "tool"),
                                        _summarize_args(call.get("args")), depth=0)
                    if getattr(message, "type", None) == "tool":
                        yield ToolResult(getattr(message, "name", "") or "tool",
                                         _result_detail(getattr(message, "content", None)), depth=0)

        elif mode == "custom":
            if isinstance(payload, dict) and payload.get("type") == "investigation_progress":
                kind = payload.get("kind")
                depth = (payload.get("depth") or 0) + 1  # nest under the deep call
                if kind in ("tool_call", "web_search"):
                    yield ToolStart(payload.get("tool") or kind,
                                    payload.get("summary") or "", depth=depth)
                elif kind == "tool_result":
                    row_count = payload.get("row_count")
                    detail = f"{row_count} row(s)" if row_count is not None else ""
                    yield ToolResult(payload.get("tool") or "tool", detail, depth=depth)
                elif kind == "truncated":
                    yield ToolResult("investigation", "reached step limit", depth=depth)
                elif kind == "usage":
                    # A Tier-4 run's own token usage (counts only); folded into the
                    # turn Cost so the estimate includes the deep investigation.
                    deep_usages.append(Usage(
                        input_tokens=payload.get("input") or 0,
                        output_tokens=payload.get("output") or 0,
                        cache_read=payload.get("cache_read") or 0,
                        cache_creation_5m=payload.get("cache_creation_5m") or 0,
                        cache_creation_1h=payload.get("cache_creation_1h") or 0,
                        model=payload.get("model") or "",
                    ))

    answer = _final_answer(messages) or "".join(tokens)
    yield Answer(answer, extract_evidence(messages, resolved_reference))
    yield estimate_cost(usage_from_messages(messages), deep_usages=deep_usages)
