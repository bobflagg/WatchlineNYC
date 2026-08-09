"""WatchlineNYC Discovery — Streamlit UI (v1.0).

Run:  uv run streamlit run watchline/discovery/ui/app.py

An in-process conversational UI over the discovery agent: multi-turn chat, a live
progress panel (top-level tools and deep-investigation steps), a token-streamed
answer, and an Evidence panel of the sanitized structure behind it (citations,
reliability caveats, resolved reference, web sources). All stream parsing lives in
``ui/stream.py``; this file only renders its events.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.ui import report, sidebar
from watchline.discovery.ui.cost import Cost, summary_line
from watchline.discovery.ui.stream import (
    Answer, ToolResult, ToolStart, Token, display_safe, run_turn, to_markdown, web_search_note,
)

st.set_page_config(page_title="Watchline NYC — Discovery", page_icon="⚖️", layout="wide")

# Load .env explicitly so the API-key gate below sees configured keys regardless
# of import order (connections.py also loads it, as an import side-effect).
load_dotenv()


@st.cache_resource
def get_agent():
    """Build the agent once per server process (UI-1), with in-process memory."""
    return build_agent(checkpointer=InMemorySaver())


# --- state (initialised in one place) ---
st.session_state.setdefault("thread_id", str(uuid.uuid4()))
st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_evidence", None)
st.session_state.setdefault("last_turn", None)


_BRAND_HEADER = (
    '<div style="background:#0a1629;border-radius:10px;border-left:4px solid #d4a017;'
    'padding:1rem 1.2rem;margin-bottom:0.6rem;">'
    '<div style="font-size:0.66rem;letter-spacing:0.26em;text-transform:uppercase;'
    'color:#d4a017;font-weight:600;">Accountability infrastructure for NYC housing</div>'
    '<div style="font-size:1.7rem;font-weight:700;color:#ffffff;line-height:1.15;">'
    'Watchline NYC — Discovery</div></div>'
)


def _render_setup_and_stop() -> None:
    """Setup screen shown when ``ANTHROPIC_API_KEY`` is absent (UI key gate).

    The agent can't run without an Anthropic key, so this blocks the app until one
    is provided. The Tavily key is offered here too, but it is optional. A key
    entered here lives only in this server process for the session — the caption
    points at ``.env`` for a permanent setup — and nothing is written to disk."""
    st.html(_BRAND_HEADER)
    st.markdown("#### Set up API keys")
    st.markdown(
        "This app needs an **Anthropic API key** to run. A **Tavily API key** is "
        "optional — it enables web search during deep investigations."
    )
    anthropic_key = st.text_input(
        "Anthropic API key (required)", type="password", key="_anthropic_key_input")
    tavily_key = st.text_input(
        "Tavily API key (optional — enables web search)", type="password", key="_tavily_key_input")

    if st.button("Continue", type="primary", key="_apikey_continue"):
        if anthropic_key.strip():
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key.strip()
        if tavily_key.strip():
            os.environ["TAVILY_API_KEY"] = tavily_key.strip()
        if os.environ.get("ANTHROPIC_API_KEY"):
            st.rerun()
        else:
            st.error("An Anthropic API key is required — the app can't continue without it.")

    st.caption(
        "Keys are held only in this server process for the current session. To set "
        "them permanently, add them to your `.env` file."
    )
    st.stop()


def _render_web_search_notice() -> None:
    """Non-blocking notice when ``TAVILY_API_KEY`` is absent: web search is disabled
    (deep investigations still run on the graph), with an inline field to add it."""
    st.warning(
        "Web search is disabled — no Tavily API key is set. Deep investigations will "
        "run on the graph only.", icon="🔎")
    with st.expander("Add a Tavily API key to enable web search"):
        tavily_key = st.text_input("Tavily API key", type="password", key="_tavily_inline_input")
        if st.button("Enable web search", key="_tavily_enable"):
            if tavily_key.strip():
                os.environ["TAVILY_API_KEY"] = tavily_key.strip()
                st.rerun()
            else:
                st.caption("Enter a Tavily API key, or continue without web search.")


def _pending_sample(selected: str) -> str | None:
    """Return a freshly-chosen sample once, so it submits a single time."""
    if selected and selected != "—" and selected != st.session_state.get("_last_sample"):
        st.session_state["_last_sample"] = selected
        return selected
    return None


def _open_report_in_new_tab(html: str) -> None:
    """A button that opens the branded HTML report in a new browser tab, via a
    client-side ``blob:`` URL (Streamlit's component iframe allows popups). Works
    both locally and on the deployed stack; Download is the guaranteed fallback.
    ``</`` is neutralised so nothing in the report can break out of the script."""
    payload = json.dumps(html).replace("</", "<\\/")
    st.iframe(
        f"""
        <a id="wl-open" href="#" target="_blank" rel="noopener"
           style="display:inline-flex;align-items:center;justify-content:center;width:100%;
                  box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                  background:#0a1629;color:#fff;text-decoration:none;padding:.5rem 1rem;
                  border:1px solid #d4a017;border-radius:.5rem;font-size:.9rem;font-weight:600;">
          ↗&nbsp;&nbsp;Open report in a new tab</a>
        <script>
          const blob = new Blob([{payload}], {{type: "text/html"}});
          document.getElementById("wl-open").href = URL.createObjectURL(blob);
        </script>
        """,
        height=52,
    )


def _render_report_panel(turn) -> None:
    """Right-hand artifact panel: the branded HTML report rendered inline, isolated
    in its own iframe so its page-level CSS can't touch the app. Download and
    open-in-new-tab sit above it; the Markdown source is one expander down. Shows the
    latest result, with a placeholder before the first one."""
    st.markdown("#### Report")
    if turn is None:
        st.caption("Run a query — the formatted, shareable report will appear here.")
        return
    kw = dict(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cost=turn.get("cost"),
        model=(turn["cost"].usage.model if turn.get("cost") else None),
        trust_level=turn.get("trust_level"),
    )
    args = (turn["question"], turn["answer"], turn["evidence"])
    # Standalone artifact keeps the branding; the in-app preview drops it (the brand
    # already lives in the sidebar).
    html_branded = report.to_html(*args, branded=True, **kw)
    html_preview = report.to_html(*args, branded=False, **kw)
    st.download_button(
        "⬇  Download report (.html)", html_branded, file_name="watchline-report.html",
        mime="text/html", width="stretch", key="download_html")
    _open_report_in_new_tab(html_branded)
    st.iframe(html_preview, height=760)
    with st.expander("Markdown source"):
        markdown = to_markdown(turn["question"], turn["answer"], turn["evidence"])
        st.download_button(
            "Download Markdown (.md)", markdown, file_name="watchline-result.md",
            mime="text/markdown", key="download_md")
        st.code(markdown, language="markdown")


def _render_evidence(evidence) -> None:
    with st.expander("Evidence — what this answer rests on", expanded=False):
        rr = evidence.resolved_reference
        if rr:
            st.markdown(
                f"**Resolved reference** — read a reference as {rr.get('type')} "
                f"`{rr.get('id')}` (via {rr.get('via')})."
            )
        if evidence.citations:
            st.markdown("**Citations** · graph-verified")
            for c in evidence.citations:
                bits = [f"`{c['tool']}`"]
                if c.get("source_name"):
                    bits.append(f"source **{c['source_name']}**")
                if c.get("run_id"):
                    bits.append(f"run `{c['run_id']}`")
                st.markdown("- " + " · ".join(bits))
        if evidence.caveats:
            st.markdown("**Caveats** · what the record does and does not establish")
            for c in evidence.caveats:
                st.markdown(f"- _{c['element']}_ — {c['text']}")
        if evidence.web_sources:
            st.markdown("**Web sources** · lower confidence, never treated as ownership")
            for w in evidence.web_sources:
                title = w.get("title") or w.get("url") or "source"
                url = w.get("url")
                st.markdown(f"- [{title}]({url})" if url else f"- {title}")
        elif evidence.web_searches:
            st.markdown("**Web sources** · lower confidence, never treated as ownership")
            st.markdown(f"- {web_search_note(evidence.web_searches)}")


def _render_turn(agent, prompt: str, config: dict):
    """Stream one turn: progress panel + token-streamed answer.

    Returns ``(text, evidence, cost)``. ``cost`` is the terminal ``Cost`` event; it
    is persisted and rendered from ``last_turn`` (like the Evidence panel), so it
    survives reruns rather than living only in this live pass."""
    status = st.status("Working…", expanded=True)
    placeholder = st.empty()
    answer, steps, evidence, cost = "", 0, None, None

    for event in run_turn(agent, prompt, config):
        if isinstance(event, Token):
            answer += event.text
            placeholder.markdown(display_safe(answer) + " ▌")
        elif isinstance(event, ToolStart):
            steps += 1
            prefix = "↳ " if event.depth else ""   # deep-investigation sub-step
            line = f"{prefix}\U0001f527 **{event.name}**"
            if event.summary:
                line += f" · {event.summary}"
            status.markdown(line)
        elif isinstance(event, ToolResult):
            if event.detail:
                prefix = "↳ " if event.depth else ""
                status.markdown(f"{prefix}&nbsp;&nbsp;→ {event.detail}")
        elif isinstance(event, Answer):
            evidence = event.evidence
            answer = event.text or answer
        elif isinstance(event, Cost):
            cost = event

    placeholder.markdown(display_safe(answer) or "_(no answer returned)_")
    status.update(label=f"Done · {steps} step(s)", state="complete", expanded=False)
    return answer, evidence, cost


# --- API-key gate: the agent can't run without an Anthropic key (blocks here) ---
if not os.environ.get("ANTHROPIC_API_KEY"):
    _render_setup_and_stop()

# --- sidebar ---
with st.sidebar:
    trust_level, persona, sample = sidebar.render()

# --- intro caption (brand now lives in the sidebar logo) ---
st.caption("Ask about a building, landlord, or portfolio. Every answer is grounded "
           "in the public record; nothing is asserted that a tool did not return.")

# --- web search availability (Tavily is optional) ---
if not os.environ.get("TAVILY_API_KEY"):
    _render_web_search_notice()

# --- submission (chat input docks to the bottom, spanning both panels) ---
prompt = st.chat_input("Ask about a building, landlord, or portfolio") or _pending_sample(sample)

# --- split layout: conversation on the left, the report artifact on the right ---
chat_col, report_col = st.columns([4, 5], gap="large")

with chat_col:
    # transcript
    for message in st.session_state.messages:
        st.chat_message(message["role"]).markdown(display_safe(message["content"]))

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").markdown(display_safe(prompt))
        st.session_state.last_evidence = None
        st.session_state.last_turn = None

        config = {"configurable": {
            "thread_id": st.session_state.thread_id,
            "trust_level": trust_level,
            "persona": persona,
        }}
        with st.chat_message("assistant"):
            answer, evidence, cost = _render_turn(get_agent(), prompt, config)

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.last_evidence = evidence
        st.session_state.last_turn = {
            "question": prompt, "answer": answer, "evidence": evidence, "cost": cost,
            "trust_level": trust_level}

    # cost + evidence for the latest answer (persist across reruns)
    if (st.session_state.last_turn is not None
            and st.session_state.last_turn.get("cost") is not None):
        st.caption(summary_line(st.session_state.last_turn["cost"]))
    if st.session_state.last_evidence is not None and not st.session_state.last_evidence.is_empty:
        _render_evidence(st.session_state.last_evidence)

with report_col:
    _render_report_panel(st.session_state.last_turn)
