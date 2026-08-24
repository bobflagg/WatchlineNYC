# Add `CONNECTED_BY_SPLINK` — de-fragment portfolios with a probabilistic same-owner edge

> **Draft / RFC.** Opening this for discussion before investing further — is a
> Splink-based same-owner edge something you'd want in the portfolio pipeline? Happy to
> adjust the shape, the dependency, and the tuning to fit how you'd actually use it.

## What it does

`build_graph` links landlord nodes by matching **names** and **business addresses**, then
`iter_split_graph` clusters them with WCC + recursive Louvain. That misses an owner's
*own* fragments when a business-address typo or a second office defeats the address match —
**Steven Croman resolves to ~6 separate portfolios** instead of one.

This adds one more edge type. It resolves HPD owner contacts into probabilistic entities
(precision-first record linkage) and drops a `type="splink"` edge between the nodes that
resolve to the same owner. **WCC and Louvain don't change** — they just cluster a graph
with a third, high-confidence edge. Because edges only *add*, components only *merge, never
split*: your existing address-nexus portfolios (a shell operation sharing one managing
office) are preserved; an owner's scattered offices collapse into one.

## The change (WCC/Louvain untouched)

**1. New module `portfoliograph/splink_edges.py`** — resolves owners and adds a same-owner
clique to the graph.

**2. `graph.py` — add the edges:**
```diff
-def build_graph(dict_cursor) -> nx.Graph:
+def build_graph(dict_cursor, add_splink_edges: bool = False) -> nx.Graph:
     ...
     for contact in contacts:
         ...  # name + bizaddr edges, unchanged
+    if add_splink_edges:
+        from . import splink_edges
+        n = splink_edges.add_to_graph(g, contacts, dict_cursor.connection)
+        print(f"Added {n} splink same-owner edges")
     return g
```
`iter_split_graph` / `split_subgraph_if` / `louvain_communities` / `connected_components`
— **no change.**

**3. `table.py` — turn it on:**
```diff
-    g = graph.build_graph(cur)
+    g = graph.build_graph(cur, add_splink_edges=True)
```

## The dependency

A small companion package, [`nyc-landlord-resolution`](https://github.com/bobflagg/nyc-landlord-resolution)
(MIT), extracted to run on the HPD tables alone — no knowledge graph, no geocoder. It
exposes one function:

```python
owner_index(conn) -> { (normalized_name, bbl): owner_id }
```

The precision guarantees live there: name-anchored blocking + a first-name veto
(JACOB ≠ JOSEF) + a common-name veto (two unrelated JIN CHENs never merge). Not on PyPI
yet — install from git while this is a draft.

## Validation

Run against a full WoW dataset, through **this repo's own `build_graph`** (not a
reimplementation):

- **Croman: 6 portfolios → 2** — his 12 nodes, split across 6 portfolios by name/address alone
  (largest 118 bbls), consolidate to a **126-bbl main portfolio** (plus one 9-bbl remnant that
  has no corp/address bridge to the main).
- **6,292 `CONNECTED_BY_SPLINK` edges added** (only *new* cross-office bridges — the module
  skips pairs your graph already connects).
- **0 edges link different surnames**; against a 105-record hand-adjudicated (owner-level) gold
  set the resolution scores pairwise **P ≈ 1.0 — zero false merges** — and agrees with an
  independent ACRIS multi-parcel-deed co-ownership signal ~86% of the time, population-wide.

## Honest caveats

- **Reproducible, not slice-dependent.** `owner_index` trains on a *stratified* slice — every
  identity with a same-name peer, across all operators — not a hand-picked or random sample.
  Two independent draws resolve the population to same-owner-pair Jaccard ~0.99, so the result
  reflects the data, not which records happened to be sampled. Gold precision is ≈1.0 against
  the owner-level gold (clustering threshold 0.999).
- **Recall is externally validated, population-wide.** Beyond the 4-family gold set (which
  anchors *precision* — "never fuses namesakes"), the resolution was checked against an
  independent, name-free signal: pairs of buildings sold together on a single ACRIS deed (same
  grantee ⇒ same owner). It agrees **~86% of the time vs ~0% by chance**, and equally for
  operators *outside* the gold families — evidence it generalizes rather than just consolidating
  the showcased operators.
- **Louvain can occasionally strand a node.** On a merged component over `MAX_SIZE`, Louvain
  may place one of a large owner's nodes in a neighbouring sub-portfolio (recall-only, never a
  wrong fusion). The stratified slice makes this rare — ~1 pair in a full-city run;
  `SPLINK_WEIGHT` is the lever if it matters to you.
- **Runtime:** `owner_index` runs the full-population resolution once (~1–2 min) per build.

## Try it

```bash
pip install git+https://github.com/bobflagg/nyc-landlord-resolution.git
# then:  g = build_graph(cur, add_splink_edges=True)
```

The companion repo ships the gold-set benchmark (`nlr/eval/`) so the resolution quality is
reproducible independently of this pipeline.
