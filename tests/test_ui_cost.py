"""Hermetic tests for the pure cost accounting (ui/cost.py). No network, no model.

Canned ``usage_metadata`` in the exact shape ``langchain_anthropic`` emits pins the
cache-aware pricing deterministically: reads at 0.10x, 5m writes at 1.25x, 1h
writes at 2.0x, and the full-price remainder as the inclusive total minus cached.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace as NS

import pytest

from watchline.discovery.ui import cost as cost_mod
from watchline.discovery.ui.cost import (
    Usage,
    estimate_cost,
    price_family,
    summary_line,
    usage_from_messages,
)

# Haiku's round $1 / $5 per-1M rate makes the arithmetic easy to read.
HAIKU = "claude-haiku-4-5"


def test_module_imports_no_streamlit_and_no_agent():
    # Pure module: no Streamlit, and no agent import (so it stays cheap to test and
    # doesn't trigger graph construction).
    src = inspect.getsource(cost_mod)
    assert "streamlit" not in src
    assert "watchline.discovery.agent" not in src


def test_uncached_call_prices_input_and_output():
    u = Usage(input_tokens=1000, output_tokens=200, model=HAIKU)
    # (1000 * 1.0 + 200 * 5.0) / 1e6
    assert estimate_cost([u]).usd == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1_000_000)


def test_cache_read_is_billed_at_one_tenth():
    # 800 of 1000 input tokens are cache reads → 200 full-price + 800 * 0.10.
    u = Usage(input_tokens=1000, cache_read=800, model=HAIKU)
    expected = (200 * 1.0 + 800 * 1.0 * 0.10) / 1_000_000
    assert estimate_cost([u]).usd == pytest.approx(expected)


def test_5m_and_1h_writes_use_their_multipliers():
    five = Usage(input_tokens=1000, cache_creation_5m=1000, model=HAIKU)
    assert estimate_cost([five]).usd == pytest.approx((1000 * 1.0 * 1.25) / 1_000_000)

    hour = Usage(input_tokens=1000, cache_creation_1h=1000, model=HAIKU)
    assert estimate_cost([hour]).usd == pytest.approx((1000 * 1.0 * 2.00) / 1_000_000)


def test_price_family_prefix_match_and_fallback(monkeypatch):
    monkeypatch.delenv("WATCHLINE_MODEL", raising=False)
    # A dated model string resolves to its family.
    assert price_family("claude-haiku-4-5-20251001") == (1.00, 5.00)
    assert price_family("claude-sonnet-5") == (2.00, 10.00)
    # Unknown / missing → the configured default's family (sonnet 5).
    assert price_family("some-unknown-model") == (2.00, 10.00)
    assert price_family(None) == (2.00, 10.00)


def _ai(input_tokens, output_tokens, details, model=HAIKU):
    return NS(
        type="ai",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": details,
        },
        response_metadata={"model": model},
    )


def test_usage_from_messages_splits_ttl_and_generic_creation():
    # TTL split present → generic cache_creation is 0 (langchain zeroes it).
    m = _ai(1000, 50, {"cache_read": 800, "cache_creation": 0,
                       "ephemeral_5m_input_tokens": 150, "ephemeral_1h_input_tokens": 50})
    (u,) = usage_from_messages([m])
    assert u.cache_read == 800
    assert u.cache_creation_5m == 150 and u.cache_creation_1h == 50
    assert u.model == HAIKU

    # No split → generic creation counts as 5m.
    m2 = _ai(1000, 0, {"cache_read": 0, "cache_creation": 300})
    (u2,) = usage_from_messages([m2])
    assert u2.cache_creation_5m == 300 and u2.cache_creation_1h == 0


def test_messages_without_usage_are_skipped():
    ai = _ai(100, 10, {})
    tool = NS(type="tool", name="lookup_building_ownership", content="{}")  # no usage_metadata
    human = NS(type="human", content="hi")
    assert len(usage_from_messages([human, ai, tool])) == 1


def test_estimate_folds_in_deep_usage_and_reports_its_share():
    top = Usage(input_tokens=1000, output_tokens=100, model=HAIKU)
    deep = [Usage(input_tokens=5000, output_tokens=800, model=HAIKU),
            Usage(input_tokens=3000, output_tokens=400, model=HAIKU)]
    cost = estimate_cost([top], deep_usages=deep)

    top_usd = (1000 * 1.0 + 100 * 5.0) / 1_000_000
    deep_usd = ((5000 * 1.0 + 800 * 5.0) + (3000 * 1.0 + 400 * 5.0)) / 1_000_000
    assert cost.deep_usd == pytest.approx(deep_usd)
    assert cost.usd == pytest.approx(top_usd + deep_usd)
    # Aggregate token counts span top + deep.
    assert cost.usage.input_tokens == 1000 + 5000 + 3000
    assert cost.usage.output_tokens == 100 + 800 + 400


def test_summary_line_reads_naturally():
    cost = estimate_cost([Usage(input_tokens=3100, output_tokens=240, cache_read=2800, model=HAIKU)])
    line = summary_line(cost)
    assert line.startswith("≈ $")
    assert "est." in line and "3.1k in" in line and "(2.8k cached)" in line and "240 out" in line
    assert "deep investigation" not in line  # no deep portion here

    with_deep = estimate_cost([Usage(input_tokens=100, model=HAIKU)],
                              deep_usages=[Usage(input_tokens=9000, output_tokens=1000, model=HAIKU)])
    assert "incl. deep investigation $" in summary_line(with_deep)
