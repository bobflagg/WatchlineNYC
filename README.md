![Watchline NYC — Discovery](header.png)

Watchline is **accountability infrastructure for New York City housing** — it helps
journalists, tenant advocates, watchdog agencies, and the public investigate housing
conditions and ownership accountability using evidence from the city's public record.

It builds on the foundational work of [JustFix](https://www.justfix.org/en/) and its Who
Owns What (WoW), and pushes past the limits every registration-based ownership tool
inherits. WoW builds a landlord's portfolio as a connected component of a graph over
shared registration **names** and **addresses** — which fails in two opposite directions:
it **splits** one owner into many, and it **merges** many owners into one. This README
walks the same arc as the [talk](https://bobflagg.github.io/WatchlineNYC/docs/meetup/):
resolve the false splits, resolve the false merges, then make all of it answerable in
plain English.

Every ownership link is labeled **sourced or inferred** — a lead to verify, never a legal
determination. *(The groupings below are algorithmic inferences from public records.)*

## 1 · Resolving false splits — `CONNECTED_BY_SPLINK`

**The false split:** one owner, filed under dozens of differently-named LLCs — or one
office address typed a dozen inconsistent ways — fractures into many separate portfolios.
WoW links only on an *exact* name or address match, so a one-character typo
(`4 WEST 51` vs `424 WEST 51`) is enough to break a real portfolio in two.

**The fix:** probabilistic record linkage with
[Splink](https://moj-analytical-services.github.io/splink/). Match an owner across name
and address variants, add a `CONNECTED_BY_SPLINK` edge between the records that are the
same party, and recompute the components — the portfolio comes back whole. Precision-first:
it reunites variants without ever fusing two different people.

Two interactive comparison maps show it — toggle between Who Owns What and Watchline,
hover a building for detail:

- **[Croman — 127 buildings, one owner](https://bobflagg.github.io/WatchlineNYC/docs/maps/croman.html):**
  Watchline unifies Steven Croman's 127 buildings that Who Owns What splits across six
  portfolios on a one-character address typo.
  ([Full de-fragmentation analysis](https://bobflagg.github.io/WatchlineNYC/docs/cases/croman.html) —
  WoW's six portfolios reunited into one.)
- **[Escobar — 26 buildings, one owner split in two](https://bobflagg.github.io/WatchlineNYC/docs/maps/escobar.html):**
  Ramon Escobar's single Bronx office is filed a dozen inconsistent ways (misspellings, and
  two records with a blank ZIP), and Who Owns What links only on an *exact* address match — so
  his Bronx portfolio fractures in two. Watchline keeps all 26 buildings together as one owner.
  ([Full node-fragmentation analysis](https://bobflagg.github.io/WatchlineNYC/docs/cases/escobar.html) —
  why the raw table holds five nodes.)

## 2 · Resolving false merges — the beneficial owner group (`CONNECTED_BY_DEED`)

**The false merge:** Who Owns What groups many separate owners as one because their LLCs
share a registration office. One rule fixes it — *don't ask one signal two questions*: a
shared office tells you what a building **operates through**, never who **owns** it.

**The fix:** resolve ownership as its own community — the **beneficial owner group** — built
only from ownership signals (record linkage and deeds) and never from a shared address. Drop
the address edge, recompute the components, and a shared-office over-merge dissolves back into
the distinct owners it always was.

`CONNECTED_BY_DEED` is the second ownership signal in that community. Built from the ACRIS
record, it catches what registrations hide — the shell game's signature move: buy a block
together, then re-deed each building into its own `$0` single-purpose LLC — and it holds a
genuine owner group together when nothing else does: strip the deed and the group shatters
into the separate registrants it was filed as.

- **[Correcting an over-merge — one office, seven owners](https://bobflagg.github.io/WatchlineNYC/docs/maps/miller.html):**
  Who Owns What groups 27 buildings as a single owner because they share one registration
  office in Lakewood, NJ; Watchline **separates** them into the seven distinct owners they
  actually are — a more accurate, disaggregated view of the same public records.
  ([Full over-merge analysis](https://bobflagg.github.io/WatchlineNYC/docs/cases/miller.html) —
  the shared office, and why the seven owners stay apart.)
- **[The deed holds an owner group together](https://bobflagg.github.io/WatchlineNYC/docs/maps/citadel.html):**
  Fifteen Brooklyn buildings, one 2008 deed, and twelve `$0` shells that share only a masked
  aggregator office Watchline ignores. Toggle the deed off and the owner group shatters into
  three registrants; toggle it on and it resolves to the single owner it is — the deed is
  precisely the edge you need where you refused to trust the address.

## 3 · Making the data accessible

On top of the graph sits a **conversational interface** so anyone can ask a question in plain
English and get an evidence-based, cited answer. The AI is an **orchestrator, not a reasoner**:
it turns a question into structured queries, retrieves evidence from the knowledge graph,
applies the reliability rules, and explains the result — it never asserts anything the records
don't. If you don't trust the AI, ignore it and read the sourced records it points you to.

A [live demonstration](https://bobflagg.github.io/WatchlineNYC/) — a **referral-ready case
file** on landlord Steven Croman — is assembled from the Watchline knowledge graph: one owner
resolved across 115 differently-named LLCs into a 127-building portfolio, the conditions and
court record across it, and the public enforcement history. Ownership links are labeled
*inferred* (leads to verify, not legal determinations); conditions and enforcement figures are
directly sourced public records.

Four worked [**case studies**](https://bobflagg.github.io/WatchlineNYC/docs/cases/) show the
owner-identity layer deciding in **both** directions. It *merges* owners Who Owns What splits — one
fractured by brittle address matching (Escobar — 26 buildings reunited), and one held together by
nothing but a shared ACRIS deed (AXL — a Flushing pair that reads as two owners but was one 2015
purchase, re-titled into two `$0` shells). And it *declines* to merge parties that share only an
office (Miller — one Lakewood suite, seven owners) or a managing agent (Levitov — one operator,
five separate owners). Together they are the answer, in data, to *"doesn't it just merge
everything?"* — every ownership link labeled an inference to verify, not a legal determination.

New to the project or skeptical of the approach? The
[**FAQ**](https://bobflagg.github.io/WatchlineNYC/docs/faq/) gives straight answers on what the
knowledge graph adds over SQL, how the AI is (and isn't) used, how accurate it is, and how ownership
links are inferred — with the honest limits stated plainly.

## Run it locally

Watchline is a Streamlit app over a Neo4j knowledge graph, with a Geosupport sidecar
for address lookups. To run it on your own machine you need access to the graph and
an Anthropic API key.

**Prerequisites**

- An **Anthropic API key** — the app prompts for it on first load if it isn't already
  set (see *API keys* below). A **Tavily API key** is optional and enables web search
  during deep investigations.
- The **discovery knowledge graph** — either already running in **Neo4j Desktop**, or
  a database **dump** to seed from (see [`deploy/README.md`](deploy/README.md)).
- **Docker Desktop** (recommended), or **[uv](https://docs.astral.sh/uv/)** with
  **Python 3.13** to run from source.
- The full graph is large (~76M relationships) and wants **~32 GB RAM**; a smaller
  subset runs comfortably on a laptop.

**Option A — Docker (recommended)**

Self-contained, and mirrors how the app is deployed.

- *Already have the graph in Neo4j Desktop?* Run just the app + Geosupport against it
  (reads `deploy/.env` — set `NEO4J_PASSWORD`; details in the
  [deploy guide](deploy/README.md#local-smoke-test-use-your-neo4j-desktop-graph)):
  ```bash
  make deploy-local          # → http://localhost:8501
  ```
- *Starting from a dump?* Bring up the whole stack — Neo4j in a container, seeded from
  a local dump — following
  [Full stack locally](deploy/README.md#full-stack-locally-neo4j-in-docker-seeded-from-a-local-dump)
  in the deploy guide.

**Option B — From source (developers)**

Runs the app directly against a Neo4j you already have (e.g. Neo4j Desktop) plus an
optional local Geosupport.

```bash
uv sync                                   # install dependencies (Python 3.13)
cp .env.example .env                      # set NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
make ui-start                             # or: uv run streamlit run watchline/discovery/ui/app.py
open http://localhost:8501
```

`make ui-stop` stops it and `make ui-logs` tails the logs. Address-lookup features
need Geosupport reachable at `GEOSUPPORT_URL`; the landlord and deep-investigation
features don't.

**API keys**

On first load the app checks for `ANTHROPIC_API_KEY`. If it isn't set in your
environment or `.env`, the app shows a setup screen where you paste it — the key is
held only in the running process for that session. Without a Tavily key, web search
is disabled and the app says so; everything else works.

## Deploy it for others

To stand the app up on a cloud VM (a DigitalOcean Droplet, EC2, …) so stakeholders
can try it, see [`deploy/README.md`](deploy/README.md).
