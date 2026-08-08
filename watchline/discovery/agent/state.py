"""Session-state capture and lifetime. The memory a multi-turn thread resolves against.

This middleware watches the tool results a turn produces and records the entities
they established into :class:`~watchline.discovery.agent.session.DiscoveryState`,
so a later turn can resolve "he", "that landlord", or "the second one" against
them (reference resolution itself is added in the next group, in ``before_model``).

Two rules this module is built around, both learned the hard way in Phase 1:

* **Both hook forms, always.** ``after_model`` and ``aafter_model`` are
  implemented together — ``langgraph dev`` runs the graph asynchronously, and a
  sync-only hook is silently absent exactly where it matters.
* **Return deltas, never mutate.** Every hook returns a state-delta dict; it
  never mutates ``state`` in place. Graph state is thread-scoped, but subagents
  and parallel turns share the object, so in-place mutation races.

The capture and expiry logic are pure functions taking an explicit ``now``, so
the idle timeout is testable without a real clock.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.config import get_config

from .session import (
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    FOCUS_TYPES,
    SHORT_TERM_SLOTS,
    DiscoveryState,
)

__all__ = [
    "SessionStateMiddleware",
    "session_state",
    "capture",
    "expire_stale_slots",
    "extract_from_payload",
    "idle_timeout_seconds",
    "resolve_references",
]


# -- extraction: a tool payload -> the entities/results it established ----------


def _identified(entity: dict[str, Any], key: str) -> dict[str, Any] | None:
    """An entity dict, but only if it carries a real identifier — never nulls."""
    return entity if entity.get(key) else None


def extract_from_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """What a single tool result establishes, as capture deltas.

    Returns a dict with any of ``focus`` (``{type: entity}``), ``last_result``
    (a list with stable indices), and ``disambiguation`` (a recorded choice
    point). Unknown tools and incomplete payloads yield ``{}`` — capture is
    additive and never guesses.
    """
    focus: dict[str, Any] = {}
    out: dict[str, Any] = {}

    if tool_name == "resolve_address" and payload.get("status") == "resolved":
        building = _identified({"bbl": payload.get("bbl"), "address": payload.get("address")}, "bbl")
        if building:
            focus["building"] = building

    elif tool_name == "resolve_landlord_name":
        if payload.get("status") == "resolved":
            ll = payload.get("landlord") or {}
            landlord = _identified({"actor_id": ll.get("actor_id"), "name": ll.get("name")}, "actor_id")
            if landlord:
                focus["landlord"] = landlord
        elif payload.get("status") == "needs_disambiguation":
            candidates = payload.get("candidates") or []
            if candidates:
                out["last_result"] = {
                    "kind": "landlord_candidates", "tool": tool_name, "items": candidates
                }
                out["disambiguation"] = {"query": payload.get("query"), "candidates": candidates}

    elif tool_name == "deep_investigation" and payload.get("status") == "complete":
        # A Tier-4 report lands in investigation_state (exempt from the idle
        # timeout) so an investigation can resume later. Only the compact,
        # public findings — never partial working state.
        out["investigation"] = {
            "question": payload.get("question"),
            "findings": payload.get("findings"),
            "priority": payload.get("priority"),
            "suggested_focus": payload.get("suggested_focus"),
        }

    elif tool_name == "lookup_building_ownership" and payload.get("found"):
        building = _identified({"bbl": payload.get("bbl"), "address": payload.get("address")}, "bbl")
        if building:
            focus["building"] = building
        controllers = payload.get("apparent_controllers") or []
        # A single controller becomes the focus landlord, so "his other
        # buildings" resolves. Several is ambiguous — leave the landlord focus
        # alone and let the list drive an indexed reference instead.
        if len(controllers) == 1:
            c = controllers[0]
            landlord = _identified({"actor_id": c.get("actor_id"), "name": c.get("name")}, "actor_id")
            if landlord:
                focus["landlord"] = landlord
        if controllers:
            out["last_result"] = {
                "kind": "apparent_controllers", "tool": tool_name, "items": controllers
            }

    if focus:
        out["focus"] = focus
    return out


def _payload_of(message: ToolMessage) -> dict[str, Any] | None:
    """Parse a ToolMessage's content into the tool's dict payload."""
    content = message.content
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None
    return None


def _tool_messages_this_turn(messages: list[Any]) -> list[ToolMessage]:
    """Tool results since the most recent human turn, in chronological order."""
    collected: list[ToolMessage] = []
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            break
        if isinstance(message, ToolMessage):
            collected.append(message)
    collected.reverse()
    return collected


# -- capture and expiry (pure, explicit clock) --------------------------------


def capture(state: dict[str, Any], now: float) -> dict[str, Any]:
    """Fold this turn's tool results into a session-state delta.

    Merges into the existing slots (a bare ``{focus_entities: ...}`` return would
    replace the whole dict and drop other types), stamps touched slots with
    ``now`` for the idle timeout, and returns ``{}`` when nothing was captured.
    """
    tool_messages = _tool_messages_this_turn(state.get("messages", []))
    if not tool_messages:
        return {}

    focus = dict(state.get("focus_entities") or {})
    last_result = state.get("last_result")
    touched = dict(state.get("slot_touched_at") or {})
    history = list(state.get("disambiguation_history") or [])
    investigation = state.get("investigation_state")
    changed = False

    for message in tool_messages:
        payload = _payload_of(message)
        if payload is None:
            continue
        delta = extract_from_payload(getattr(message, "name", "") or "", payload)
        for entity_type, entity in delta.get("focus", {}).items():
            if entity_type in FOCUS_TYPES:
                focus[entity_type] = entity
                touched[entity_type] = now
                touched["focus_entities"] = now
                changed = True
        if "last_result" in delta:
            last_result = delta["last_result"]
            touched["last_result"] = now
            changed = True
        if "disambiguation" in delta:
            history.append(delta["disambiguation"])
            changed = True
        if "investigation" in delta:
            investigation = delta["investigation"]  # not timestamped: exempt
            changed = True

    if not changed:
        return {}
    out: dict[str, Any] = {"focus_entities": focus, "slot_touched_at": touched}
    if last_result is not state.get("last_result"):
        out["last_result"] = last_result
    if history != (state.get("disambiguation_history") or []):
        out["disambiguation_history"] = history
    if investigation is not state.get("investigation_state"):
        out["investigation_state"] = investigation
    return out


def expire_stale_slots(state: dict[str, Any], now: float, timeout: float) -> dict[str, Any]:
    """Clear short-term slots whose last touch is older than ``timeout``.

    Only :data:`SHORT_TERM_SLOTS` expire; ``disambiguation_history`` and any
    future ``investigation_state`` persist. Returns ``{}`` when nothing expired.
    """
    touched = state.get("slot_touched_at") or {}
    remaining = dict(touched)
    out: dict[str, Any] = {}
    for slot in SHORT_TERM_SLOTS:
        stamped = touched.get(slot)
        if stamped is not None and now - stamped > timeout:
            out[slot] = {} if slot == "focus_entities" else None
            remaining.pop(slot, None)
    if out:
        out["slot_touched_at"] = remaining
    return out


def idle_timeout_seconds() -> float:
    """The thread's idle timeout, from config, defaulting to 30 minutes."""
    try:
        config = get_config()
    except Exception:  # noqa: BLE001 - outside a runnable context: use the default
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    configurable = (config or {}).get("configurable") or {}
    value = configurable.get("session_idle_timeout_seconds")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return DEFAULT_IDLE_TIMEOUT_SECONDS


