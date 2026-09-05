# Reviewer-Assist Tool — Repo Structure & Data Contract

The eval splits cleanly into two independently-built halves joined by a small file contract:

- **WatchlineNYC side** (this repo) — knows the pipeline. Draws the stratified pairs, keeps the
  answer key, scores the returned annotations.
- **`owner-review`** (its own repo, shareable) — knows *nothing* about our pipeline. A generic
  ACRIS/DOS/HPD **dossier viewer + blind-annotation app** over a records Postgres. Reusable on its
  own as a records viewer for journalists.

The seam is three JSONL files. See [`eval-protocol.md`](eval-protocol.md) for the methodology this
implements (strata, C1/C2 classes, the circularity ruling).

## Flow

```
WatchlineNYC  sample.py ──► review_queue.jsonl ─────────────► owner-review (annotators)
              (draws pairs) │                                        │
              keeps ────────┤  blinding_key.jsonl (PRIVATE)          │ export_annotations.py
                            └  frame_manifest.json (PRIVATE)         ▼
WatchlineNYC  score.py ◄──────────────────────────────────── annotations.jsonl
              = join(annotations, blinding_key) ─► strict/inclusive precision, κ, McNemar, C2 share
```

**Blinding architecture (the key never leaves WatchlineNYC).** `owner-review` receives *only*
`review_queue.jsonl` — no stratum, no signal, no system decision, no expected label. It cannot leak
what it never holds. Class C1/C2 (§1 of the protocol) is assigned by `score.py` on the WatchlineNYC
side, by rejoining the returned annotations with the private key. This is a stronger blind than
"the frontend hides a field."

---

## Data contract

### 1. `review_queue.jsonl` — WatchlineNYC → tool (blinded)

One pair per line. Everything the annotator legitimately judges on; nothing that could cue the answer.

```json
{
  "pair_id": "P0001",
  "a": {"ref": "A", "name": "MOBUN YIP",   "bbls": ["4054140033"]},
  "b": {"ref": "B", "name": "JAN HOW KANG", "bbls": ["4054140034"]}
}
```

- `pair_id` — opaque, stable, carries no ordering information (shuffle before numbering).
- `a` / `b` — the two entities; `ref` is a neutral label shown in the UI, `name` the display name,
  `bbls` the buildings. The tool derives everything else (deeds, LLC names → DOS, HPD contacts) from
  the bbls — it is **not** told "the linking deed"; it shows *all* records and the annotator finds
  the link. `a`/`b` order is randomized so it encodes nothing.
- **Absent by design:** stratum, signal, `watchline`/`wow` decision, anchor membership.

### 2. `annotation.jsonl` — tool → WatchlineNYC

One line per (pair, annotator).

```json
{
  "pair_id": "P0001", "annotator_id": "ann_2",
  "label": "SAME",
  "evidence_tiers": ["T1"],
  "c2_checks": {"entity_identity": true, "successor_reality": true, "restructuring_not_sale": true},
  "rationale": "2018 joint deed LIBERTY 162 → both; LIBERTY is grantor of both single-purpose successors",
  "duration_ms": 184000, "ts": "2026-09-10T14:22:03Z"
}
```

