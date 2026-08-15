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
  - `fit(df, addr_degrees=None, ...)` → `(linker, preds)`; `link(df)` = convenience.
    Internals factored into `_mask_aggregators` / `_settings` / `_train_linker` so
    every fit path masks and blocks identically.
  - `cluster_gated(preds, nodes, threshold, name_freq=None, name_cap=15)` → clusters
    with TWO precision vetoes before connected-components: (a) first-name — drop
    `gamma_first_name==0` edges (genuine first-name disagreement); (b) common-name
    (when `name_freq` passed) — drop edges where the name is common (> `name_cap`
    identities) AND the normalized addresses differ (`_addr_key`). **The clusterer to
    use**; `cluster(linker, preds, thr)` is the ungated Splink path, kept for comparison.
  - `fit_predict_full(train_df, full_df, addr_degrees=None, ...)` → train on a dense
    slice, predict over the full population (dodges the low-λ trap; `save_model_to_json`
    → reload onto a full-pop Linker). This is the full-run entry point.
  - `build_portfolios(df, clusters)` → resolved portfolios (entity, bbls, n_bbls).
  - `corp_owners_for(conn, bbls=None)` → corp co-owners on buildings (loop input);
    `bbls=None` = every building (the full run; avoids a 170k-element array param).
  - `feedback_merge(df, clusters, corp_df, corp_deg, corp_cap=25, name_freq,
    name_cap=15)` → the loop pass; re-maps `cluster_id`.
- **`eval/`** — the gold-set harness:
  - `gold_set.csv` — 105 hand-adjudicated records (the artifact; edit it directly).
  - `build_gold.py` — regenerates the seed from adjudication rules (`TARGET_WHERE`,
    `NBR_WHERE`, `OFFICE_WHERE`). Stays in sync with the CSV — regenerating is safe.
  - `scorer.py` — pairwise precision/recall/F1 + FP/FN pair lists.
  - `run_eval.py` — fit + threshold sweep + score (on the ~2.8k slice).
  - `run_loop.py` — pass 1 vs pass 2 (feedback merge) scored; suppression diagnostic.
  - `run_full.py` — the **full-population run**: train-on-slice/predict-on-full,
    gold sweep, feedback loop, a diff-surname **precision guard** the gold can't give,
    and a `portfolios.parquet` export. Deterministic training slice.
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

## Current results (gold set, 105 records)

- **Slice** (eval harness, ~2.8k records): pass 1 **P 0.996 / R 0.735**; loop pass 2
  **R → 0.954**, Croman `[120,6,1] → [126,1]`. The 1 pass-1 FP is the Kadden
  490/504-Myrtle labeling tail (same person, gold labels office-separate).
- **Full population** (`eval/run_full.py`, ~55s): 145,412 person identities →
  **123,215 resolved portfolios**. Croman = one 127-bbl portfolio, Rashad one
  226-bbl, Valiotis's 27 typo variants collapse into one. **At population scale
  term-frequency alone consolidates cross-office rare names, so the feedback loop is
  largely redundant** (pass 2 ≈ pass 1). Precision guard (below) = **0** clusters
  with >1 surname.
- **Blocking is now NAME-ANCHORED** — the old address-only rule was a population-scale
  precision hole (fused 2,044 different-surname office-mate clusters); dropping it
  zeroed those out at no recall cost. See "Tuning decisions".
- **First-name-compatibility veto** (`cluster_gated`): fixed the same-surname /
  same-office / different-first-name leak — JACOB vs JOSEF GUTMAN now split (2
  clusters), STEVE/STEVEN & ZACH/ZACHARY kept. At full scale it split ~1,200
  different-person blobs (diff-first-name clusters 3,028 → 1,837). See "Tuning".
- **Common-name veto** (`cluster_gated(name_freq=...)`): fixed the last known leak —
  an exact common name repeated at a *different* address (two unrelated JIN CHENs)
  merging on name alone. Investigation showed the "leak" was mostly benign: of ~4,300
  common-name clusters only **252 spanned truly-distinct addresses** (the rest were
  same-address formatting artifacts the model *correctly* merged). The veto drops those
  252 (guard = 0) while preserving artifacts and all 6,508 rare-name cross-office
  merges. See "Tuning".
- `compare_kg`: Splink puts Croman's buildings in 1 portfolio vs **4 in the KG**;
  Rashad's in 1 vs **5**.

## The gold set

Person/operator-level labels (105 records). Hard cases baked in: Croman/Rashad
**typos = merge**; different-first-name namesakes = **don't**; aggregator-address
decoys = **don't**; two-office operators adjudicated by **corporate-umbrella evidence**
(Castellano's offices merged because Choice NY Management, a private manager, spans 40
of his buildings — verified independently, not because the model merged them);
**shared-office co-mates** (14 different landlords at 223 & 18 Spencer St, incl. JACOB
vs JOSEF GUTMAN) = **don't** — the population failure mode the rare-surname gold
couldn't see (`OFFICE_WHERE` in `build_gold.py`). To change a call, edit `gold_set.csv`
(or the rules in `build_gold.py::adjudicate`) then re-run. `build_gold.py` stays in
sync with the CSV, so regenerating is safe.
**Never flip a label just because the model merged — verify evidence first.**

## Tuning decisions — and dead-ends (don't repeat these)

