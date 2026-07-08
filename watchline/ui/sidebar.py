import base64
import os
import streamlit as st
import uuid

# Each mode pairs a graph endpoint with its own sample questions and transcript.
MODES = {
    "⚖️ Mission": {
        "emoji": "⚖️",                    # rendered via CSS ::before, not the label
        "graph": "investigator",          # single-shot, evidence-grounded pipeline
        "messages_key": "inv_messages",
        "select_key": "investigate_sample",
        "guard_key": "last_investigate_sample",
        "input_placeholder": "Ask about a building or landlord",
        "samples": [
        ],
    },
    "🔬 Investigate": {
        "emoji": "🔬",                    # rendered via CSS ::before, not the label
        "graph": "investigator",          # single-shot, evidence-grounded pipeline
        "messages_key": "inv_messages",
        "select_key": "investigate_sample",
        "guard_key": "last_investigate_sample",
        "input_placeholder": "Ask about a building or landlord",
        "samples": [
            "Is 122 West 97th Street in Manhattan getting worse?",
            "Who controls 530 East 169th Street in the Bronx?",
            "What is the full record on 122 West 97th Street in Manhattan?",
            "Are Michael Bennett and Ryan Hiller operating as a coordinated network?",
            "Is 925 9 Avenue losing rent stabilized units?",
            "What are the ECB violations at 1459 Wythe Place Bronx?",
            "How bad is Mark Engel's record across all his buildings?",
            "Who is the worst landlord in NYC?",
            "Is HPD following up on violations at 79 Post Avenue, Manhattan",
            "Is HPD following up on violations at 1459 Wythe Place Bronx?",
            "Has Margaret Brunn let hazardous conditions persist repeatedly?",
            "Are LLCs being used to hide someone's identity in the Kamran Hakim portfolio?",
            "Are there clusters of troubled buildings in the Bronx?",
            "Did conditions change after 883 East 180 Street in the Bronx was sold?",
            "Did conditions change after 122 West 97th Street in Manhattan was sold?",
            "-----",
            "Has the landlord been keeping up with repairs at 10 Halletts Point?",
            "What's the BBL for 1071 Franklin Avenue, Bronx?",
            "How many of Mark Engel's buildings have persistent hazardous conditions?",
            "Tell me about 530 East 169th Street in the Bronx",
            "What are the ECB violations at 1459 Wythe Place Bronx?",
            "Who controls the buildings at 9 Metropolitan Oval in the Bronx?",
            "Is 1380 White Plains Road Bronx losing rent stabilized units?",
        ],
    },
    "🔭 Explore": {
        "emoji": "🔭",                    # rendered via CSS ::before, not the label
        "graph": "deedwatch",             # conversational deep agent, remembers context
        "messages_key": "messages",
        "select_key": "explore_sample",
        "guard_key": "last_explore_sample",
        "input_placeholder": "Ask a follow-up — it remembers context",
        "samples": [
            "Is 122 West 97th Street in Manhattan getting worse?",
            "Who controls 530 East 169th Street in the Bronx?",
            "What is the full record on 122 West 97th Street in Manhattan?",
            "Are Michael Bennett and Ryan Hiller operating as a coordinated network?",
            "Is 925 9 Avenue losing rent stabilized units?",
            "What are the ECB violations at 1459 Wythe Place Bronx?",
            "How bad is Mark Engel's record across all his buildings?",
            "Who is the worst landlord in NYC?",
            "Is HPD following up on violations at 79 Post Avenue, Manhattan",
            "Is HPD following up on violations at 1459 Wythe Place Bronx?",
            "Has Margaret Brunn let hazardous conditions persist repeatedly?",
            "Are LLCs being used to hide someone's identity in the Kamran Hakim portfolio?",
            "Are there clusters of troubled buildings in the Bronx?",
            "Did conditions change after 883 East 180 Street in the Bronx was sold?",
            "Did conditions change after 122 West 97th Street in Manhattan was sold?",
            "-----",
            "Has the landlord been keeping up with repairs at 10 Halletts Point?",
            "What's the BBL for 1071 Franklin Avenue, Bronx?",
            "How many of Mark Engel's buildings have persistent hazardous conditions?",
            "Tell me about 530 East 169th Street in the Bronx",
            "What are the ECB violations at 1459 Wythe Place Bronx?",
            "Who controls the buildings at 9 Metropolitan Oval in the Bronx?",
            "Is 1380 White Plains Road Bronx losing rent stabilized units?",
            "How many rent-stabilized units does it have?",
            "Who owns 1-02 26th Avenue, Queens, and how confident is that link?",
            "How many rent-stabilized units does 1-02 26th Avenue have?",
            "What other buildings does that owner control, and how many units total?",
            "What's the enforcement history for 1-02 26th Avenue — HPD, DOB, ECB/OATH?",
            "Show the ownership chain for 26-50 1st Street, Queens, with interpretive status.",
        ],
    },
}

_PLACEHOLDER = "--"


def configure_agents():
    st.session_state.model = init_chat_model(st.session_state.llm_aggregate)
    
    
def render():
    _logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
    _logo_b64 = None
    if os.path.exists(_logo_path):
        with open(_logo_path, "rb") as _f:
            _logo_b64 = base64.b64encode(_f.read()).decode()
    if _logo_b64:
        st.markdown(
            f"""
            <div style="display:flex; justify-content:center; padding:0 0 1.5rem 0;">
                <img src="data:image/png;base64,{_logo_b64}"
                     style="width:100%; max-width:240px; border-radius:12px;
                            box-shadow:0 8px 24px rgba(0,0,0,0.35);" />
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("Place logo.png in the assets/ folder next to this app.")

    # Model selector
    options = list(MODES.keys())
    with st.expander(label=":material/settings: Select an Application Mode", expanded=True):
        mode = st.radio(
            label=":material/settings: Select View",
            options=options,
            key="mode",
            label_visibility="collapsed",
            horizontal=False,
        )

    cfg = MODES[mode]

    # st.caption(f"Thread: `{st.session_state.thread_id[:8]}`")            

    # Model selector
    with st.expander(label=":material/settings: Select Models", expanded=True):
        options = [
            "claude-haiku-4-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        ]
        st.selectbox(
            "🔬 Investigation Model",
            options,
            key="llm_aggregate",
            on_change=configure_agents,
            index=0,
        )
        st.selectbox(
            "🔭 Exploration Model",
            options,
            key="llm_analyze",
            on_change=configure_agents,
            index=0,
        )

    if "⚖️" not in st.session_state.mode:
        # Only the active mode's pulldown is rendered.
        st.selectbox(
            ":material/settings: Select a Sample Question",
            options=[_PLACEHOLDER, *cfg["samples"]],
            index=0,
            key=cfg["select_key"],
        )
        left, right = st.columns([.5, .5], vertical_alignment="center", border=False)
        with left:
            if st.button("💭 New chat"):
                st.session_state.thread_id = str(uuid.uuid4())
                for c in MODES.values():
                    st.session_state[c["messages_key"]] = []
                    st.session_state.pop(c["guard_key"], None)
                st.rerun()
        with right:            
            if st.button("📝 Copy Answer"):
                st.session_state.thread_id = str(uuid.uuid4())
                for c in MODES.values():
                    st.session_state[c["messages_key"]] = []
                    st.session_state.pop(c["guard_key"], None)
                st.rerun()

