# Extraction plan — carve the linkage pipeline into a standalone repo

**Status: not yet — a decision banked, not an action.** This records *how* and
*when* to lift the entity-linking + portfolio-construction pipeline out of
WatchlineNYC into its own shareable repo. Read alongside [`CLAUDE.md`](./CLAUDE.md)
(the working notes). Nothing here changes until the validation gate below clears.

## Why a separate repo

The goal is to **share the technique** — let a JustFix dev, a housing researcher,
or another city run this linkage against a plain Postgres HPD dump (eventually just
the public CSVs) and reproduce the resolution, **without standing up a Neo4j graph
of 10s of millions of nodes**. That's a much cleaner artifact than "check out a
branch of my app and run a buried submodule," and it's citeable (own license, own
README, the gold set as a benchmark).

The key enabling fact — verified in the coupling audit below — is that **the
technique does not depend on the KG at all**. Only the *comparison* to Watchline's
existing portfolios does.

## The coupling audit (the clean seam)

Grep of `from watchline.shared.connections import …` across this directory:

| File | Uses `pg_conn` | Uses `neo4j_driver` / `NEO4J_*` | Travels to the standalone repo? |
|------|:---:|:---:|---|
| `splink_source.py` (**the core**) | — (takes `conn` as a param) | no | **yes** — already decoupled |
| `eval/build_gold.py` | yes | no | **yes** |
| `eval/run_eval.py` | yes | no | **yes** |
| `eval/run_loop.py` | yes | no | **yes** |
| `eval/scorer.py` | no (pure) | no | **yes** |
| `compare_kg.py` | yes | **yes** | **no** — stays in Watchline |
| `pipeline.py` | yes | **yes** | **no** — the old WoW/GDS KG build |
| `algorithms.py` | no | **yes** | **no** — GDS WCC/Louvain |

So the split is already latent in the code: `splink_source.py` + `eval/` are the
KG-free technique (only need Postgres); the three KG-coupled files are the
Watchline integration and the legacy build. The **only** coupling to sever for the
core is a single `pg_conn` import in the eval scripts.

## Validation gate — extract only after all three

Don't pay the extraction overhead while the approach is still unproven:

1. **Full-population run** works (currently sliced for the eval) — see CLAUDE.md
   "Not done".
2. Metrics hold at population scale (precision-first; the Croman/Rashad
   consolidation still lands).
3. Ideally a **JustFix read** of the technique, since they're a target consumer.

Until then the `entity-linking-prototype` branch is the right holding pen. Keep the
coupling thin (it already is) so extraction stays a half-day job.

## What moves

Copy into the new repo (proposed name: `nyc-landlord-resolution`):

```
nyc-landlord-resolution/
  src/nlr/
    splink_source.py        # verbatim — the core, already conn-parametric
    db.py                   # NEW — the pg_conn shim (replaces watchline.shared.connections)
    eval/
      __init__.py
      build_gold.py         # swap the pg_conn import to nlr.db
      run_eval.py           #   "
      run_loop.py           #   "
      scorer.py             # verbatim — pure
      gold_set.csv          # the 87-record artifact — travels as-is
  pyproject.toml            # standalone; splink/psycopg2/duckdb are MAIN deps now
  README.md                 # load data -> run -> eval -> export
  CLAUDE.md                 # copy the working notes; drop the KG-diff paragraphs
  LICENSE                   # own license (e.g. MIT) for shareability
```

The three imports to rewrite: `from watchline.shared.connections import pg_conn`
→ `from nlr.db import pg_conn` in `build_gold.py`, `run_eval.py`, `run_loop.py`.
Nothing else in the core references Watchline.

## What stays in Watchline

- `compare_kg.py`, `pipeline.py`, `algorithms.py` — the KG diff, the old
  WoW-consuming GDS build, and its algorithms. These are Watchline-specific.
- Watchline gains a **thin consumer**: read the pipeline's exported portfolios and
  materialize `Portfolio` nodes (see "Integration boundary").
- Options for how Watchline gets the code: (a) `pip install nyc-landlord-resolution`
  as a dependency and call `build_portfolios`; or (b) fully decouple — the
  standalone tool writes a portfolios export (CSV/parquet) and Watchline's ingest
  reads that file. **(b) is cleaner** and is the recommended boundary.