# -- reference resolution (deterministic, before classify/route) --------------

#: Ordinal words → 1-based position, for indexed reference.
_ORDINAL_WORDS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

#: Explicit type words → the focus type they name.
_TYPE_WORDS: dict[str, str] = {
    "landlord": "landlord", "owner": "landlord", "controller": "landlord",
    "building": "building", "property": "building",
    "portfolio": "portfolio",
    "actor": "actor", "party": "actor",
}

#: Bare pronouns → the focus type they most plausibly denote. Personal pronouns
#: denote a party (a landlord/actor); "it" is deliberately excluded as too
#: ambiguous between a building and a party to resolve without guessing.
_PRONOUN_TYPE: dict[str, str] = {
    "he": "landlord", "him": "landlord", "his": "landlord",
    "she": "landlord", "her": "landlord", "hers": "landlord",
    "they": "landlord", "them": "landlord", "their": "landlord", "theirs": "landlord",
}

#: A last_result kind → the focus type its items are.
_KIND_TYPE: dict[str, str] = {
    "landlord_candidates": "landlord",
    "apparent_controllers": "landlord",
}

#: Corrective openers. A correction overwrites the focus slot rather than adding.
_CORRECTION_RE = re.compile(
    r"^\s*(no,?\s|not\s|actually\b|i\s+meant\b|i\s+mean\b|rather\b)", re.IGNORECASE
)

