![Watchline NYC — Discovery](header.png)

Watchline is **accountability infrastructure for New York City housing** — it helps
journalists, tenant advocates, watchdog agencies, and the public investigate housing
conditions and ownership accountability using evidence from the city's public record.

It builds on the foundational work of [JustFix](https://www.justfix.org/en/) and its Who
Owns What, and pushes past the limits every registration-based ownership tool inherits.
Watchline adds three things:

- **Precision-first record linkage** (probabilistic entity resolution with
  [Splink](https://moj-analytical-services.github.io/splink/)) that resolves one owner across
  dozens of differently-named LLCs — reuniting portfolios that a single name or address typo
  fractures, without fusing two different people.
- A **deed veil-pierce** built from the ACRIS record (`CONNECTED_BY_DEED`) that catches
  shell-LLC ownership registrations hide — including the shell game's signature move: buy a
  block together, then re-deed each building into its own single-purpose LLC.
- A **three-layer model** that keeps three questions ownership data routinely conflates
  cleanly apart — who **owns** a building, what operational network it **runs through**, and
  who **manages** it.

Every ownership link is labeled **sourced or inferred** — a lead to verify, never a legal
determination.

On top of that sits a **conversational interface** so anyone can ask a question in plain
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

Four interactive comparison maps show how Watchline's owner-identity layer diverges from
Who Owns What — in **both** directions. Toggle between the two systems; hover a building
for details. *(These groupings are algorithmic inferences from public records — leads to
verify, not determinations of legal ownership.)*

- **[Croman — 127 buildings, one owner](https://bobflagg.github.io/WatchlineNYC/docs/maps/croman.html):**
  Watchline unifies Steven Croman's 127 buildings that Who Owns What splits across six
  portfolios on a one-character address typo (`4 WEST 51` vs `424 WEST 51`).
- **[Escobar — 26 buildings, split by a typo](https://bobflagg.github.io/WatchlineNYC/docs/maps/escobar.html):**
  Who Owns What splits landlord Ramon Escobar's Bronx portfolio into two on a single
  registration-address typo (`GRAND CONCOURSE` vs `GRAND COURSE`); Watchline keeps all 26
  buildings together as one owner.
- **[Haight Street — one block, six owners, one deed](https://bobflagg.github.io/WatchlineNYC/docs/maps/haight.html):**
  Nine identical townhouses on one Queens block that Who Owns What reads as six separate owners;
  Watchline reunites them via a single 2020 bulk deed — a veil-pierce from the ACRIS record that
  registration-based grouping cannot see. Toggle to watch one contiguous row turn six colors.
- **[Correcting an over-merge — one office, seven owners](https://bobflagg.github.io/WatchlineNYC/docs/maps/miller.html):**
  Who Owns What groups 27 buildings as a single owner because they share one registration
  office in Lakewood, NJ; Watchline **separates** them into the seven distinct owners they
  actually are — a more accurate, disaggregated view of the same public records.

Four worked [**case studies**](https://bobflagg.github.io/WatchlineNYC/docs/cases/) follow the
owner-identity layer deciding in **both** directions. It *merges* owners Who Owns What splits — one
fractured by a typo (Escobar — 26 buildings reunited), and one WoW can't see at all: nine buildings
tied only by a shared ACRIS deed (Haight — a Queens block that reads as six owners but was one bulk
purchase). And it *declines* to merge parties that share only an office (Miller — one Lakewood suite,
seven owners) or a managing agent (Levitov — one operator, five separate owners). Together they are
the answer, in data, to *"doesn't it just merge everything?"* — every ownership link labeled an
inference to verify, not a legal determination, and drawn from the public record.

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
