# Off-eval review queue — Escobar/Espinal (case B)

A single illustrative pair (`PB01`) for the Escobar/Espinal 12-building portfolio
(`PF-20260901T165123Z-44544`), split along WoW's own fracture line:

- **Side A** — 8 buildings WoW files as portfolio `#50057` (PO Box 370, Manhattan)
- **Side B** — 4 buildings WoW files as portfolio `#44728` (374 McLean Ave, Yonkers)

The reviewer is asked, blind, whether A and B are the same owner. WatchlineNYC
merges them (SAME); WoW splits them (DIFFERENT).

## NOT part of the eval

This pair is **not** in the frozen, preregistered sample (`eval_out/review_queue.jsonl`,
SEED=42). It was hand-constructed for a demo/walkthrough. **Do not fold its result
into any precision/recall number** — folding hand-picked pairs into the metrics
would bias them. Present it only as a labeled anecdote, reviewed the same blind way.

## Review it (separate queue AND separate store, so nothing mixes)

```bash
cd ../../owner-review   # the owner-review repo
REVIEW_QUEUE=/absolute/path/to/eval_out/offeval/review_queue.jsonl \
OWNER_REVIEW_STORE=data/offeval.sqlite \
  uvicorn owner_review.review.app:app --port 8020
# then open http://127.0.0.1:8020/pair/PB01?annotator=demo
```

`OWNER_REVIEW_STORE=data/offeval.sqlite` keeps these annotations out of the eval
store. `RECORDS_DSN` (the records dump) must be set in `owner-review/.env` as usual.

## Score / label (off-eval)

Rejoin `blinding_key.jsonl` here by hand — it records `watchline=SAME`,
`wow=DIFFERENT`, the two WoW portfolio ids, and the signals. There is no automated
scoring for this directory on purpose.