## The `pg_conn` shim (`src/nlr/db.py`)

Cuts the one Postgres coupling with ~10 lines, env-driven, no Watchline import:

```python
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def pg_conn():
    """Connection to a Postgres holding the HPD contact/registration tables."""
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5434"),
        dbname=os.environ.get("PGDATABASE", "justfixwow"),
        user=os.environ.get("PGUSER", ""),
        password=os.environ.get("PGPASSWORD", ""),
    )
```

(Mirror the real body of `watchline/shared/connections.py::pg_conn` when copying.)

## Standalone `pyproject.toml`

The deps that are an *optional* `ingest` extra inside Watchline become the repo's
**core** deps — that's the whole point of this project:

```toml
[project]
name = "nyc-landlord-resolution"
requires-python = ">=3.13"
dependencies = [
    "splink>=4.0.16",
    "psycopg2-binary>=2.9.12",
    "duckdb>=1.0",       # transitive via splink today; make explicit for the DuckDB-native path
    "pandas>=2.0",
    "python-dotenv>=1.0",
]
```

## README skeleton

1. **What it does** — probabilistic record linkage (Splink/Fellegi-Sunter) +
   a corporate-co-owner feedback loop that de-fragments NYC landlord portfolios;
   the Croman-4→1 / Rashad-5→1 story.
2. **Data** — point at a Postgres with HPD `hpd_contacts` + `hpd_registrations`
   (load via WoW's loader, or a provided dump). Set `PG*` in `.env`.
3. **Run** — `uv run python -m nlr.eval.run_eval` / `run_loop`.
4. **Evaluate** — the gold set + `scorer`; the P/R/F1 numbers.
5. **Export** — resolved portfolios out to CSV/parquet for downstream consumers.
6. **Guards & gotchas** — port the aggregator-masking / zip / first-initial /
   name-rarity lessons from CLAUDE.md (they're the reproducibility-critical bits).

## North star — DuckDB-native, no Postgres at all

The maximally shareable form drops Postgres too: DuckDB reads the **public HPD
open-data CSVs** directly, so the repo becomes `pip install` → point at CSVs → run.
No DB, no KG, trivially reproducible — the ideal artifact for "share the technique."

This is a real refactor, not day one: `EXTRACT_SQL` is Postgres-flavored
(`DISTINCT ON`, `regexp_replace`, `array_agg`, `= ANY(ARRAY[...])`). DuckDB's SQL is
close but not identical — `DISTINCT ON` and `array_agg` exist; audit the regex and
`ANY` forms. Do it as a **follow-on milestone** after the Postgres-first extraction
proves out. Keep `duckdb` an explicit dep now so the path is open.

## Integration boundary with Watchline (stays thin)

The pipeline **produces** resolved portfolios; Watchline **consumes** them:

```
nlr:  extract -> fit -> cluster -> build_portfolios -> feedback_merge
                                                     -> portfolios.parquet   (export)
watchline: read portfolios.parquet -> materialize Portfolio nodes in the KG
           (compare_kg.py stays here as the drift check)
```

That's the entire surface. Separate repos, one file passed between them — no code
coupling, so the standalone repo never needs Neo4j and Watchline never needs Splink.

## Extraction checklist (when the gate clears)

- [ ] Init `nyc-landlord-resolution`; add LICENSE + `pyproject.toml` above.
- [ ] Copy `splink_source.py`, `eval/*` (incl. `gold_set.csv`) into `src/nlr/`.
- [ ] Add `src/nlr/db.py` shim; rewrite the 3 `pg_conn` imports.
- [ ] Copy `CLAUDE.md` → repo root; strip the KG-diff / `compare_kg` paragraphs.
- [ ] `uv sync`; confirm `run_eval` + `run_loop` reproduce the P/R/F1 numbers.
- [ ] Write README from the skeleton above.
- [ ] In Watchline: add the export-consumer that materializes `Portfolio` nodes;
      keep `compare_kg.py` / `pipeline.py` / `algorithms.py` as-is.
- [ ] (Follow-on) DuckDB-native path: port `EXTRACT_SQL`, drop the Postgres dep.
```