#: An indexed reference needs an explicit ordinal marker — an ordinal word
#: ("second"), an ordinal-suffixed digit ("2nd"), or a "number"/"#" prefix
#: ("number 2", "#2"). A **bare** number is deliberately not one: "115 Broad
#: Street" must never be read as "item 115".
_INDEX_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b"
    r"|\b(\d+)(?:st|nd|rd|th)\b"
    r"|(?:\bnumber\s+|#)(\d+)\b",
    re.IGNORECASE,
)


def _id_and_name(entity_type: str, entity: dict[str, Any]) -> tuple[Any, Any]:
    """The identifier and display name for an entity of ``entity_type``."""
    if entity_type == "building":
        return entity.get("bbl"), entity.get("address")
    if entity_type == "portfolio":
        return entity.get("portfolio_id"), entity.get("name")
    return entity.get("actor_id"), entity.get("name")  # landlord / actor


def _find_index(text: str) -> int | None:
    """A 0-based index from an explicit ordinal phrase, or ``None``."""
    match = _INDEX_RE.search(text)
    if not match:
        return None
    word, ordinal_digit, prefixed_digit = match.group(1), match.group(2), match.group(3)
    if word:
        return _ORDINAL_WORDS[word.lower()] - 1
    if ordinal_digit:
        return int(ordinal_digit) - 1
    if prefixed_digit:
        return int(prefixed_digit) - 1
    return None


def _referenced_type(text: str) -> tuple[str, str] | None:
    """The focus type a demonstrative/pronoun names, plus the matched phrase."""
    words = re.findall(r"[a-z]+", text.lower())
    for word in words:
        if word in _TYPE_WORDS:
            return _TYPE_WORDS[word], word
    for word in words:
        if word in _PRONOUN_TYPE:
            return _PRONOUN_TYPE[word], word
    return None


def resolve_references(
    text: str, focus: dict[str, Any], last_result: dict[str, Any] | None
) -> dict[str, Any]:
    """Resolve one reference in ``text`` deterministically against session state.

    Tried in order: an **indexed** reference into ``last_result`` ("the second
    one"), then a **pronoun / demonstrative** into ``focus`` ("he", "that
    landlord"). Returns a dict with ``resolved_reference`` metadata and, when a
    new entity was selected, a ``focus`` overwrite for that type. Returns ``{}``
    when nothing resolved — never a guess.
    """
    correction = bool(_CORRECTION_RE.match(text or ""))

    # 1. Indexed reference into the last result list.
    index = _find_index(text)
    if index is not None and last_result:
        items = last_result.get("items") or []
        if 0 <= index < len(items):
            entity = items[index]
            entity_type = _KIND_TYPE.get(last_result.get("kind", ""), "landlord")
            identifier, name = _id_and_name(entity_type, entity)
            return {
                "focus": {entity_type: entity},
                "resolved_reference": {
                    "phrase": f"item {index + 1}", "type": entity_type, "via": "indexed",
                    "id": identifier, "name": name, "correction": correction,
                },
            }

    # 2. Pronoun / demonstrative into the typed focus.
    referenced = _referenced_type(text)
    if referenced:
        entity_type, phrase = referenced
        entity = focus.get(entity_type)
        if entity:
            identifier, name = _id_and_name(entity_type, entity)
            return {
                "resolved_reference": {
                    "phrase": phrase, "type": entity_type, "via": "reference",
                    "id": identifier, "name": name, "correction": correction,
                },
            }
    return {}


