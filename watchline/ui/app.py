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

if "last_lead" not in st.session_state:
    st.session_state.last_lead = None

if "pending_handoff_question" not in st.session_state:
    st.session_state.pending_handoff_question = None

# Streamlit forbids writing st.session_state.mode once the st.radio(key="mode")
# widget in render_sidebar() has been instantiated this run -- so a mode
# switch triggered from the main body (the Lead panel's hand-off button)
# can't set st.session_state.mode directly. It sets this separate,
# unbound flag instead; consuming it here, before render_sidebar() runs,
# is what actually changes the radio's value for this run.
if st.session_state.get("pending_mode_switch"):
    st.session_state.mode = st.session_state.pop("pending_mode_switch")

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
# Discovery Lead panel
# ---------------------------------------------------------------------------
# Charter Principle 18: Discovery's output is a Lead, never a Claim -- it
# carries no Interpretive Status and asserts nothing about the world. This
# panel exists to show that distinction to the user, not just to display
# data (design doc §2).

# Maps a Lead's suggested_intent to a natural-language question likely to
# route back to the SAME intent_category when evidentiary's identify_intent
# parses it (see watchline/fw/intent.py's INTENT_SYSTEM_PROMPT definitions --
# these templates paraphrase that prompt's own intent definitions).
_INTENT_QUESTION_TEMPLATES = {
    "PortfolioIdentification":   "Who actually controls {target}?",
    "PortfolioCondition":        "How bad is {target}'s record across all their buildings?",
    "Recidivism":                "Has {target} let hazardous conditions persist repeatedly?",
    "WorstFirst":                "Who is the worst landlord in NYC?",
    "ConcealmentDetection":      "Is {target} using LLCs or name variations to hide their identity?",
    "DeteriorationTrajectory":   "Is {target} getting worse over time?",
    "EnforcementAccountability": "Is HPD following up on violations at {target}?",
    "GeographicConcentration":   "Are there clusters of troubled buildings near {target}?",
    "OwnershipChange":           "Did conditions change after {target} was sold?",
    "BuildingDueDiligence":      "What is the full record on {target}?",
    "RentStabilization":         "Is {target} losing rent-stabilized units?",
    "FineEvasion":               "What are the outstanding ECB fines at {target}?",
    "NetworkExposure":           "Is {target} connected to other landlords with bad records?",
}


# Intents whose phrasing is about a landlord/actor, not a specific building
# ("...their buildings", "...let conditions persist", "...hide their
# identity") -- these must prefer the Actor's name over a BBL, or the
# constructed question reads incoherently (e.g. "How bad is BBL 123's record
# across all their buildings?"). Everything else is building-scoped and
# prefers the BBL.
_ACTOR_SCOPED_INTENTS = {
    "PortfolioCondition", "Recidivism", "ConcealmentDetection", "NetworkExposure",
}


def _build_handoff_question(lead: dict) -> str | None:
    """
    Construct a natural-language question from a Lead's target and
    suggested_intent, for the "investigate in evidentiary" hand-off
    (design doc §9). Only Building.bbl is safe to hand off directly --
    Discovery's Actor/Portfolio ids are a namespace evidentiary doesn't
    share (Reconciliation Principle 3) -- so an Actor target is handed off
    by its human-readable name instead. Portfolio-only Leads have no clean
    evidentiary equivalent and return None.
    """
    proposal = lead.get("lead_proposal") or {}
    intent = proposal.get("suggested_intent")
    template = _INTENT_QUESTION_TEMPLATES.get(intent)
    if not template:
        return None
    if "{target}" not in template:
        return template  # e.g. WorstFirst names no specific target

    targets = lead.get("validated_targets") or []
    building = next((t for t in targets if t.get("kind") == "Building"), None)
    actor = next((t for t in targets if t.get("kind") == "Actor" and t.get("label")), None)

    primary, fallback = (actor, building) if intent in _ACTOR_SCOPED_INTENTS else (building, actor)
    chosen = primary or fallback
    if not chosen:
        return None
    label = f"BBL {chosen['id']}" if chosen["kind"] == "Building" else chosen["label"]
    return template.format(target=label)


