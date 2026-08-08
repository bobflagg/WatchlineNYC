"""Shared setup for the ``llm`` tiers.

The llm tests assert on *tool invocation and payload structure*, never on model
prose, so they do not need the production Opus model to make the same routing
decisions. This routes the whole stack (top-level agent and the Tier-4
investigator, both built via ``graph.build_model``) onto a cheaper model per
test — a large cost saving with no change to production, which reads no
``WATCHLINE_MODEL``:

* **``-m llm``** (routing / structural checks) run on **Haiku 4.5** — cheapest,
  and plenty for deciding which tool to call.
* **``-m llm_deep``** (a full Tier-4 investigation, which reasons over many
  hops) runs on **Sonnet 5** — a stronger reasoner, still far below Opus cost.

Overrides: ``WATCHLINE_TEST_MODEL`` for the routing tier, ``WATCHLINE_TEST_DEEP_MODEL``
for the deep tier, or pin ``WATCHLINE_MODEL`` yourself to force one model for the
whole run.

Implementation note: the override is a **function-scoped, autouse ``monkeypatch``**
fixture. Function scope means it restores after every test, so it cannot leak the
cheap model into a hermetic test in a full ``-m ''`` run; autouse-before-requested
ordering means it sets the env before the (also function-scoped) ``agent`` fixture
builds the model. This is why the ``agent`` fixtures are function-scoped.
"""

from __future__ import annotations

import os

import pytest

#: The routing (``-m llm``) tier's model — cheapest, since these tests only check
#: which tool is called.
DEFAULT_LLM_MODEL = os.environ.get("WATCHLINE_TEST_MODEL", "claude-haiku-4-5-20251001")

#: The deep-agent (``-m llm_deep``) tier's model — a stronger reasoner for the
#: multi-hop investigation, still well below Opus cost.
DEFAULT_LLM_DEEP_MODEL = os.environ.get("WATCHLINE_TEST_DEEP_MODEL", "claude-sonnet-5")


@pytest.fixture(autouse=True)
def _cheap_model_for_llm_tests(request, monkeypatch):
    """Point ``graph.build_model`` at the right cheap model for this test.

    A test marked ``llm_deep`` gets the deep-tier model; everything else in the
    llm tiers gets the routing model. An explicit ``WATCHLINE_MODEL`` set by the
    caller wins, so a developer can pin any model for a run.
    """
    if os.environ.get("WATCHLINE_MODEL") is not None:
        return
    is_deep = request.node.get_closest_marker("llm_deep") is not None
    monkeypatch.setenv("WATCHLINE_MODEL", DEFAULT_LLM_DEEP_MODEL if is_deep else DEFAULT_LLM_MODEL)
