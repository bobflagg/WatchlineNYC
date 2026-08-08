![Watchline NYC — Discovery](header.png)

Watchline is **accountability infrastructure for New York City housing** — it helps
journalists, tenant advocates, watchdog agencies, and the public investigate housing
conditions and ownership accountability using evidence from the city's public record.

It builds on the foundational work of [JustFix](https://www.justfix.org/en/), adding
an AI interface so anyone can ask a question in plain English and get an
evidence-based answer. The AI is an **orchestrator, not a reasoner**: it translates a
question into structured queries, retrieves evidence from a knowledge graph, applies
explicit rules, and explains the result in plain language — making public housing
data accessible to everyone without sacrificing transparency or accountability.

A [live demonstration](https://bobflagg.github.io/WatchlineNYC/) shows Watchline
answering *"Is 122 West 97th Street in Manhattan getting worse?"*

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
