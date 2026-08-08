"""Capability gating and persona policy. The layer that makes trust real.

``CLAUDE.md`` is unambiguous about where this belongs:

    **Enforce this in the tool-filtering/middleware layer that controls which
    tools the model can even see** — never as a prompt instruction the model
    could be argued out of.

So the gate here removes tools from the request before the model is called. It
does not ask the model to decline, and it does not check inside the tool — in
both of those designs the model still knows the capability exists and can be
talked toward it. The only durable version is the one where the tool is absent.

That matters concretely rather than theoretically: from Phase 5, the Tier-4 deep
agent reads NOV descriptions and raw ACRIS/HPD ``raw_record`` JSON directly. That
is attacker-influenced text arriving in the model's context, so any control
implemented *as prose in the same context* is contestable by construction.

**Two independent layers, same rule.**

1. :class:`TrustGate` filters the tool list on every model call. This is the one
   that matters.
2. :class:`ToolCallGuard` refuses a gated tool at execution time. Unreachable if
   layer 1 works — which is exactly why it is here. It converts a bug in the
   filter from a capability leak into a refusal.

**Sync and async hooks are both implemented, deliberately.** These are
``AgentMiddleware`` subclasses rather than ``@wrap_model_call`` decorated
functions because the decorator registers only the sync hook, and
``langgraph dev`` invokes the graph asynchronously. A decorator-only gate raises
``NotImplementedError`` in the server while every unit test still passes —
which is to say, the control is absent exactly where it matters. Any hook added
here must exist in both forms.

**Trust never comes from the conversation.** It is read from the run config each
turn via :func:`~watchline.discovery.agent.graph.resolve_trust_level`, which fails
closed to ``"public"`` on anything unexpected. Nothing a user, a tool result, or
a ``raw_record`` field says can change it. A caller wanting to elevate trust
starts a new thread.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import get_runtime

from .session import DEFAULT_PERSONA, resolve_persona, resolve_trust_level

logger = logging.getLogger(__name__)

__all__ = [
    "TIER_4_METADATA_KEY",
    "PERSONA_DIRECTIVES",
    "requires_tier_4",
    "visible_tools",
    "TrustGate",
    "ToolCallGuard",
    "PersonaPrompt",
    "trust_gate",
    "tool_call_guard",
    "persona_prompt",
    "build_system_prompt",
    "as_gated_metadata",
    "BASE_SYSTEM_PROMPT",
]

#: Tool metadata key carrying the gate decision. Populated from the tool
#: function's static reliability declaration
#: (:attr:`~watchline.discovery.agent.reliability.Reliability.requires_tier_4`),
#: never hand-written per tool and never a name list. A name list would drift the
#: moment a tool is renamed, and would not notice a new Type III/IV tool at all.
TIER_4_METADATA_KEY = "requires_tier_4"


def requires_tier_4(tool: Any) -> bool:
    """Whether *tool* may only be exposed on a vetted thread.

    Fails **closed**: a tool whose metadata cannot be read is treated as gated.
    An unreadable declaration is a bug, and the safe reading of a bug is to
    withhold capability rather than grant it.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        logger.warning(
            "Tool %r has no readable metadata; treating as Tier-4 gated",
            getattr(tool, "name", tool),
        )
        return True
    if TIER_4_METADATA_KEY not in metadata:
        logger.warning(
            "Tool %r does not declare %s; treating as Tier-4 gated",
            getattr(tool, "name", tool),
            TIER_4_METADATA_KEY,
        )
        return True
    return bool(metadata[TIER_4_METADATA_KEY])


def visible_tools(tools: Iterable[Any], trust_level: str) -> list[Any]:
    """The tools a thread at *trust_level* is entitled to see.

    Pure and hermetically testable — no config lookup, no graph, no model. The
    policy is deliberately simple, because v1's policy *is* simple: Tier 4 is
    blocked for public trust, full stop.
    """
    if trust_level == "vetted":
        return list(tools)
    return [tool for tool in tools if not requires_tier_4(tool)]


#: Only these keys are lifted out of the run context — trust/persona, never
#: anything else the context might carry.
_CONTEXT_KEYS = ("trust_level", "persona")


def _context_to_dict(context: Any) -> dict[str, Any]:
    """The trust/persona fields from a run context (dataclass or dict), if set."""
    if context is None:
        return {}
    if isinstance(context, dict):
        return {k: context[k] for k in _CONTEXT_KEYS if context.get(k) is not None}
    return {k: getattr(context, k) for k in _CONTEXT_KEYS
            if getattr(context, k, None) is not None}


def _ambient_config() -> dict[str, Any]:
    """The run config with the typed run **context** folded into ``configurable``.

    Trust and persona can arrive two ways: ``config["configurable"]`` (programmatic
    callers, tests, the SDK) or the typed run ``context`` (a ``context_schema``
    form, e.g. LangGraph Studio). Fold the context in as a **fallback** —
    ``configurable`` wins — so an explicit ``configurable`` value is never
    overridden by the context defaults, and neither channel bypasses the
    fail-closed :func:`resolve_trust_level` that reads the result. Any failure to
    read the ambient context (e.g. called outside a run) means "no context".
    """
    try:
        configurable = dict((get_config() or {}).get("configurable") or {})
    except Exception:  # noqa: BLE001 - no run config means "unknown"
        configurable = {}
    try:
        context = get_runtime().context
    except Exception:  # noqa: BLE001 - no ambient runtime/context
        context = None
    return {"configurable": {**_context_to_dict(context), **configurable}}


def _trust_from_ambient_config() -> str:
    """Read trust from the running config/context, failing closed on any problem.

    Neither channel can establish trust outside a run, so the answer is
    ``"public"`` — the fail-closed default preserved by :func:`resolve_trust_level`.
    """
    return resolve_trust_level(_ambient_config())


