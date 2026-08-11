"""Headless AppTest for the Streamlit UI — deterministic, no model, no graph.

``build_agent`` is stubbed to a scripted stream, so the whole flow (submit →
progress → answer → evidence), the trust toggle reaching the run config, and the
reset are verified without a live agent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "watchline" / "discovery" / "ui" / "app.py")


@pytest.fixture(autouse=True)
def _clear_resource_cache():
    # get_agent is @st.cache_resource; clear it so each test gets the freshly
    # stubbed build_agent rather than a cached fake from a previous test. Also
    # snapshot os.environ: the API-key gate writes keys into it directly (not via
    # monkeypatch), so restore it afterwards to keep tests from leaking keys.
    st.cache_resource.clear()
    env_snapshot = dict(os.environ)
    yield
    st.cache_resource.clear()
    os.environ.clear()
    os.environ.update(env_snapshot)


def _scripted_chunks():
    ai_call = NS(type="ai", content=[],
                 tool_calls=[{"name": "lookup_building_ownership",
                              "args": {"bbl": "1000050010"}, "id": "1"}])
    tool_msg = NS(type="tool", name="lookup_building_ownership", content=json.dumps({
        "found": True,
        "apparent_controllers": [{"name": "PETER HUNGERFORD", "provenance": {"run_id": "run-9"}}],
        "reliability": {"type": "II", "caveats": [
            {"element": "apparent_control", "text": "Apparent control is inferred, not a legal finding."}]},
    }))
    final = NS(type="ai", tool_calls=[],
               content=[{"type": "text",
                         "text": "The apparent controller is PETER HUNGERFORD; the AG settlement was $8M."}],
               usage_metadata={"input_tokens": 3200, "output_tokens": 180,
                               "input_token_details": {"cache_read": 2800}},
               response_metadata={"model": "claude-haiku-4-5"})
    return [
        ("updates", {"model": {"messages": [ai_call]}}),
        ("updates", {"tools": {"messages": [tool_msg]}}),
        ("updates", {"model": {"messages": [final]}}),
    ]


def _scripted_investigation_chunks():
    """Like _scripted_chunks, but the top-level agent calls the Tier-4
    ``deep_investigation`` tool — so the turn is flagged as an investigation and
    earns the right-hand report panel."""
    ai_call = NS(type="ai", content=[],
                 tool_calls=[{"name": "deep_investigation",
                              "args": {"query": "Investigate the portfolio"}, "id": "1"}])
    tool_msg = NS(type="tool", name="deep_investigation", content=json.dumps({
        "report": "PETER HUNGERFORD apparently controls the portfolio.",
        "citations": [{"tool": "lookup_building_ownership", "run_id": "run-9"}],
        "reliability": {"type": "III", "caveats": [
            {"element": "apparent_control", "text": "Apparent control is inferred, not a legal finding."}]},
    }))
    final = NS(type="ai", tool_calls=[],
               content=[{"type": "text",
                         "text": "The apparent controller is PETER HUNGERFORD; the AG settlement was $8M."}],
               usage_metadata={"input_tokens": 3200, "output_tokens": 180,
                               "input_token_details": {"cache_read": 2800}},
               response_metadata={"model": "claude-haiku-4-5"})
    return [
        ("updates", {"model": {"messages": [ai_call]}}),
        ("updates", {"tools": {"messages": [tool_msg]}}),
        ("updates", {"model": {"messages": [final]}}),
    ]


def _stub_agent(monkeypatch, captured: list, chunks_fn=_scripted_chunks):
    class _Agent:
        def stream(self, inputs, config=None, stream_mode=None):
            captured.append(config)
            return iter(chunks_fn())

    monkeypatch.setattr("watchline.discovery.agent.graph.build_agent",
                        lambda checkpointer=None: _Agent())


def test_turn_renders_answer_and_evidence(monkeypatch):
    _stub_agent(monkeypatch, [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Who owns BBL 1000050010?").run()

    assert not at.exception
    assert len(at.chat_message) == 2                        # user + assistant
    assert any("PETER HUNGERFORD" in (m.value or "") for m in at.markdown)
    assert any("Evidence" in e.label for e in at.expander)  # the evidence panel
    assert len(at.status) >= 1                              # the progress panel


def test_report_panel_offers_download_and_markdown(monkeypatch):
    # The report panel appears only for investigations.
    _stub_agent(monkeypatch, [], chunks_fn=_scripted_investigation_chunks)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Investigate landlord ACT-LL-42357").run()

    # The right-hand report panel: HTML download + Markdown source (behind an expander).
    labels = [b.label for b in at.download_button]
    assert "Download" in labels                                  # the report download (relabeled)
    assert any("Download Markdown (.md)" in ell for ell in labels)
    assert any("Markdown source" in e.label for e in at.expander)
    md = " ".join(getattr(c, "value", "") or "" for c in at.code)
    assert "# Watchline NYC" in md and "PETER HUNGERFORD" in md


def test_plain_lookup_shows_no_report_panel(monkeypatch):
    # A Tier 1-3 lookup stays full-width — no artifact panel.
    _stub_agent(monkeypatch, [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Who owns BBL 1000050010?").run()

    assert not at.exception
    assert "Download" not in [b.label for b in at.download_button]
    assert not any("Markdown source" in e.label for e in at.expander)


def test_artifact_card_open_and_close(monkeypatch):
    # A fresh investigation auto-opens its report; closing returns to full-width but
    # leaves a reopenable card in the chat.
    _stub_agent(monkeypatch, [], chunks_fn=_scripted_investigation_chunks)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Investigate landlord ACT-LL-42357").run()
    assert "Download" in [b.label for b in at.download_button]      # auto-opened

    at.session_state["open_artifact"] = None                        # close the panel
    at.run()
    assert "Download" not in [b.label for b in at.download_button]   # back to full-width
    assert any(b.label == "Open report" for b in at.button)         # card can reopen it


def test_artifact_expand_toggles_full_width(monkeypatch):
    # The expand button fills the main panel with the artifact; collapse restores the
    # split. Closing resets the expanded state.
    _stub_agent(monkeypatch, [], chunks_fn=_scripted_investigation_chunks)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Investigate landlord ACT-LL-42357").run()
    assert at.session_state["artifact_expanded"] is False           # opens split

    [b for b in at.button if b.label == "⤢"][0].click()             # expand
    at.run()
    assert at.session_state["artifact_expanded"] is True
    assert "Download" in [b.label for b in at.download_button]       # artifact still rendered

    [b for b in at.button if b.label == "⤡"][0].click()             # collapse
    at.run()
    assert at.session_state["artifact_expanded"] is False

    at.session_state["open_artifact"] = None                         # close resets expand
    at.run()
    assert at.session_state["artifact_expanded"] is False


def _cluster_artifact():
    def c(name, buildings):
        return {"name": name, "buildings": buildings, "residential_units": 1,
                "rent_stabilized_units": 1, "records": [{"actor_id": "ACT-LL-1", "buildings": buildings}],
                "name_edges": [], "events": []}
    return {"c1": {
        "kind": "operator_cluster", "question": "Top hidden operators",
        "clusters": {7: c("SCOTT CASTELLANO", 356), 9: c("DIVYA RASHAD", 239)},
        "leaderboard": [
            {"componentId": 7, "operator": "SCOTT CASTELLANO", "buildings": 356, "records": 5, "distinct_names": 1},
            {"componentId": 9, "operator": "DIVYA RASHAD", "buildings": 239, "records": 13, "distinct_names": 1}],
        "selected": 7}}


def test_operator_cluster_artifact_renders(monkeypatch):
    # A typed operator-cluster artifact renders the network panel (not the report panel).
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["artifacts"] = _cluster_artifact()
    at.session_state["open_artifact"] = "c1"
    at.run()

    assert not at.exception
    assert any("Download network" in b.label for b in at.download_button)   # the network panel
    body = " ".join(m.value or "" for m in at.markdown)
    assert "SCOTT CASTELLANO" in body                                        # the selected (marked) row


def test_operator_cluster_renders_expanded(monkeypatch):
    # Expanded, the graph is centred by wrapping it in a fixed-width container inside a
    # centre-aligned parent — exercise that path so it renders without error.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["artifacts"] = _cluster_artifact()
    at.session_state["open_artifact"] = "c1"
    at.session_state["artifact_expanded"] = True
    at.run()

    assert not at.exception
    assert any("Download network" in b.label for b in at.download_button)


def test_operator_cluster_row_click_switches(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["artifacts"] = _cluster_artifact()
    at.session_state["open_artifact"] = "c1"
    at.run()

    # #7 is selected (a marker, not a button); #9 (Rashad) is a clickable row.
    [b for b in at.button if "DIVYA RASHAD" in (b.label or "")][0].click()
    at.run()
    assert at.session_state["artifacts"]["c1"]["selected"] == 9


def test_operator_cluster_lazy_events(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("watchline.discovery.analytics.operators.operator_events",
                        lambda ids: [{"event_type": "Complaint", "events": 42}])
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["artifacts"] = _cluster_artifact()
    at.session_state["open_artifact"] = "c1"
    at.run()

    btn = [b for b in at.button if "event fingerprint" in (b.label or "").lower()]
    assert btn                                                   # offered before load
    btn[0].click()
    at.run()
    assert at.session_state["artifacts"]["c1"]["clusters"][7]["events"] == [
        {"event_type": "Complaint", "events": 42}]              # loaded + cached


def test_cost_caption_renders_after_a_turn(monkeypatch):
    _stub_agent(monkeypatch, [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Who owns BBL 1000050010?").run()

    captions = " ".join(getattr(c, "value", "") or "" for c in at.caption)
    assert "est." in captions                 # the cost line rendered
    assert "cached" in captions               # 2800 cache_read → "(2.8k cached)"


def test_dollar_signs_escaped_on_screen_but_raw_in_download(monkeypatch):
    """Streamlit renders $…$ as KaTeX; a report full of dollar amounts must show
    literal dollars. Escaped at the render boundary only — the downloadable
    Markdown keeps raw $ (other renderers don't do inline math)."""
    _stub_agent(monkeypatch, [], chunks_fn=_scripted_investigation_chunks)  # code block is in the panel
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Investigate landlord ACT-LL-42357").run()

    rendered = " ".join(m.value or "" for m in at.markdown)
    assert "\\$8M" in rendered            # escaped → literal dollar, no math

    md = " ".join(getattr(c, "value", "") or "" for c in at.code)
    assert "$8M" in md and "\\$8M" not in md   # download stays raw


def test_evidence_shows_caveat_and_run_provenance(monkeypatch):
    _stub_agent(monkeypatch, [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Who owns BBL 1000050010?").run()

    body = " ".join(m.value or "" for m in at.markdown)
    assert "inferred, not a legal finding" in body   # the caveat text
    assert "run-9" in body                            # the detection run provenance


def test_trust_toggle_reaches_the_run_config(monkeypatch):
    captured: list = []
    _stub_agent(monkeypatch, captured)
    at = AppTest.from_file(APP, default_timeout=30).run()

    at.session_state["trust_level"] = "vetted"        # flip the sidebar control
    at.chat_input[0].set_value("anything").run()

    assert captured, "agent.stream should have been called"
    assert captured[-1]["configurable"]["trust_level"] == "vetted"


def test_new_chat_resets_the_transcript(monkeypatch):
    _stub_agent(monkeypatch, [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("Who owns BBL 1000050010?").run()
    assert len(at.session_state["messages"]) == 2

    at.sidebar.button[0].click().run()                # "New chat"
    assert at.session_state["messages"] == []


def test_missing_anthropic_key_blocks_with_setup_form(monkeypatch):
    # Neutralise .env loading and remove the key: the gate must block the chat.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30).run()

    assert not at.exception
    assert len(at.chat_input) == 0                                 # chat is blocked
    labels = [ti.label or "" for ti in at.text_input]
    assert any("Anthropic API key" in ell for ell in labels)      # setup form shown


def test_providing_anthropic_key_unblocks(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert len(at.chat_input) == 0                                 # gated at first

    at.text_input[0].set_value("sk-ant-test")                     # the Anthropic field
    at.button[0].click()                                          # "Continue"
    at.run()

    assert not at.exception
    assert len(at.chat_input) >= 1                                 # gate released


def test_missing_tavily_shows_web_search_disabled(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")        # present → no hard gate
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30).run()

    assert not at.exception
    assert len(at.chat_input) >= 1                                 # non-blocking
    warnings = " ".join(getattr(w, "value", "") or "" for w in at.warning)
    assert "Web search is disabled" in warnings


def test_library_imports_no_streamlit():
    """A clean interpreter importing the agent pulls in no Streamlit (UI-6)."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import watchline.discovery.agent, watchline.discovery.agent.graph, sys; "
         "assert 'streamlit' not in sys.modules"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
