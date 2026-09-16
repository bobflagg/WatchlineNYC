# Merging `entity-linking-prototype` → `main` — open issues before you do it

Working note (2026-09-12). The branch is **mechanically** merge-ready; the reasons to pause
are about *what a merge would publish* and the two-branch model — not conflicts or tests.

> Meta note: this file lives in `specs/`, which is itself one of the things a merge would
> publish (see #1). It's an internal planning doc — don't ship it.

## TL;DR

Don't merge as-is. The blocking decision is **#1 (publishing `specs/`)**. Resolve that + confirm
repo visibility (#5), then the merge is a one-line `.gitignore` conflict away.

## Reasons to hold off (prioritized)

1. **A merge publishes the entire `specs/` directory (26 files) + `EXTRACTION.md` to `main`.**
   `main` has no `specs/` today. If the repo is public (its Pages setup implies so), these become
   public on the default branch **without** the per-item publish decisions we made all along:
   - The four case studies (`case-escobar/miller/levitov/haight.md`) — the *internal, fuller*
     versions (raw reproduce queries, full traces, "anatomy of one edge" sections, named private
     individuals in more detail than the sanitized public case page).
   - Venue/strategy drafts: `nicar-pitch.md`, `cj-pitch.md`, `facct-abstract.md`,
     `paper-abstract.md`, `meetup-deck.md`, `meetup-qa-card.html` (has "SAY:" speaker lines).
   - Ownership-model design + roadmap: `ownership-model-spec`, `-layer-decision`, `-migration-plan`,
     `-phase0/1/2`, `cutover-readiness`, `roadmap.md`, `eval-protocol.md` — several document
     "not yet implemented / next build" status and honest limitations.
   - `watchline/discovery/ingest/portfolio/EXTRACTION.md` and `specs/wow-connected-by-splink/`.

   **Action:** decide `specs/` disposition per item — publish the ones you want public, and
   `gitignore`-keep-local the rest (the move we made for `CLAUDE.md`). The named case studies
   deserve the same per-item decision, not a bulk publish.

2. **`main` is the repo's public face + the Pages source.** Today a visitor sees a curated story
   (case file, maps, FAQ, contribution-first README). After a merge the default branch is dominated
   by the research pipeline internals — including the honest "accuracy eval not run yet" and the
   tuning-dead-end notes. Fine for a research repo; a real change in first impression.

3. **The two-branch separation looks intentional** (curated public `main` vs. research
   `entity-linking-prototype` — different READMEs, branch-only `specs/`). A merge collapses it.
   Decide the intended model: keep `main` curated and keep developing on the branch, **or** make the
   branch the mainline (then do #1 first).

4. **In-flight work becomes mainline.** The ownership-model migration is documented as "not yet
   implemented," plus `shadow_compare` / `cutover` experiments. Normal for research — just note WIP
   is going into `main`.

5. **UNVERIFIED: repo visibility (public vs private).** `gh` was unavailable this session, so I
   couldn't confirm. If public, #1/#2 matter a lot; if private, mostly about collapsing the
   internal/external split. **Confirm** in GitHub repo Settings or `gh repo view --json visibility`.

## Already resolved this session (mechanical prep is done)

- Hermetic suite **green**: 1150 passed / 22 skipped (fixed by scoping the cypher-guard coverage test
  to exclude the `watchline/discovery/ingest/` write path — commit `edda6b5`).
- `graphdatascience>=1.22` dep + `uv.lock` **committed** (`ca2ff66`); `uv lock --check` passes.
- `eval_out/` **gitignored** (`a212176`) — incl. `eval_out/blinding_key.jsonl`, which must NEVER be
  committed (blind-eval integrity). Also ignores root `portfolio-defragmentation-*.html` and
  `ignore-this-folder/`.
- Both `CLAUDE.md` files **untracked + gitignored** (kept local): `2739a33`, `e20f1f1`.
- Only remaining **merge conflict**: a one-line `.gitignore` clash (the CLAUDE.md ignore region;
  the branch also adds `eval_out/`). On merge, take the **branch's** version — it's a superset.
- `deploy/.env.example` deliberately **left uncommitted** — it holds local, non-template values
  (a real `DISCOVERY_GDRIVE_ID` and a non-default model). Don't ship it; move those to your local
  `.env` and revert the example if you want a clean tree.
- Untracked `.claude/` left alone (Claude Code local dir; some repos gitignore it — your call).

## Re-check commands (when you come back to this)

```bash
# What a merge would publish under specs/ (should be curated first):
git diff main...entity-linking-prototype --name-only -- specs/

# Confirm the only conflict is still .gitignore:
git merge-tree --write-tree --name-only main entity-linking-prototype   # exit 1 + lists .gitignore

# Confirm suite still green and lock consistent:
uv run pytest -q && uv lock --check

# Repo visibility:
gh repo view --json visibility,isPrivate,nameWithOwner
```

## Divergence snapshot (as of 2026-09-12)

- Branch **177 commits ahead** of `main`; `main` **23 ahead** (the docs/Pages commits published via
  worktree, whose content is mirrored onto the branch).
- Merge brings ~**137 files / ~20.7k lines** of pipeline code into `main`.
