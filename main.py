"""Runnable usage example for the WatchlineNYC-Discovery agent library.

    uv run python main.py

Shows the whole calling contract end to end: build the agent, open a session (a
thread id + the trust/persona config), pass a turn, and read the **structured,
cited** tool payloads — not just the prose. Requires a populated ``.env``
(``ANTHROPIC_API_KEY`` plus the Neo4j discovery connection); it calls the model
and the live graph.

Import-safe: importing this module builds nothing and calls no model — the agent
is built and invoked only inside :func:`main`.
"""

from __future__ import annotations

import json

#: A Type II (apparent-control) question — its answer ships reliability caveats
#: and run provenance, so the structured payload shows what the prose is built on.
EXAMPLE_QUESTION = "Who owns the building at BBL 1000050010, and how confident is that?"


def _final_text(state) -> str:
    for message in reversed(state["messages"]):
        content = getattr(message, "content", None)
        if getattr(message, "type", None) == "ai" and isinstance(content, str) and content.strip():
            return content
    return ""


def _tool_payloads(state) -> dict[str, list]:
    payloads: dict[str, list] = {}
    for message in state["messages"]:
        name = getattr(message, "name", None)
        if getattr(message, "type", None) == "tool" and name:
            content = getattr(message, "content", None)
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
            except (ValueError, TypeError):
                parsed = content
            payloads.setdefault(name, []).append(parsed)
    return payloads


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    from watchline.discovery.agent import build_agent

    agent = build_agent()

    # A session is a thread id plus the trust/persona contract, in the run config.
    # Trust gates capability (a "vetted" thread can reach the Tier-4 deep agent);
    # persona shapes tone only and never confers trust.
    config = {
        "configurable": {
            "thread_id": "example-session",
            "trust_level": "public",
            "persona": "general_public",
        }
    }

    state = agent.invoke(
        {"messages": [{"role": "user", "content": EXAMPLE_QUESTION}]},
        config=config,
    )

    print(f"Q: {EXAMPLE_QUESTION}\n")
    print(f"A: {_final_text(state)}\n")
    print("Structured tool payloads (the cited evidence behind the prose):")
    print(json.dumps(_tool_payloads(state), indent=2, default=str))


if __name__ == "__main__":
    main()