- **Aggregator addresses corrupt the model, not just the output.** A registered-agent
  office shared by many landlords poisons EM ("same address = weak") and *depresses*
  legitimate merges. Masking high-degree addresses (`AGGREGATOR_DEGREE=25`, computed
  **full-population** via `address_degrees`) was the single biggest lift (F1 0.23 →
  0.93). This is WoW's `MAX_ADDR_DEGREE`, done probabilistically.
- **NAME-ANCHORED blocking (the full-population precision fix).** The full run exposed
  what the slice gold structurally could not: an address-only blocking rule
  (`block_on(biz_house, biz_street_norm, first_initial)`) scores **different-surname**
  office-mates, and for a non-aggregator shared office (degree ≤ 25) the exact-address
  match overpowers the surname mismatch — **2,044 clusters fused different people**
  (JOEL BRAVER + JACOB GUTMAN at one address). Dropping that rule so linkage blocks
  only on `(last_name, first_initial)` zeroed those out at **zero** recall cost
  (targets consolidate via the name rule + TF; gold P/R unchanged). Cost: surname-
  *typo* pairs are no longer candidates. **Do NOT re-add an address-only block** —
  recover surname-typo recall (if it ever matters) with a name-agreeing block. The
  `run_full` precision guard (diff-surname clusters, target 0) watches for regressions.
- **First-name-compatibility veto (`cluster_gated`).** Name-anchoring stopped
  different-*surname* merges; this stops same-surname / same-office / *different-first-
  name* ones (JACOB vs JOSEF GUTMAN — different people; exact surname + exact address
  otherwise beat the first-name difference). Splink already scores a first-name level
  per pair — `gamma_first_name == 0` is "both present, Jaro-Winkler below the lowest
  threshold" = genuine disagreement. Dropping those edges before connected-components
  splits GUTMAN while keeping gamma ≥ 1 variants (STEVE/STEVEN, ZACH/ZACHARY, the
  EFSTATHIOS/EFSTAHIOS typo) and null-first-name pairs. Slice P 0.991 → 0.996 at no
  recall cost; full-pop diff-first-name clusters 3,028 → 1,837. Trade-off: true
  nicknames that aren't near-matches (ABE/ABRAHAM) won't bridge — precision-first.
- **Common-name veto (`cluster_gated(name_freq=...)`).** An exact common full name at a
  *different* address (two unrelated JIN CHENs) merges on name alone — TF under-
  penalizes the coincidence. Drop an edge when the name is common (> `name_cap`=15
  distinct identities, from `name_freq`) AND the normalized addresses differ
  (`_addr_key` = digits-house + suffix-normalized street). Key subtlety: use the exact
  address KEY, not Splink's `gamma_biz_house`, which is lenient by design (Levenshtein
  ≤2, to catch Croman's "4"/"424" typo) and so treats "9411"/"9415" as a near-match.
  The rarity gate protects rare cross-office merges (Croman ~8 ≪ cap); the address key
  preserves same-address formatting variants (140-06 == 14006). Robust across cap
  15–60 (leak names like CHEN sit at ~230). Same name-rarity philosophy as the loop's
  `name_cap`, applied to the base linkage — coherent stance: common names merge only at
  one address; rare names merge across addresses (TF + the corp-bridge loop).
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
- **Blocking:** never on `biz_zip` alone (208M candidate pairs — measured). The
  name-anchored rule `(last_name, first_initial)` generates only **~600k** pairs over
  the full 145k population (the first-initial gate keeps it tiny) — the whole full run
  is ~55s in-memory. Use `splink.blocking_analysis.count_comparisons_from_blocking_rule`
  to size a rule (Splink 4 renamed it off the linker).
- **Splink low-λ trap:** on a huge, mostly-unique population the estimated
  "probability two random records match" collapses and the model *under-merges even
  identical records*. Fixed by `fit_predict_full`: train m/u/λ on a dense slice (~2-3k),
  transfer the model to a full-pop Linker for prediction (TF recomputes over the full
  pop = population-correct name rarity). Transferring the slice's λ wholesale slightly
  over-merges, but it's the office-mate blocking, not λ, that drove the real errors.

## Not done / next steps

- **Full-population run — DONE** (`eval/run_full.py`): 145k identities → 123k
  portfolios, precision-guard clean (0 diff-surname clusters), Croman/Rashad
  consolidate. This clears validation-gate #1/#2 in `EXTRACTION.md`.
- **Precision leaks — all known ones now fixed** by `cluster_gated` (different-surname
  office-mates via name-anchoring, GUTMAN via the first-name veto, common-name cross-
  address via the common-name veto). Only genuinely-indistinguishable residuals remain
  (two different people with the SAME common name at the SAME exact address — no signal
  separates them; rare). Optional follow-up: adjudicate a few common-name cases with
  deed evidence and add them to the gold, so the slice harness tests the veto too (the
  `run_full` guard already watches it at population scale). NOTE: the common-name veto
  trades a small recall cost — a common-named operator with buildings at several
  addresses is NOT consolidated unless rare; consistent with the loop's `name_cap`.
- **Materialize resolved portfolios to the KG** (`Portfolio` nodes) so the app's
  "hidden operators" view uses the de-fragmented resolution. Writes to the live graph.
  `run_full` already exports `portfolios.parquet` — the hand-off surface.
- **Wire `SplinkSource` as the source adapter into `pipeline.py`** (replace the
  `landlords_with_connections` read); currently runs standalone on slices.
- **Address standardization** (Geosupport sidecar / libpostal) — modest recall payoff.
- **Grow the gold set** further; the feedback loop is largely subsumed by TF at full
  scale (pass 2 ≈ pass 1) — reconsider whether it earns its complexity.

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