def _last_human_text(messages: list[Any]) -> str | None:
    """The latest message's text, only if it is the human turn (turn start)."""
    if not messages:
        return None
    last = messages[-1]
    if getattr(last, "type", None) != "human":
        return None
    content = getattr(last, "content", "")
    return content if isinstance(content, str) else str(content)


def _resolution_note(reference: dict[str, Any]) -> HumanMessage:
    """The resolved reference, as a context message the model can act on.

    A ``HumanMessage`` rather than a ``SystemMessage``: the system prompt is
    already set by the persona middleware, and a second, non-consecutive system
    message is rejected by the Anthropic API. Appended right after the user turn,
    it merges with it as one user message.
    """
    named = f" ({reference['name']})" if reference.get("name") else ""
    return HumanMessage(
        f"[session context] The reference \"{reference['phrase']}\" refers to "
        f"{reference['type']} {reference['id']}{named}. Use this identifier when a "
        "tool needs it; do not recompute or recall a value from an earlier turn."
    )


class SessionStateMiddleware(AgentMiddleware[DiscoveryState]):
    """Capture entities, expire stale slots, and resolve references.

    ``before_model`` runs first in the chain (the turn order CLAUDE.md mandates):
    it expires slots idle past the timeout, then resolves a pronoun / indexed /
    demonstrative reference against the surviving state, records the resolution
    as ``resolved_reference`` metadata, and injects it as context so the model
    re-queries precisely rather than recalling a stale value. A correction ("no,
    I meant…") overwrites the focus slot. ``after_model`` captures the turn's
    tool results. Both hook forms are implemented for the async server.
    """

    state_schema = DiscoveryState

    def _before(self, state: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        delta = expire_stale_slots(state, now, idle_timeout_seconds())

        text = _last_human_text(state.get("messages", []))
        if text is None:
            return delta  # mid-loop call, not a turn start — resolve nothing

        # Resolve against state as it stands after expiry.
        focus = {**(state.get("focus_entities") or {})}
        if "focus_entities" in delta:
            focus = dict(delta["focus_entities"])
        last_result = delta["last_result"] if "last_result" in delta else state.get("last_result")

        resolution = resolve_references(text, focus, last_result)
        # resolved_reference reflects the current turn only — set it either way.
        delta["resolved_reference"] = resolution.get("resolved_reference")
        if "focus" in resolution:
            focus.update(resolution["focus"])
            delta["focus_entities"] = focus
            touched = dict(delta.get("slot_touched_at") or state.get("slot_touched_at") or {})
            for entity_type in resolution["focus"]:
                touched[entity_type] = now
            touched["focus_entities"] = now
            delta["slot_touched_at"] = touched
        if resolution.get("resolved_reference"):
            delta["messages"] = [_resolution_note(resolution["resolved_reference"])]
        return delta

    def before_model(self, state, runtime):
        return self._before(state) or None

    async def abefore_model(self, state, runtime):
        return self._before(state) or None

    def after_model(self, state, runtime):
        return capture(state, time.time()) or None

    async def aafter_model(self, state, runtime):
        return capture(state, time.time()) or None


session_state = SessionStateMiddleware()
