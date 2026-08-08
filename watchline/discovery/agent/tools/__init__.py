"""The shared Tier 1-3 Cypher tool library.

One tool per *canonical pattern*, not one per tier. Written once and used from
two places: the top-level agent takes the fast path, and Phase 5's Tier-4 deep
agent is handed the same library for its own internal investigation.

Every tool in here:

* reads through :mod:`watchline.discovery.agent.db` and nothing else,
* declares what it touches with
  :func:`watchline.discovery.agent.reliability.tagged`, which attaches the
  canonical caveats and fails at import if a Type II tool has none,
* returns a structured payload rather than prose. This module's product is
  cited data; presentation is the calling application's concern.
"""
