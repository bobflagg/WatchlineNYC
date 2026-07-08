#!/usr/bin/env python3
"""
diagnose.py
Run from the WatchlineNYC project root:
    python diagnose.py

Traces the pipeline step by step to find where the dashboard breaks.
"""

import asyncio
import json
import sys
import os

# ---------------------------------------------------------------------------
# Step 1: Can we import everything?
# ---------------------------------------------------------------------------
print("=" * 60)
print("Step 1: Imports")
print("=" * 60)

try:
    from watchline.fw.investigator import build_pipeline
    print("  ✓ build_pipeline")
except Exception as e:
    print(f"  ✗ build_pipeline: {e}")
    sys.exit(1)

try:
    from watchline.fw.renderer import render_dashboard
    print("  ✓ render_dashboard")
except Exception as e:
    print(f"  ✗ render_dashboard: {e}")
    sys.exit(1)

try:
    from watchline.fw.state import WatchlineState
    print("  ✓ WatchlineState")
except Exception as e:
    print(f"  ✗ WatchlineState: {e}")

# ---------------------------------------------------------------------------
# Step 2: Does the pipeline graph contain render_dashboard?
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("Step 2: Pipeline graph nodes")
print("=" * 60)

pipeline = build_pipeline()
nodes = list(pipeline.get_graph().nodes.keys())
print(f"  Nodes: {nodes}")
if "render_dashboard" in nodes:
    print("  ✓ render_dashboard node present")
else:
    print("  ✗ render_dashboard node MISSING — investigator.py not updated")

# ---------------------------------------------------------------------------
# Step 3: Run the pipeline synchronously and inspect state
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("Step 3: Pipeline invoke")
print("=" * 60)

question = "Is 122 West 97th Street in Manhattan getting worse?"
print(f"  Question: {question}")

try:
    result = pipeline.invoke({"question": question})
except Exception as e:
    print(f"  ✗ Pipeline invoke failed: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

print(f"  State keys: {list(result.keys())}")
print(f"  answer present:        {'answer' in result and bool(result.get('answer'))}")
print(f"  dashboard_html present: {'dashboard_html' in result}")
print(f"  dashboard_html type:    {type(result.get('dashboard_html'))}")

dh = result.get("dashboard_html")
if dh:
    print(f"  dashboard_html length:  {len(dh)} chars")
    print(f"  starts with DOCTYPE:    {dh.strip().startswith('<!DOCTYPE')}")
else:
    print("  ✗ dashboard_html is None or empty")
    print()
    print("  traversal_results keys:", list((result.get("traversal_results") or {}).keys()))
    print("  error:", result.get("error"))
    print("  needs_clarification:", result.get("needs_clarification"))

# ---------------------------------------------------------------------------
# Step 4: Test the SSE event emission
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("Step 4: SSE event stream")
print("=" * 60)

async def scan_events():
    events_seen = []
    async for event in pipeline.astream_events(
        {"question": question}, version="v2"
    ):
        kind = event["event"]
        name = event.get("name", "")
        if kind == "on_chain_end" and name == "render_dashboard":
            out = event["data"].get("output") or {}
            print(f"  ✓ render_dashboard on_chain_end fired")
            print(f"    output keys: {list(out.keys()) if isinstance(out, dict) else type(out)}")
            dh = out.get("dashboard_html") if isinstance(out, dict) else None
            print(f"    dashboard_html present: {bool(dh)}")
            if dh:
                print(f"    dashboard_html length: {len(dh)} chars")
            events_seen.append("render_dashboard")
    if "render_dashboard" not in events_seen:
        print("  ✗ render_dashboard on_chain_end event never fired")

asyncio.run(scan_events())

# ---------------------------------------------------------------------------
# Step 5: Test base64 encode/decode round trip
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("Step 5: Base64 round-trip")
print("=" * 60)

import base64
if dh := result.get("dashboard_html"):
    encoded = base64.b64encode(dh.encode("utf-8")).decode("ascii")
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    assert decoded == dh, "Round-trip mismatch!"
    print(f"  ✓ Round-trip OK ({len(encoded)} base64 chars)")
else:
    print("  skipped — no dashboard_html to encode")

print()
print("=" * 60)
print("Diagnosis complete.")
print("=" * 60)
