import base64
from pathlib import Path
import os

import streamlit as st
from sidebar import MODES, _PLACEHOLDER, render as render_sidebar
import uuid

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "last_dashboard" not in st.session_state:
    st.session_state.last_dashboard = None

st.set_page_config(
    page_title="Watchline NYC",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar: render_sidebar() 


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,400;9..144,600&display=swap');

    #MainMenu, footer, header {visibility: hidden;}

    [data-testid="stSidebar"] {
        background: #0a1629;
        border-right: 2px solid #d4a017;
    }
    /* Collapse the reserved header/nav region at the top of the sidebar */
    [data-testid="stSidebarHeader"],
    [data-testid="stSidebarNav"] {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    /* Zero out the default top padding on the content wrapper(s) */
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    [data-testid="stSidebar"] > div,
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    [data-testid="stSidebarUserContent"] {
        padding-top: 0.75rem !important;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
        gap: 0.5rem;
    }
    [data-testid="stSidebar"] * {
        color: #e8e8e8;
    }

    .block-container {
        padding-top: 0rem;
        padding-bottom: 0rem;
        max-width: 100%;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .banner {
        background: #0a1629;
        color: #ffffff;
        padding: 2.2rem 3rem 2rem 3rem;
        border-bottom: 2px solid #d4a017;
        position: relative;
        overflow: hidden;
    }

    .banner::before {
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background-image:
            linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
        background-size: 44px 44px;
        pointer-events: none;
    }

    .banner-inner {
        max-width: 1080px;
        margin: 0 auto;
        position: relative;
        z-index: 1;
    }

    .banner-eyebrow {
        font-size: 0.72rem;
        letter-spacing: 0.32em;
        text-transform: uppercase;
        color: #d4a017;
        font-weight: 600;
        margin-bottom: 0.6rem;
    }

    .banner-title {
        font-family: 'Fraunces', serif;
        font-size: 3.2rem;
        font-weight: 600;
        line-height: 1.0;
        margin: 0 0 0.5rem 0;
        letter-spacing: -0.02em;
    }

    .banner-subtitle {
        font-size: 1.28rem;
        font-weight: 400;
        color: #b8b8b8;
        margin: 0;
        letter-spacing: 0.01em;
    }

    .body-wrap {
        max-width: 1080px;
        margin: 0 auto;
        padding: 4rem 3rem 3.5rem 3rem;
    }

    .body-wrap p {
        font-size: 1.12rem;
        line-height: 1.85;
        color: #2b2b2b;
        margin-bottom: 1.6rem;
    }

    .body-wrap p:first-of-type {
        font-size: 1.24rem;
        line-height: 1.7;
        color: #111111;
        font-weight: 500;
    }

    .body-wrap p:first-of-type::first-letter {
        font-family: 'Fraunces', serif;
        font-size: 3.6rem;
        font-weight: 600;
        float: left;
        line-height: 0.8;
        padding: 0.32rem 0.7rem 0 0;
        color: #d4a017;
    }

    .footer {
        background: #000000;
        color: #ffffff;
        padding: 2.6rem 3rem;
        text-align: center;
        border-top: 2px solid #d4a017;
    }

    .footer-values {
        font-size: 0.95rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-weight: 600;
        color: #e8e8e8;
    }

    .footer-values .dot {
        color: #d4a017;
        margin: 0 0.9rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "⚖️" in st.session_state.mode:
    extras = ""
else:
    extras =  f"- {st.session_state.mode.split()[-1]}"
st.markdown(
    f"""
    <div class="banner">
        <div class="banner-inner">
            <div class="banner-eyebrow">Accountability infrastructure for NYC housing enforcement</div>
            <h1 class="banner-title">{st.session_state.mode[0]} Watchline NYC{extras}</h1>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

body_paragraphs = [
    "New York City’s housing enforcement data is public, but accountability is not. Violations are recorded. Inspections happen. Deeds are filed. Yet the questions that matter most are also the hardest to answer quickly, systematically, and with evidence that holds up to scrutiny: who is ultimately responsible for this building, why have conditions persisted, and what is the full pattern across a portfolio.",
    "Watchline NYC is being built to change that. It is an integrated knowledge graph linking every major housing enforcement dataset: HPD violations, DOB complaints and permits, ECB/OATH judgments, ACRIS deed records, DHCR rent stabilization filings, tax liens, and beneficial ownership disclosures. These datasets are connected through a principled model of building identity, ownership chains, and enforcement history. Over that graph sits an AI agent that interprets investigative questions in plain language, retrieves structured evidence from the graph, and returns answers in which every claim is explicitly linked to the records that support it.",
    "The animating principle is that answers must be defensible, not merely plausible. Watchline distinguishes between what the records show, what can be reasonably inferred, and what remains uncertain. Every conclusion the system produces can be traced back through its reasoning to the primary sources that justify it. When the underlying data changes, because a deed is corrected, a violation is resolved, or an ownership structure is updated, the conclusions update with it.",
    "Watchline does not make legal findings or editorial judgments. It is infrastructure: a shared capability that makes rigorous, evidence-based investigation faster and more accessible for the journalists, tenant advocates, legal services organizations, policy analysts, and watchdog agencies whose work depends on knowing who is responsible and what the record shows.",
    "The immediate goal is to make the kind of research that currently takes an expert hours available in minutes, and to make it available not just to specialists, but to the tenant in a deteriorating building who needs to understand who actually controls it, and why that matters.",
]

import httpx
import json

API_BASE = "http://localhost:8080"

# ---------------------------------------------------------------------------
# Dashboard panel
# ---------------------------------------------------------------------------

def _render_dashboard_panel():
    """Render the latest investigator dashboard with a download button."""
    html_str = st.session_state.get("last_dashboard", "")
    if not html_str:
        return

    st.divider()

    col_label, col_dl = st.columns([0.85, 0.15], vertical_alignment="center")
    with col_label:
        st.caption("📊 Watchline Dashboard — Evidence · Rules · Query")
    with col_dl:
        st.download_button(
            label="⬇ Download",
            data=html_str.encode("utf-8"),
            file_name="watchline_dashboard.html",
            mime="text/html",
            use_container_width=True,
            key=f"dl_{st.session_state.thread_id}",
        )

    st.components.v1.html(html_str, height=700, scrolling=True)


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

def iter_events(prompt: str, graph: str):
    """Stream SSE events from a named graph endpoint ('deedwatch' | 'investigator')."""
    with httpx.stream(
        "POST", f"{API_BASE}/stream/{graph}",
        json={"message": prompt, "thread_id": st.session_state.thread_id},
        timeout=None,
    ) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line[len("data: "):])


def render(prompt: str, graph: str) -> str:
    # One collapsible panel holds the whole event stream. While it's running,
    # st.status shows a spinner in the title; we flip it to "complete" at the end.
    events_panel = st.status("Investigating…", expanded=False)
    active = {}            # run_id -> sub-status inside the panel
    event_count = 0

    # Answer text renders OUTSIDE the panel, so the final answer stays visible
    # after the event log is collapsed.
    text, placeholder = "", st.empty()

    for event in iter_events(prompt, graph):
        t = event["type"]
        if t == "token":
            text += event["content"]
            placeholder.markdown(text + "▌")
        elif t == "tool_start":
            event_count += 1
            events_panel.update(label=f"Investigating… ({event_count} steps)")
            s = events_panel.status(f"🔧 `{event['name']}`", expanded=False)
            s.write(f"Input: `{event['input']}`")
            active[event["run_id"]] = s
        elif t == "tool_end":
            if s := active.get(event["run_id"]):
                s.write(f"Result: `{event['output']}`")
                s.update(label=f"✅ `{event['name']}`", state="complete")
        elif t == "dashboard":
            # Dashboard HTML arrives base64-encoded to guarantee SSE safety.
            encoded = event.get("html", "")
            if encoded:
                st.session_state.last_dashboard = base64.b64decode(
                    encoded.encode("ascii")
                ).decode("utf-8")
        elif t == "error":
            events_panel.error(event["message"])
            events_panel.update(label="Error", state="error", expanded=True)
        elif t == "done":
            break

    # Only render the placeholder if tokens actually arrived (DeedWatch path).
    # For the investigator, text is empty and the dashboard is the answer.
    if text:
        placeholder.markdown(text)
    else:
        placeholder.empty()

    label = f"✅ {event_count} steps" if event_count else "✅ Done"
    events_panel.update(label=label, state="complete", expanded=False)
    return text


def pending_sample(select_key: str, guard_key: str):
    """Return a freshly-selected sample question once, else None.

    The guard ensures a given selection submits only once across reruns.
    """
    selected = st.session_state.get(select_key, _PLACEHOLDER)
    if selected != _PLACEHOLDER and selected != st.session_state.get(guard_key):
        st.session_state[guard_key] = selected
        return selected
    return None


cfg = MODES[st.session_state.mode]
# Per-mode transcripts: the two graphs are separate conversations.
for _cfg in MODES.values():
    st.session_state.setdefault(_cfg["messages_key"], [])


# ---------------------------------------------------------------------------
# Main area: the active mode's conversation
# ---------------------------------------------------------------------------
if "⚖️" in st.session_state.mode:
    st.markdown(
        '<div class="body-wrap">' + "".join(f"<p>{p}</p>" for p in body_paragraphs) + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="footer">
            <div class="footer-values">
                Evidence<span class="dot">•</span>Transparency<span class="dot">•</span>Accountability
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    messages = st.session_state[cfg["messages_key"]]
    for m in messages:
        st.chat_message(m["role"]).write(m["content"])

    typed = st.chat_input(cfg["input_placeholder"])
    pending = pending_sample(cfg["select_key"], cfg["guard_key"])

    prompt = typed or pending
    if prompt:
        # Clear the previous dashboard so a stale result never shows
        # below a new question while the pipeline is still running.
        st.session_state.last_dashboard = None
        messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        with st.chat_message("assistant"):
            answer = render(prompt, cfg["graph"])
        # For investigator responses the answer text is empty — store a
        # placeholder so the transcript shows something on replay.
        transcript_entry = answer if answer else "_(See dashboard below)_"
        messages.append({"role": "assistant", "content": transcript_entry})

    # Render the dashboard if the investigator produced one.
    # Displayed outside the chat message so it gets full width.
    if st.session_state.get("last_dashboard") and cfg["graph"] == "investigator":
        _render_dashboard_panel()

