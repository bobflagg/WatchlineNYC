![Picture](header.png)

# Mission

New York City's housing enforcement data is public, but accountability is not. Violations are recorded. Inspections happen. Deeds are filed. Yet the questions that matter most are also the hardest to answer quickly, systematically, and with evidence that holds up to scrutiny: who is ultimately responsible for this building, why have conditions persisted, and what is the full pattern across a portfolio.

Watchline NYC is being built to change that. It is an integrated knowledge graph linking every major housing enforcement dataset: HPD violations, DOB complaints and permits, ECB/OATH judgments, ACRIS deed records, DHCR rent stabilization filings, tax liens, and beneficial ownership disclosures. These datasets are connected through a principled model of building identity, ownership chains, and enforcement history. Over that graph sits an AI agent that interprets investigative questions in plain language, retrieves structured evidence from the graph, and returns answers in which every claim is explicitly linked to the records that support it.

The animating principle is that answers must be *defensible*, not merely plausible. Watchline distinguishes between what the records show, what can be reasonably inferred, and what remains uncertain. Every conclusion the system produces can be traced back through its reasoning to the primary sources that justify it. When the underlying data changes, because a deed is corrected, a violation is resolved, or an ownership structure is updated, the conclusions update with it.

Watchline does not make legal findings or editorial judgments. It is infrastructure: a shared capability that makes rigorous, evidence-based investigation faster and more accessible for the journalists, tenant advocates, legal services organizations, policy analysts, and watchdog agencies whose work depends on knowing who is responsible and what the record shows.

The immediate goal is to make the kind of research that currently takes an expert hours available in minutes, and to make it available not just to specialists, but to the tenant in a deteriorating building who needs to understand who actually controls it, and why that matters.

# Installion

## Prerequisites

Before you begin, make sure you have the following installed:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- [make](https://www.gnu.org/software/make/) — available by default on macOS and Linux
- API keys for [Anthropic](https://console.anthropic.com/) and [Tavily](https://app.tavily.com/)


### 1. Clone the repository

```bash
git clone git@github.com:bobflagg/WatchlineNYC.git
cd WatchlineNYC
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure environment variables

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Open `.env` and set your API keys — the Neo4j connection settings are pre-configured to match the local Docker setup and should not need to be changed:

```dotenv
# Neo4j domain connection
NEO4J_DOMAIN_URI=bolt://localhost:7687
NEO4J_DOMAIN_USER=neo4j
NEO4J_DOMAIN_PASSWORD=watchline
NEO4J_DOMAIN_DATABASE=neo4j

# Neo4j epistemic connection
NEO4J_EPISTEMIC_URI=bolt://localhost:7688
NEO4J_EPISTEMIC_USER=neo4j
NEO4J_EPISTEMIC_PASSWORD=watchline
NEO4J_EPISTEMIC_DATABASE=neo4j

# Anthropic API Key
ANTHROPIC_API_KEY=your-key-here

# Tavily API Key
TAVILY_API_KEY=your-key-here
```

### 4. Set up and load the knowledge graphs

This downloads the Neo4j dumps from Google Drive, creates the Docker containers, and loads the data:

```bash
make kgs
```

You can also run each step individually:

```bash
make download   # download KG dumps from Google Drive
make setup      # create Neo4j Docker containers
make load       # load dumps into the containers
```

Verify the KGs are up and running:

```bash
make test
```

### 5. Start the application

```bash
make serve
```

This starts both services in the background:

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI server | http://localhost:8080 |
| FastAPI docs | http://localhost:8080/docs |

## Usage

### Stopping the application

```bash
make serve-stop
```

### Checking application status

```bash
make serve-status
```

### Viewing logs

```bash
make api-logs       # FastAPI logs
make ui-logs        # Streamlit logs
```

### Neo4j browser

Both graph databases are accessible via the Neo4j browser UI:

| Database | URL | 
|---|---|
| Domain KG | http://localhost:7474 |
| Epistemic KG | http://localhost:7475 |

Login with username `neo4j` and password `watchline`.

## All make targets

Run `make help` to see all available targets:

```
make help
```

## Troubleshooting

**Docker out of disk space during `make load`**
Neo4j expands dumps significantly on load. Make sure Docker Desktop has at least 60GB of virtual disk space allocated under Settings → Resources → Advanced.

**Neo4j containers fail to start**
Check that ports 7474, 7475, 7687, and 7688 are not already in use:
```bash
lsof -i :7474 -i :7475 -i :7687 -i :7688
```

**Authentication errors when running `make test`**
The Neo4j containers can take 10–15 seconds to finish initializing after `make setup`. Wait a moment and re-run `make test`.