class TrustGate(AgentMiddleware):
    """Remove tools the current thread is not entitled to, before the model call.

    This is the enforcement point. A tool filtered out here is absent from the
    request, so the model cannot call it, cannot be persuaded to call it, and is
    not told it exists.

    Both hooks are implemented because the agent may be driven either way, and a
    gate that only works under ``invoke()`` is not a gate.
    """

    def _filtered(self, request):
        trust_level = _trust_from_ambient_config()
        allowed = visible_tools(request.tools, trust_level)
        withheld = len(request.tools) - len(allowed)
        if withheld:
            logger.info(
                "trust_level=%s: withheld %d Tier-4 tool(s) from the model request",
                trust_level,
                withheld,
            )
        return request.override(tools=allowed)

    def wrap_model_call(self, request, handler):
        return handler(self._filtered(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._filtered(request))


class ToolCallGuard(AgentMiddleware):
    """Refuse a gated tool at execution time.

    Defense in depth. If :class:`TrustGate` is working this never fires, which is
    the point of having it: a filter bug becomes a refusal rather than a
    capability leak.
    """

    def _refusal(self, request) -> str | None:
        if not requires_tier_4(request.tool):
            return None
        if _trust_from_ambient_config() == "vetted":
            return None
        name = getattr(request.tool, "name", "the requested tool")
        logger.error(
            "Tier-4 tool %r reached execution on a non-vetted thread; refusing. "
            "This indicates the tool-visibility filter did not apply.",
            name,
        )
        return (
            f"{name} is not available on this session. Tier-4 investigative "
            "tools require vetted trust, which is set once when the session is "
            "created."
        )

    def wrap_tool_call(self, request, handler):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        refusal = self._refusal(request)
        return refusal if refusal is not None else await handler(request)


#: Instances, ready to pass to ``create_agent(middleware=[...])``.
trust_gate = TrustGate()
tool_call_guard = ToolCallGuard()


#: Persona shapes tone and language register **only**. It never gates capability:
#: a self-declared ``"journalist"`` does not imply ``trust_level: "vetted"``, and
#: nothing in this mapping grants access to anything.
PERSONA_DIRECTIVES: dict[str, str] = {
    "general_public": (
        "Write in plain language for someone with no housing-policy background. "
        "Explain terms like BBL, HPD violation class, and vacate order the first "
        "time they appear. Avoid jargon and abbreviations."
    ),
    "tenant_advocate": (
        "Write for a tenant organizer. Be concrete and practical, and lead with "
        "what is actionable — which conditions are documented, which are open, "
        "and what the record does and does not establish."
    ),
    "journalist": (
        "Write for a reporter who will need to verify and cite every claim. Be "
        "precise about what each record is, which agency it comes from, and "
        "where the record ends and inference begins."
    ),
    "watchdog_agency": (
        "Write for an analyst familiar with NYC housing data. Technical terms and "
        "field names are fine without explanation; be precise and concise."
    ),
}

#: Behavioural rules that hold regardless of persona. Deliberately short: the
#: guarantees that matter are structural — caveats are attached by
#: :mod:`.reliability`, capability is gated by :func:`trust_gate` — and prose is
#: the weakest place to put a rule. This describes how to *present* what the
#: tools return; it is not what makes any of it true.
BASE_SYSTEM_PROMPT = """You answer questions about NYC housing conditions and \
ownership accountability, grounded in the public record held in the \
watchline-discovery graph.

Ground every factual claim in a tool result. If no tool can answer, say so \
rather than answering from memory — an ungrounded answer is worse than no answer \
here, because it is indistinguishable from a cited one.

When reporting who owns a building, always give both answers the tool returns, \
clearly distinguished: the recorded owner filed with the Department of Finance, \
and the apparent controller inferred by the graph. Never merge them, never pick \
one silently, and never describe an inference as ownership. A building with no \
apparent controller is a normal, common result — report the recorded owner and \
say plainly that the graph has no apparent controller for it.

Never state or imply a legal determination of ownership or control. Pass through \
the caveat text attached to tool results rather than paraphrasing it away."""


def build_system_prompt() -> str:
    """Base rules plus the persona's register.

    Persona is read from the run config/context, like trust, and defaults to
    plain-language framing when absent or unrecognized — never from
    conversation state, for the same reason trust never is.
    """
    persona = resolve_persona(_ambient_config())
    directive = PERSONA_DIRECTIVES.get(persona, PERSONA_DIRECTIVES[DEFAULT_PERSONA])
    return f"{BASE_SYSTEM_PROMPT}\n\n{directive}"


class PersonaPrompt(AgentMiddleware):
    """Set the system prompt from the base rules and the thread's persona.

    A subclass rather than ``@dynamic_prompt`` for the same reason as the gate:
    the decorator registers only the sync hook, and the server runs async.
    """

    def _with_prompt(self, request):
        return request.override(system_prompt=build_system_prompt())

    def wrap_model_call(self, request, handler):
        return handler(self._with_prompt(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._with_prompt(request))


persona_prompt = PersonaPrompt()


def as_gated_metadata(declaration: Any) -> dict[str, bool]:
    """Build tool metadata from a static reliability declaration.

    Used when constructing LangChain tools so the gate reads the declaration
    rather than a name list. Keeping this derivation in one place is what makes
    validation 4.3 meaningful: drop ``requires_tier_4`` from a tool's declaration
    and it becomes visible at public trust, proving the gate consults the tag.
    """
    return {TIER_4_METADATA_KEY: bool(getattr(declaration, "requires_tier_4", True))}
