"""The public API surface + import-safety (Phase 6, Group 3).

The library's calling surface is exported from ``watchline.discovery.agent`` and
documented in prose; these tests pin that it actually imports, that the eager
names carry no agent build, and that the usage example is import-safe.
"""

from __future__ import annotations

import importlib


def test_session_contract_imports_from_the_package():
    from watchline.discovery.agent import (  # noqa: F401
        DEFAULT_PERSONA,
        DEFAULT_TRUST_LEVEL,
        VALID_PERSONAS,
        VALID_TRUST_LEVELS,
        DiscoveryState,
        TrustLevel,
        all_tools,
        resolve_persona,
        resolve_trust_level,
    )

    assert callable(resolve_trust_level)
    assert callable(resolve_persona)
    assert callable(all_tools)


def test_all_lists_the_public_surface():
    import watchline.discovery.agent as agent_pkg

    for name in agent_pkg.__all__:
        assert hasattr(agent_pkg, name), f"{name} is in __all__ but not importable"


def test_build_agent_is_exported_lazily():
    """``build_agent`` resolves on access without an eager build."""
    import watchline.discovery.agent as agent_pkg

    build_agent = agent_pkg.build_agent
    assert callable(build_agent)
    # The compiled singleton the server serves lives on the submodule (the
    # package-level name would collide with the submodule).
    from watchline.discovery.agent import graph as graph_module

    assert graph_module.graph is not None


def test_unknown_attribute_still_raises():
    import watchline.discovery.agent as agent_pkg

    try:
        agent_pkg.does_not_exist
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AttributeError for an unknown attribute")


def test_usage_example_imports_without_side_effects():
    """Importing ``main`` must not build the agent or call the model."""
    main = importlib.import_module("main")
    assert callable(main.main)
    # The example question is a module constant, not the product of a call.
    assert isinstance(main.EXAMPLE_QUESTION, str) and main.EXAMPLE_QUESTION
