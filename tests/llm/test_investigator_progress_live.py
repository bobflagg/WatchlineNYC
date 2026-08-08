"""Live progress-streaming check for the Tier-4 investigation (``llm_deep``).

Streams the **top-level** agent on a vetted thread over a scoped one-building deep
query and asserts sanitized ``investigation_progress`` events arrive on the
``custom`` channel *before* the final report — the exact path a UI (e.g.
Streamlit) consumes. One real deep run (Sonnet by default); opt-in, excluded from
a routine ``-m llm`` pass. Structural assertions only, never prose.
"""

from __future__ import annotations

import json

import pytest

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.agent.investigator import PROGRESS_EVENT

pytestmark = pytest.mark.llm_deep


def test_top_level_stream_surfaces_sanitized_investigation_progress():
    agent = build_agent()
    config = {"configurable": {"trust_level": "vetted", "thread_id": "prog-live-1"}}
    prompt = (
        "Use your deep_investigation capability for a short case file on BBL "
        "2028100045 (231 Echo Place, Bronx): open hazardous violations and any "
        "active vacate orders, and who apparently controls it. Keep it to this "
        "one building."
    )

    progress: list[dict] = []
    report_complete = False

    for mode, data in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
        stream_mode=["custom", "updates"],
    ):
        if mode == "custom" and isinstance(data, dict) and data.get("type") == PROGRESS_EVENT:
            progress.append(data)
        elif mode == "updates" and isinstance(data, dict):
            for update in data.values():
                for message in (update or {}).get("messages", []) or []:
                    if getattr(message, "name", None) == "deep_investigation":
                        content = getattr(message, "content", None)
                        payload = json.loads(content) if isinstance(content, str) else content
                        if isinstance(payload, dict) and payload.get("status") == "complete":
                            report_complete = True

    # The investigation surfaced its internal steps, sanitized.
    kinds = {event["kind"] for event in progress}
    assert kinds & {"tool_call", "tool_result"}, f"no progress events surfaced: {progress[:3]}"
    for event in progress:
        assert event["type"] == PROGRESS_EVENT
        assert not any(key in event for key in ("result", "content", "rows", "events"))
    # And it still produced a complete report.
    assert report_complete, "the deep investigation did not complete"
