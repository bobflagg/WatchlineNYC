"""Sidebar: brand, the session's trust/persona (a demo control), samples, reset.

Kept thin — the trust caption states plainly that this is a demo affordance, not a
security control (the enforced boundary is the library's fail-closed gate).
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

import streamlit as st

from watchline.discovery.agent.session import DEFAULT_PERSONA, VALID_PERSONAS
from watchline.discovery.ui.samples import sample_questions

_LOGO = Path(__file__).with_name("logo.png")


def _logo() -> None:
    if _LOGO.exists():
        b64 = base64.b64encode(_LOGO.read_bytes()).decode()
        st.html(
            '<div style="display:flex;justify-content:center;padding:0 0 1rem 0;">'
            f'<img src="data:image/png;base64,{b64}" '
            'style="width:100%;border-radius:12px;" alt="Watchline NYC"/></div>'
        )


def render() -> tuple[str, str, str]:
    """Draw the sidebar; return the chosen (trust_level, persona, sample)."""
    _logo()

    st.subheader("Session")
    trust = st.selectbox(
        "Trust level", ["public", "vetted"], index=0, key="trust_level")
    st.caption(
        "⚠️ Demo control — a real deployment sets trust from authentication, not "
        "here. Only a vetted thread can reach the Tier-4 deep investigation."
    )

    personas = sorted(VALID_PERSONAS)
    persona = st.selectbox(
        "Persona", personas, index=personas.index(DEFAULT_PERSONA), key="persona")

    sample = st.selectbox("Sample question", ["—", *sample_questions(trust)], key="sample")

    if st.button("New chat", width="stretch"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        for key in ("_last_sample", "last_evidence", "last_turn"):
            st.session_state.pop(key, None)
        st.rerun()

    return trust, persona, sample
