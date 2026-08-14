# Entity linking + portfolio construction — working notes

Scoped guidance for the **landlord entity-resolution pipeline** (this directory).
Read this before touching `splink_source.py` or `eval/`. Everything here lives on
the **`entity-linking-prototype`** branch; the deps (`splink`, `psycopg2`, `duckdb`)
are an **optional extra** — always run with `--extra ingest`.

## The problem we're solving

NYC landlord registrations fragment a single operator across many records (typo'd
names/addresses, multiple offices). WoW's rule-based linkage + WCC/Louvain inherits
this: **Steven Croman shows as 4 separate portfolios, Divya Rashad as 5**, because a
business-address typo (`4 WEST 51` vs `424 WEST 51`) or a different office defeats
the exact/gated matching. We replace the linkage with **probabilistic record
linkage (Splink)** and add a **feedback loop** for cross-office. Goal: precision-
first resolution (never fuse two different people) with recall lifted by the loop.

## Architecture — two stages + a loop

1. **Linking (records → entities).** Splink/Fellegi-Sunter over raw HPD owner
   contacts. `extract()` → `fit()` → `cluster()`.
2. **Portfolio construction (entities → portfolios).** At the name+address level the
   entity *is* the portfolio (its buildings = union of its records' `bbls`).
   `build_portfolios()`. (This supersedes WoW's WCC+Louvain for the linkage part.)
3. **Feedback loop (cross-office).** After pass 1, bridge name-compatible entities
   that share a corporate co-owner across their buildings — the signal name+address
   can't reach. `feedback_merge()`.

Where it sits vs. the existing code: `pipeline.py` + `algorithms.py` are the *old*
WoW-consuming portfolio build (reads WoW's `landlords_with_connections`, GDS
WCC+Louvain, writes KG `Portfolio` nodes). The Splink path is the intended
replacement/source; it is **not yet wired into `pipeline.py` or materialized to the
KG** (see "Not done").

## Module map (`watchline/discovery/ingest/portfolio/`)

- **`splink_source.py`** — the core. Key functions:
  - `extract(conn, where="TRUE")` → one row per owner-contact **identity**
    (most-recent registration per BBL; no fan-out; raw + lightly-normalized fields;
    `biz_street_norm` = suffix-stripped; `first_initial`). `where` slices the pop.
  - `address_degrees(conn)` / `corp_degrees(conn)` / `name_freq(conn)` —
    **full-population** lookups feeding the guards below.
  - `fit(df, addr_degrees=None, ...)` → `(linker, preds)`; `cluster(linker, preds,
    threshold)` → clusters; `link(df)` = fit+cluster convenience.
  - `build_portfolios(df, clusters)` → resolved portfolios (entity, bbls, n_bbls).
  - `corp_owners_for(conn, bbls)` → corp co-owners on buildings (loop input).
  - `feedback_merge(df, clusters, corp_df, corp_deg, corp_cap=25, name_freq,
    name_cap=15)` → the loop pass; re-maps `cluster_id`.
- **`eval/`** — the gold-set harness:
  - `gold_set.csv` — 87 hand-adjudicated records (the artifact; edit it directly).
  - `build_gold.py` — regenerates the seed from adjudication rules.
  - `scorer.py` — pairwise precision/recall/F1 + FP/FN pair lists.
  - `run_eval.py` — fit + threshold sweep + score.
  - `run_loop.py` — pass 1 vs pass 2 (feedback merge) scored; suppression diagnostic.
- **`compare_kg.py`** — resolved portfolios vs the current KG (fragmentation diff).

## How to run

```bash
uv sync --extra ingest                 # once
uv run --extra ingest python -m watchline.discovery.ingest.portfolio.eval.run_eval
uv run --extra ingest python -m watchline.discovery.ingest.portfolio.eval.run_loop
uv run --extra ingest python -m watchline.discovery.ingest.portfolio.compare_kg
uv run --extra ingest python -m watchline.discovery.ingest.portfolio.eval.build_gold
```

## Data sources

- **`pg_conn()`** → local Postgres `justfixwow` on **:5434** (raw HPD tables:
  `hpd_contacts`, `hpd_registrations`, plus a `wow` schema). Needs `PG*` in `.env`.
  This is what the pipeline reads at runtime.
- **`neo4j_driver()`** → discovery KG (`Building`, `Portfolio`, `Landlord`).
- JustFix's own DB is available via the **`postgres-justfix` MCP** — for interactive
  investigation only, NOT reachable from the runtime pipeline.
- WoW's algorithm we're replacing: `/Users/rflagg/git-alt/who-owns-what/portfoliograph`.

## Current results (gold set, 87 records)

- Splink linkage (pass 1): **P 0.996 / R 0.76**. No different-person confusions;
  recall ceiling is cross-office.
- Feedback loop (pass 2): **recall 0.73 → 0.95** (Croman consolidates cross-office,
  `[120,6,1] → [126,1]`). Residual gold FP are rare-named operators the loop
  correctly bridges but the gold still labels office-separate — a labeling tail.
- `compare_kg`: Splink puts Croman's 120 buildings in 1 portfolio vs **4 in the KG**;
  Rashad's 220 in 1 vs **5**.

## The gold set

Person/operator-level labels. Hard cases baked in: Croman/Rashad **typos = merge**;
different-first-name namesakes = **don't**; aggregator-address decoys = **don't**;
two-office operators adjudicated by **corporate-umbrella evidence** (Castellano's
offices merged because Choice NY Management, a private manager, spans 40 of his
buildings — verified independently, not because the model merged them). To change a
call, edit `gold_set.csv` (or the rules in `build_gold.py::adjudicate`) then re-run.
**Never flip a label just because the model merged — verify evidence first.**

## Tuning decisions — and dead-ends (don't repeat these)

- **Aggregator addresses corrupt the model, not just the output.** A registered-agent
  office shared by many landlords poisons EM ("same address = weak") and *depresses*
  legitimate merges. Masking high-degree addresses (`AGGREGATOR_DEGREE=25`, computed
  **full-population** via `address_degrees`) was the single biggest lift (F1 0.23 →
  0.93). This is WoW's `MAX_ADDR_DEGREE`, done probabilistically.
- **Do NOT fold zip into a composite address key.** The raw business zip is noisy
  (one office filed under several zips); a composite `house+street+zip` split
  operators' own addresses and broke merging (recall → 0). Compare components; keep
  zip out or weak.
- **Street-suffix normalization** (`biz_street_norm`, strip STREET/AVE/…) fixed the
  `WEST 21ST` vs `WEST 21ST STREET` recall gap **without** loosening the fuzzy match
  (loosening the JW threshold *lowered* precision — the harness vetoed it).
- **First-initial gate** in blocking kills different-first-name-same-address FPs
  (ANDREA vs FILIPPO; DIVYA vs JAMAL).
- **Loop guards:** corp **degree-cap** (exclude registered-agent super-corps) +
  **name-rarity gate** (`name_cap=15`; targets sit at 5-11, common names 20-232).
  The rarity gate **subsumes** the ownership-vs-management distinction: for a rare
  name a shared *manager* is still one person; a common name is never corp-bridged.
- **Blocking:** never on `biz_zip` alone (208M candidate pairs — measured); name +
  house/street ≈ 3M pairs, ~1-2 GB DuckDB scratch. Run `count_num_comparisons_from_
  blocking_rule` before predicting.
- **Splink low-λ trap:** on a huge, mostly-unique population the estimated
  "probability two random records match" collapses and the model *under-merges even
  identical records*. Train on a denser slice (~2-3k) or set the prior.

## Not done / next steps

- **Address standardization** (Geosupport sidecar / libpostal) — the remaining
  quality lever; modest recall payoff (residual recall is cross-office = the loop).
- **Materialize resolved portfolios to the KG** (`Portfolio` nodes) so the app's
  "hidden operators" view uses the de-fragmented resolution. Writes to the live graph.
- **Wire `SplinkSource` as the source adapter into `pipeline.py`** (replace the
  `landlords_with_connections` read); currently runs standalone on slices.
- **Grow the gold set**; adjudicate the rare-name operators (Kadden, Rashad-scattered)
  that are the residual gold FP.
- **Full-population run** (currently sliced for the eval).

## Gotchas

- `extract()` passes **no** psycopg2 params (owner-roles inlined) so `LIKE '%'` /
  `%` (modulo) in a `where` stay literal — psycopg2 errors on mixed formats otherwise.
- Splink 4 term-frequency: `cl.X(...).configure(term_frequency_adjustments=True)`,
  **not** a constructor kwarg.
- EM is stochastic; a different random sample → a different model. Metrics vary
  run-to-run; sanity-check on a target (Croman should consolidate).
- `registrationid` is **not unique** in `hpd_registrations` (multi-building complexes
  repeat it). Always dedup to `(registrationid, bbl)`.
- `.DS_Store` / `__pycache__` are untracked here; stage files explicitly.
