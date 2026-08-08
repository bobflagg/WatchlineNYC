"""Session context: trust level and persona, read from the run config.

A session **is** a LangGraph thread — ``CLAUDE.md`` is explicit that there is no
separate session concept, and a new conversation is just a new ``thread_id``.
What this module owns is the two values a calling application sets once at
thread start, as ``configurable`` fields on the run config.

``trust_level`` gates capability; ``persona`` shapes tone and never gates
anything. Both are read from the config on every turn and are **never inferred
from conversation content** — nothing a user says, and nothing arriving in a
tool result or a ``raw_record`` field, can change them. A caller wanting to
elevate trust starts a new thread.

This lives apart from :mod:`.graph` so that :mod:`.middleware` can read session
context without importing the graph that the middleware is itself part of.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args

from langchain.agents.middleware import AgentState
from langchain_core.runnables import RunnableConfig
from typing_extensions import NotRequired

__all__ = [
    "TrustLevel",
    "VALID_TRUST_LEVELS",
    "DEFAULT_TRUST_LEVEL",
    "Persona",
    "VALID_PERSONAS",
    "DEFAULT_PERSONA",
    "DiscoveryContext",
    "resolve_trust_level",
    "resolve_persona",
    "DiscoveryState",
    "FOCUS_TYPES",
    "SHORT_TERM_SLOTS",
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
]

#: The entity types tracked for pronoun / demonstrative resolution. One slot per
#: type, holding the most-recently-established entity of that type — so "he" and
#: "that landlord" resolve to the last landlord, independently of the last
#: building. Kept typed rather than a single "last entity" so a building
#: reference cannot shadow a landlord reference (CLAUDE.md, Session State).
FOCUS_TYPES: frozenset[str] = frozenset({"building", "landlord", "portfolio", "actor"})

#: Slots that expire on the short-term idle timeout. ``disambiguation_history``
#: and any future ``investigation_state`` are deliberately excluded — an
#: investigation may resume days later (CLAUDE.md).
SHORT_TERM_SLOTS: tuple[str, ...] = ("focus_entities", "working_set", "last_result")

#: Default idle timeout for the short-term slots. Overridable per thread via
#: ``configurable.session_idle_timeout_seconds``.
DEFAULT_IDLE_TIMEOUT_SECONDS: float = 30 * 60


class DiscoveryState(AgentState):
    """Session state carried across turns of a thread (P2-4).

    A session **is** a LangGraph thread, so this state lives in the graph's own
    state and is checkpointed by whatever checkpointer the runtime supplies —
    there is no separate session store. Every field is ``NotRequired``: a fresh
    thread starts with none of them, and the capture middleware fills them in.

    The slots, from CLAUDE.md's Session State section:

    * ``focus_entities`` — the most-recently-established entity per type, for
      pronoun / demonstrative resolution.
    * ``working_set`` — the current *implicit* scoped collection an aggregation
      or filter turn operates over.
    * ``comparison_set`` — a small *explicit* named list the user asked to
      compare. Distinct from ``working_set``; never summed.
    * ``last_result`` — the most recent result list with stable indices, for
      indexed reference ("the second one").
    * ``thread_mode`` — lightweight lookup vs. an active Tier-4 investigation.
    * ``disambiguation_history`` — ambiguous name→entity choices already made.
    * ``slot_touched_at`` — per-slot last-touch timestamps, for the idle timeout.
    * ``resolved_reference`` — metadata on what the current turn resolved, so a
      caller can show "interpreting 'he' as…". Set each turn, so it reflects the
      current turn only.
    * ``investigation_state`` — the most recent Tier-4 investigation's report and
      findings. **Exempt from the idle timeout** (not in ``SHORT_TERM_SLOTS``):
      an investigation may reasonably resume days later.
    """

    focus_entities: NotRequired[dict[str, Any]]
    working_set: NotRequired[dict[str, Any] | None]
    comparison_set: NotRequired[list[Any]]
    last_result: NotRequired[dict[str, Any] | None]
    thread_mode: NotRequired[str]
    disambiguation_history: NotRequired[list[dict[str, Any]]]
    slot_touched_at: NotRequired[dict[str, float]]
    resolved_reference: NotRequired[dict[str, Any] | None]
    investigation_state: NotRequired[dict[str, Any] | None]

# Trust levels recognized by the library. Anything else — missing, malformed,
# misspelled, or a value invented mid-conversation — resolves to "public".
TrustLevel = Literal["public", "vetted"]
VALID_TRUST_LEVELS: frozenset[str] = frozenset({"public", "vetted"})
DEFAULT_TRUST_LEVEL: TrustLevel = "public"

# Persona shapes tone and language register only. It never gates capability:
# a self-declared "journalist" does not imply vetted trust.
Persona = Literal["general_public", "tenant_advocate", "journalist", "watchdog_agency"]
VALID_PERSONAS: frozenset[str] = frozenset(get_args(Persona))
DEFAULT_PERSONA: Persona = "general_public"


@dataclass
class DiscoveryContext:
    """Typed run **context** for the agent — what a caller sets once per thread.

    Declared as the agent's ``context_schema`` so LangGraph Studio renders
    ``trust_level`` / ``persona`` as fields (dropdowns, from the ``Literal``
    types). Values set this way arrive as the run **context**; the middleware
    also accepts the classic ``config["configurable"]`` form (which wins), so both
    Studio and programmatic callers work. Neither channel can escalate trust past
    the fail-closed :func:`resolve_trust_level`.
    """

    trust_level: TrustLevel = DEFAULT_TRUST_LEVEL
    persona: Persona = DEFAULT_PERSONA


def resolve_trust_level(config: RunnableConfig | None) -> TrustLevel:
    """Read ``trust_level`` from the run config, failing closed to ``public``.

    Fails closed on a missing key, a non-string value, or an unrecognized
    string. Trust is set once at thread start and is never inferred or
    upgraded from anything said mid-thread; a caller wanting to elevate trust
    starts a new thread.

    Consumed by the tool-filtering layer in :mod:`.middleware`. It is
    deliberately not a prompt instruction — a model can be argued out of a
    prompt.
    """
    configurable: dict[str, Any] = (config or {}).get("configurable") or {}
    candidate = configurable.get("trust_level")
    if isinstance(candidate, str) and candidate in VALID_TRUST_LEVELS:
        return candidate  # type: ignore[return-value]
    return DEFAULT_TRUST_LEVEL


def resolve_persona(config: RunnableConfig | None) -> str:
    """Read ``persona`` from the run config, defaulting to plain-language.

    Unlike trust, an unrecognized persona is not a security concern — it just
    falls back to general-public framing.
    """
    configurable: dict[str, Any] = (config or {}).get("configurable") or {}
    candidate = configurable.get("persona")
    if isinstance(candidate, str) and candidate in VALID_PERSONAS:
        return candidate
    return DEFAULT_PERSONA
