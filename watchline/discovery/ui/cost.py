"""Per-turn LLM cost accounting (pure — no Streamlit, no agent import).

The estimator turns the ``usage_metadata`` that rides every ``AIMessage`` into a
**cache-aware** dollar estimate. It is pure and hermetically testable, like
``ui/stream.py``; the app file only renders what this returns.

Token accounting (verified against ``langchain_anthropic._create_usage_metadata``):

* ``usage_metadata.input_tokens`` is the **inclusive total** — base (full-price)
  plus cache reads plus cache-creation. The full-price remainder is therefore
  ``input_tokens − cache_read − cache_creation``.
* ``input_token_details`` breaks out ``cache_read`` and, when Anthropic reports the
  TTL split, ``ephemeral_5m_input_tokens`` / ``ephemeral_1h_input_tokens`` (the
  generic ``cache_creation`` is zeroed in that case to avoid double counting).
* ``None``-valued detail keys are dropped, so every read is ``.get(...) or 0``.

Pricing is cache-aware: reads bill at 0.10x, 5-minute writes at 1.25x, 1-hour
writes at 2.0x of the model's input rate. A naive ``input_tokens × rate`` would
over-bill cached reads tenfold — the whole point of this module.

**This is an estimate.** Prices are a maintained table (see ``PRICES``); Anthropic
billing / LangSmith remain authoritative. The UI labels the figure "est.".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = [
    "Usage", "Cost", "PRICES", "DEFAULT_MODEL",
    "price_family", "usage_from_messages", "estimate_cost", "summary_line",
]

#: The model this stack defaults to (mirrors ``graph.MODEL_ID`` — kept as a local
#: constant so this module imports nothing from the agent and stays cheap to test).
DEFAULT_MODEL = "claude-sonnet-5"

#: Effective input/output price per 1M tokens, keyed by model **family** (a prefix
#: of the model string the API returns). An estimate, not billing truth.
#:
#: ⚠️ MAINTENANCE: Sonnet 5 is on **intro pricing ($2 / $10)** through
#: **2026-08-31**; after that it reverts to **$3 / $15**. Update this row then.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.00, 10.00),     # intro through 2026-08-31 → (3.00, 15.00)
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4": (5.00, 25.00),
}

#: Cache-control price multipliers on the input rate (model-independent).
CACHE_READ_MULT = 0.10
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.00


@dataclass
class Usage:
    """One model call's token counts. ``input_tokens`` is the inclusive total."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation_5m: int = 0
    cache_creation_1h: int = 0
    model: str = ""


@dataclass
class Cost:
    """A turn's aggregated usage and its estimated cost.

    ``deep_usd`` is the portion attributable to a Tier-4 deep investigation, so the
    UI can call it out; it is already included in ``usd``.
    """
    usage: Usage = field(default_factory=Usage)
    usd: float = 0.0
    deep_usd: float = 0.0


def price_family(model: str | None) -> tuple[float, float]:
    """The (input, output) per-1M rate for *model*, by longest-prefix family match.

    Falls back to the configured ``WATCHLINE_MODEL`` (then :data:`DEFAULT_MODEL`)
    when *model* is missing or unrecognized — an estimate should degrade to a
    sensible rate, never crash.
    """
    name = model or os.environ.get("WATCHLINE_MODEL") or DEFAULT_MODEL
    for family in sorted(PRICES, key=len, reverse=True):
        if name.startswith(family):
            return PRICES[family]
    # Unknown model string: try the configured default's family, else DEFAULT_MODEL.
    configured = os.environ.get("WATCHLINE_MODEL") or DEFAULT_MODEL
    for family in sorted(PRICES, key=len, reverse=True):
        if configured.startswith(family):
            return PRICES[family]
    return PRICES[DEFAULT_MODEL]


def _model_of(message) -> str:
    meta = getattr(message, "response_metadata", None) or {}
    return meta.get("model") or meta.get("model_name") or ""


def usage_from_messages(messages) -> list[Usage]:
    """A :class:`Usage` for every message that carries ``usage_metadata``.

    Messages without usage (human turns, tool results, streaming partials) are
    skipped rather than counted as zero — a zero would still price at $0, but
    skipping keeps the per-call list honest.
    """
    out: list[Usage] = []
    for message in messages:
        um = getattr(message, "usage_metadata", None)
        if not um:
            continue
        details = um.get("input_token_details") or {}
        cache_read = details.get("cache_read") or 0
        # Generic creation is zeroed by langchain when the TTL split is present, so
        # summing generic + split never double-counts. Generic (no split) → 5m.
        cc_generic = details.get("cache_creation") or 0
        cc_5m = (details.get("ephemeral_5m_input_tokens") or 0) + cc_generic
        cc_1h = details.get("ephemeral_1h_input_tokens") or 0
        out.append(Usage(
            input_tokens=um.get("input_tokens") or 0,
            output_tokens=um.get("output_tokens") or 0,
            cache_read=cache_read,
            cache_creation_5m=cc_5m,
            cache_creation_1h=cc_1h,
            model=_model_of(message),
        ))
    return out


def _cost_of(u: Usage) -> float:
    in_rate, out_rate = price_family(u.model)
    base_input = max(u.input_tokens - u.cache_read - u.cache_creation_5m - u.cache_creation_1h, 0)
    micro = (
        base_input * in_rate
        + u.cache_read * in_rate * CACHE_READ_MULT
        + u.cache_creation_5m * in_rate * CACHE_WRITE_5M_MULT
        + u.cache_creation_1h * in_rate * CACHE_WRITE_1H_MULT
        + u.output_tokens * out_rate
    )
    return micro / 1_000_000


def _aggregate(usages: list[Usage]) -> Usage:
    if not usages:
        return Usage(model=os.environ.get("WATCHLINE_MODEL") or DEFAULT_MODEL)
    models = {u.model for u in usages if u.model}
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cache_read=sum(u.cache_read for u in usages),
        cache_creation_5m=sum(u.cache_creation_5m for u in usages),
        cache_creation_1h=sum(u.cache_creation_1h for u in usages),
        model=next(iter(models)) if len(models) == 1 else ("mixed" if models else ""),
    )


def estimate_cost(usages, *, deep_usages=()) -> Cost:
    """Aggregate token usage and estimate the turn's cost, cache-aware.

    ``usages`` are the top-level model calls; ``deep_usages`` are a Tier-4
    investigation's internal calls (surfaced separately because they never reach
    the parent stream). Both are priced and summed; ``deep_usd`` reports the
    investigation's share.
    """
    top = list(usages)
    deep = list(deep_usages)
    total = sum(_cost_of(u) for u in top + deep)
    deep_usd = sum(_cost_of(u) for u in deep)
    return Cost(usage=_aggregate(top + deep), usd=total, deep_usd=deep_usd)


def _k(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def summary_line(cost: Cost) -> str:
    """A compact one-line cost caption for the UI."""
    u = cost.usage
    in_part = f"{_k(u.input_tokens)} in"
    if u.cache_read:
        in_part += f" ({_k(u.cache_read)} cached)"
    line = f"≈ ${cost.usd:.4f} est. · {in_part} / {_k(u.output_tokens)} out"
    if cost.deep_usd > 0:
        line += f" · incl. deep investigation ${cost.deep_usd:.4f}"
    return line