def _render_lead_panel():
    """Render the latest Discovery Lead, with an evidentiary hand-off button."""
    lead = st.session_state.get("last_lead")
    if not lead:
        return

    st.divider()
    proposal = lead.get("lead_proposal") or {}

    st.caption(f"🕵️ Discovery Lead · `{lead['lead_id']}`")
    st.markdown(
        f"**Suggested intent:** {proposal.get('suggested_intent', '—')}"
        f"  ·  **Priority:** {proposal.get('priority', '—')}"
    )
    st.info(
        "This is a Lead: a non-authoritative pointer for further investigation, "
        "not a Claim. It carries no Interpretive Status and asserts nothing "
        "about the world (Charter Principle 18)."
    )

    if proposal.get("novel_intent_description"):
        st.markdown(f"**Novel pattern:** {proposal['novel_intent_description']}")

    st.markdown("**Rationale**")
    st.write(proposal.get("rationale", "—"))

    targets = lead.get("validated_targets") or []
    if targets:
        st.markdown("**Targets**")
        for t in targets:
            st.write(f"- {t['kind']}: {t.get('label') or t['id']}  (`{t['id']}`)")

    question = _build_handoff_question(lead)
    if question:
        if st.button("🔍 Investigate in Evidentiary", key=f"handoff_{lead['lead_id']}"):
            st.session_state.pending_handoff_question = question
            st.session_state.pending_mode_switch = "🔬 Investigate"
            st.rerun()
        st.caption(f"Will ask: _{question}_")
    else:
        st.caption("No building or actor target available for an evidentiary hand-off.")


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
    events_panel = st.status("Investigating…", expanded=True)
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
            s = events_panel.status(f"🔧 {event['name']}", expanded=True)
            if event.get("input"):
                s.caption(event["input"])
            active[event["run_id"]] = s
        elif t == "tool_end":
            if s := active.get(event["run_id"]):
                output = event.get("output")
                if output:
                    s.write(output)
                s.update(label=f"✅ {event['name']}", state="complete")
        elif t == "dashboard":
            # Dashboard HTML arrives base64-encoded to guarantee SSE safety.
            encoded = event.get("html", "")
            if encoded:
                st.session_state.last_dashboard = base64.b64decode(
                    encoded.encode("ascii")
                ).decode("utf-8")
        elif t == "lead":
            # Discovery Explore's answer -- a Lead, not a dashboard. See
            # _render_lead_panel().
            st.session_state.last_lead = event
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
    events_panel.update(label=label, state="complete")
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


def pending_handoff():
    """
    Return a Discovery Lead's hand-off question once, else None.

    Set by _render_lead_panel()'s "Investigate in Evidentiary" button
    (design doc §9), which also switches st.session_state.mode to
    "🔬 Investigate" before calling st.rerun() -- by the time this function
    runs on the next script pass, the active mode is already Investigate,
    so returning the question here is enough to auto-submit it.
    """
    question = st.session_state.get("pending_handoff_question")
    if question:
        st.session_state.pending_handoff_question = None
        return question
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
    handoff = pending_handoff() if cfg["graph"] == "investigator" else None

    prompt = typed or pending or handoff
    if prompt:
        # Clear the previous dashboard/Lead so a stale result never shows
        # below a new question while the pipeline is still running.
        st.session_state.last_dashboard = None
        st.session_state.last_lead = None
        messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        with st.chat_message("assistant"):
            answer = render(prompt, cfg["graph"])
        # For investigator/explore responses the answer text is empty --
        # store a placeholder so the transcript shows something on replay.
        if answer:
            transcript_entry = answer
        elif cfg["graph"] == "explore":
            transcript_entry = "_(See Lead below)_"
        else:
            transcript_entry = "_(See dashboard below)_"
        messages.append({"role": "assistant", "content": transcript_entry})

    # Render the dashboard/Lead if the pipeline produced one. Displayed
    # outside the chat message so it gets full width.
    if st.session_state.get("last_dashboard") and cfg["graph"] == "investigator":
        _render_dashboard_panel()
    if st.session_state.get("last_lead") and cfg["graph"] == "explore":
        _render_lead_panel()