- `label` — `SAME` | `DIFFERENT` | `INDETERMINATE`.
- `evidence_tiers` — the tier(s) the call rests on (T1 deed / T2 DOS / T3 HPD-or-other / T4 external).
  Multi-valued; this is what lets `score.py` assign C1 vs C2 (C2 = the only tier is the deed **and**
  the system's signal was the deed; C1 = any tier other than the system's signal's record).
- `c2_checks` — **required and hard-gated by the tool** whenever `label=SAME` rests on a *single*
  deed source (only `T1`). Missing any check ⇒ the tool records `INDETERMINATE`. Signal-agnostic, so
  blinding holds: the tool doesn't know the system used the deed, it just demands deed-verification
  whenever a SAME stands on a deed alone.
- `rationale`, `duration_ms`, `ts` — audit + quality signal.

### 3. `blinding_key.jsonl` — WatchlineNYC-**private** (never sent to the tool)

```json
{"pair_id": "P0001", "stratum": "S1b_linked_successor",
 "signal": "acris-deed", "watchline": "SAME", "wow": "DIFFERENT",
 "anchor": null}
```

Plus `frame_manifest.json` (preregistration): `as_of_date`, `pipeline_git_sha`, sampling `seed`, and
per-stratum `{frame_size, n}` — frozen before adjudication.

---

## `owner-review` repo (standalone, no `watchline` dependency)

```
owner-review/
  README.md
  pyproject.toml                # web framework + a Postgres driver only
  owner_review/
    config.py                   # RECORDS_DSN (Postgres: ACRIS/HPD/DOS/PLUTO) · STORE_PATH (SQLite)
    records/                    # READ-ONLY primary-record assembly — no system heuristics, ever
      buildings.py              #   building facts + co-op/condo flag (HPD contactdescription)
      deeds.py                  #   full ACRIS conveyance chain per bbl (master/legals/parties)
      hpd.py                    #   HPD registration contacts per bbl
      dos.py                    #   DOS entity lookup by LLC name (thin; surfaces the caveats)
      dossier.py                #   assemble an entity dossier from the above — ALL records, no "match"
    review/
      queue.py                  #   load review_queue.jsonl
      store.py                  #   append-only SQLite annotation store (immutable log)
      gate.py                   #   enforce: SAME on a lone deed ⇒ the 3 C2 checks required
      app.py                    #   web app: one pair at a time, dossier + capture, independent sessions
    web/                        #   frontend (templates/static or a light SPA)
    schema/                     #   review_queue.schema.json · annotation.schema.json
  data/                         # gitignored: imported queue + the annotation SQLite
  scripts/
    import_queue.py             #   load review_queue.jsonl
    export_annotations.py       #   dump annotations.jsonl for WatchlineNYC scoring
```

**Hard invariants for `owner-review`** (what keeps it "assist not replace"):
- Never receives or stores the blinding key, the stratum, the signal, or the system decision.
- `records/` reads primary records only; it must **not** import or reuse any WatchlineNYC matching
  logic (splink/deed/aggregator) to organize the view — that would smuggle the inference back in.
- The dossier shows *all* records for both entities; it never labels "the match," never suggests a
  label, never shows a model/confidence score, and never shows one annotator another's judgment.

## WatchlineNYC side (this repo)

```
watchline/discovery/ingest/portfolio/eval/
  sample.py     # draw stratified pairs from the graph → review_queue.jsonl + blinding_key.jsonl + frame_manifest.json
  score.py      # join(annotations.jsonl, blinding_key.jsonl) → per-stratum strict & inclusive
                #   precision (Wilson CIs), coverage, C2 share, κ, McNemar vs WoW, recall on anchors
```

### Proposed strata for `sample.py` (confirm before freezing)

Updated for what the diligence taught us (co-op/condo, the linked-successor recoveries):

| Stratum | Frame | n |
|---|---|---|
| **S1a deed (held)** | `CONNECTED_BY_DEED` from a still-latest joint deed | 120 |
| **S1b deed (linked-successor)** | `CONNECTED_BY_DEED` recovered via the restructuring guard — the novel, riskiest claim; its own stratum | 120 |
| **S2 model** | `CONNECTED_BY_SPLINK` method `splink-fellegi-sunter` | 150 |
| **S3 precision-hygiene** | pairs the system **declined/dropped** — co-op/condo-excluded and aggregator-masked — test they are genuinely *not* one rental owner | 120 |
| **S4 hard negatives** | same surname or address, not merged (over-firing guard) | 120 |

Recall anchors (not sampled) per §2/§ recall — **re-vetted** for co-op/condo / institutional /
nonprofit contamination before use (see [`recall-anchors.md`](recall-anchors.md)).

---

**Build order.** The two repos can proceed in parallel once this contract is frozen: `owner-review`
needs only `review_queue.schema.json`; WatchlineNYC's `sample.py`/`score.py` need only the queue and
annotation shapes above. `owner-review`'s `records/` layer (the dossier) is the long pole and the
reusable asset — build it first, against real bbls, verifying every assembled view links out to the
ACRIS/DOS/HPD source.
