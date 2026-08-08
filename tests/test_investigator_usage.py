"""Hermetic tests for the investigator's usage summing/emission (query-cost G3).

The pure token accounting is tested here; that a real deep run actually emits the
event rides the existing ``llm_deep`` progress path.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from watchline.discovery.agent.investigator import PROGRESS_EVENT, _emit_usage, _sum_usage


def _ai(inp, out, details, model="claude-sonnet-5"):
    return NS(type="ai",
              usage_metadata={"input_tokens": inp, "output_tokens": out,
                              "input_token_details": details},
              response_metadata={"model": model})


def test_sum_usage_totals_and_splits_cache_creation():
    msgs = [
        _ai(1000, 100, {"cache_read": 800, "cache_creation": 0,
                        "ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 50}),
        _ai(2000, 200, {"cache_read": 0, "cache_creation": 300}),   # no split → generic is 5m
        NS(type="tool", name="run_cypher", content="{}"),           # no usage → skipped
    ]
    u = _sum_usage(msgs)
    assert u["input"] == 3000 and u["output"] == 300
    assert u["cache_read"] == 800
    assert u["cache_creation_5m"] == 100 + 300
    assert u["cache_creation_1h"] == 50
    assert u["model"] == "claude-sonnet-5"


def test_sum_usage_counts_only_no_content_leak():
    # A message whose content is a raw record must not contribute anything but counts.
    msg = _ai(500, 10, {})
    msg.content = "RAW BLOB THAT MUST NOT LEAK"
    u = _sum_usage([msg])
    assert "RAW BLOB" not in repr(u)
    assert set(u) == {"input", "output", "cache_read",
                      "cache_creation_5m", "cache_creation_1h", "model"}


def test_emit_usage_only_fires_when_nonzero():
    events: list = []
    _emit_usage(events.append, {"messages": [_ai(500, 50, {})]})
    assert len(events) == 1
    assert events[0]["type"] == PROGRESS_EVENT and events[0]["kind"] == "usage"
    assert events[0]["input"] == 500 and events[0]["output"] == 50

    events.clear()
    _emit_usage(events.append, {"messages": []})   # no usage-bearing messages
    _emit_usage(events.append, None)               # no final state at all
    assert events == []
