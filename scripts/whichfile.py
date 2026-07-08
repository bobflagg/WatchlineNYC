#!/usr/bin/env python3
"""
whichfile.py
Prints the exact file path of every watchline module being imported.
Run from project root: uv run python scripts/whichfile.py
"""
import watchline.fw.investigator as inv
import watchline.fw.renderer as rend
import watchline.fw.state as st
import watchline.fw.router as router

print("investigator.py :", inv.__file__)
print("renderer.py     :", rend.__file__)
print("state.py        :", st.__file__)
print("router.py       :", router.__file__)

# Show the actual nodes in the compiled graph
from watchline.fw.investigator import build_pipeline
pipeline = build_pipeline()
nodes = list(pipeline.get_graph().nodes.keys())
print("\nCompiled graph nodes:", nodes)

# Show first 30 lines of the investigator that's running
print("\n--- investigator.py (first 40 lines) ---")
with open(inv.__file__) as f:
    for i, line in enumerate(f, 1):
        print(f"{i:3}: {line}", end="")
        if i >= 40:
            break
