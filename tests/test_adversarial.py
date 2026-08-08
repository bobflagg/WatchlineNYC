"""Adversarial edge cases — the genuinely-missing pieces (Phase 6, Group 2).

Most adversarial coverage already exists and is catalogued in
[`ADVERSARIAL.md`](./ADVERSARIAL.md); per decision P6-4 this file adds only the
cases that were not yet pinned. Right now that is the tool-level surfacing of an
**unbounded traversal being bounded**: the investigator's ``run_cypher`` caps
rows and must *tell the agent* it truncated, so a scan of a 42M-node label comes
back as a flagged partial result rather than an unbounded dump or a silent
head. (The refusal, timeout-feedback, and cap-value paths are already covered in
``test_investigator.py``; this pins the ``truncated`` signal itself.)
"""

from __future__ import annotations

from watchline.discovery.agent import investigator
from watchline.discovery.agent.db import ReadResult


def test_unbounded_scan_is_capped_and_flagged_as_truncated(monkeypatch):
    """A broad scan returns at most the row cap, with ``truncated`` set — the
    agent is told the result is partial, never handed a silent head."""
    cap = investigator.RUN_CYPHER_ROW_CAP

    def fake_read(cypher, parameters=None, **kwargs):
        # The DB layer capped the scan at row_cap and reports the overflow.
        assert kwargs.get("row_cap") == cap  # run_cypher must pass the cap through
        return ReadResult(records=[{"n": i} for i in range(cap)], truncated=True, row_cap=cap)

    monkeypatch.setattr(investigator, "read", fake_read)
    out = investigator.run_cypher.invoke({"cypher": "MATCH (n) RETURN n"})

    assert out["truncated"] is True
    assert out["row_count"] == cap
    assert out["row_count"] <= cap  # never more than the cap escapes the tool
