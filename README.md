![Picture](header.png)

Watchline is a public investigation platform for NYC housing accountability. It connects HPD violations, ownership registrations, and court records so that journalists, tenant advocates, and enforcement agencies can trace patterns of abuse across a landlord's entire portfolio. It exists to put rigorous, evidence-based investigation within reach of anyone who needs to understand who controls a building and what the record shows — in minutes rather than hours. See the [Founding Charter](https://github.com/bobflagg/WatchlineNYC/blob/main/documents/charter.md) for details an [example response](https://bobflagg.github.io/WatchlineNYC/) to this query:

>> Is 122 West 97th Street in Manhattan getting worse?


# Installation

## Prerequisites

Before you begin, make sure you have the following installed:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- [make](https://www.gnu.org/software/make/) — available by default on macOS and Linux
- API keys for [Anthropic](https://console.anthropic.com/) and [Tavily](https://app.tavily.com/)


## 1. Clone the repository

```bash
git clone git@github.com:bobflagg/WatchlineNYC.git
cd WatchlineNYC
```

## 2. Install dependencies

```bash
uv sync
```

## 3. Configure environment variables

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

## 4. Set up and load the knowledge graphs

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

# Usage

## Start the application

```bash
make serve
```

This starts both services in the background:

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI server | http://localhost:8080 |
| FastAPI docs | http://localhost:8080/docs |

## Stop the application

```bash
make serve-stop
```

## Check application status

```bash
make serve-status
```

## View logs

```bash
make api-logs       # FastAPI logs
make ui-logs        # Streamlit logs
```

## Review the KGs with Neo4j browser

Both graph databases are accessible via the Neo4j browser UI:

| Database | URL | 
|---|---|
| Domain KG | http://localhost:7474 |
| Epistemic KG | http://localhost:7475 |

Login with username `neo4j` and password `watchline`.

## Review make targets

Run `make help` to see all available targets:

```
make help
```

## Troubleshoot

**Docker out of disk space during `make load`**
Neo4j expands dumps significantly on load. Make sure Docker Desktop has at least 60GB of virtual disk space allocated under Settings → Resources → Advanced.

**Neo4j containers fail to start**
Check that ports 7474, 7475, 7687, and 7688 are not already in use:
```bash
lsof -i :7474 -i :7475 -i :7687 -i :7688
```

**Authentication errors when running `make test`**
The Neo4j containers can take 10–15 seconds to finish initializing after `make setup`. Wait a moment and re-run `make test`.


# Connect to Claude Desktop

The Neo4j MCP server ([`mcp-neo4j-cypher`](https://github.com/neo4j-contrib/mcp-neo4j)) is the official Model Context Protocol integration maintained by Neo4j Labs. Once configured, Claude Desktop can read the graph schema, run Cypher queries, and answer natural-language questions about the data — which is exactly how the Watchline conversational AI interface will work.

## Prerequisites

- [Claude Desktop](https://claude.ai/download) installed
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux, or see the `uv` docs for Windows)

## Configuration

Open the Claude Desktop configuration file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the following entries inside the `mcpServers` object, using the password you set in step 2:

```json
{
  "mcpServers": {
    "neo4j-watchline-domain": {
      "command": "uvx",
      "args": [
        "mcp-neo4j-cypher",
        "--db-url",
        "neo4j://localhost:7687",
        "--username",
        "neo4j",
        "--password",
        "watchline",
        "--database",
        "neo4j"
      ]
    },
    "neo4j-watchline-epistemic": {
      "command": "uvx",
      "args": [
        "mcp-neo4j-cypher",
        "--db-url",
        "neo4j://localhost:7688",
        "--username",
        "neo4j",
        "--password",
        "watchline",
        "--database",
        "neo4j"
      ]
    }
}
```
Save the file, then **quit and relaunch** Claude Desktop. The two connectors `neoj4-watchline-domain` and `neoj4-watchline-epistemic` should appeat in the connectors menu.

## Sample system prompt

Here's is a sample prompt to consider when starting a conversation in Claude Desktop about Watchline:

```text
Read the Watchline 
[Charter](https://github.com/bobflagg/WatchlineNYC/blob/main/documents/charter.md) 
and 
[Ontology Specification](https://github.com/bobflagg/WatchlineNYC/blob/main/documents/ontology-implementable.md) 
to get oriented on the WatchlineNYC project then use the cypher command "SHOW CURRENT GRAPH TYPE" 
to review the Neo4j KG structure, which you have access to via MCP at neo4j-watchline-epistemic.
```

