"""CLI for the operator analysis — prints the leaderboard + #1 resolved cluster.

The logic lives in :mod:`watchline.discovery.analytics.operators` (importable so the
UI can call it). See that module for the read-only / GDS / reliability notes.

Run:  uv run python scripts/top_operators.py
"""

from __future__ import annotations

import json
from typing import Any

from watchline.discovery.analytics.operators import top_operators


def _print(payload: dict[str, Any]) -> None:
    print(f"\n=== {payload.get('view', 'top operators')} (ranked by buildings) ===")
    for i, r in enumerate(payload["leaderboard"], 1):
        frag = "" if r["records"] == 1 else f"  ({r['records']} records unified)"
        print(f"{i:>2}. {r['operator']:<24} {r['buildings']:>4} buildings{frag}")

    op = payload["top_operator"]
    print(f"\n=== #1 resolved: {op['name']} ===")
    print(f"  buildings: {op.get('buildings')} · residential units: "
          f"{op.get('residential_units')} · rent-stabilized: {op.get('rent_stabilized_units')}")
    print(f"  records unified ({len(op.get('records', []))}):")
    for rec in op.get("records", []):
        print(f"    - {rec['actor_id']}  {rec.get('buildings', 0):>3} bldgs  {rec.get('address')}")
    print(f"  name-links in cluster: {len(op.get('name_edges', []))}")
    ev = op.get("events", [])
    if ev:
        print("  event fingerprint: " + ", ".join(f"{e['event_type']} {e['events']:,}" for e in ev[:6]))


if __name__ == "__main__":
    payload = top_operators(hidden=True)   # the "hidden operators" view (fragmented identity)
    _print(payload)
    print("\n--- raw payload (first 1000 chars) ---")
    print(json.dumps(payload, default=str)[:1000])
