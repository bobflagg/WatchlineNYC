# =============================================================================
# Watchline NYC -- Makefile
#
# Orchestrates the full knowledge graph build pipeline, Neo4j infrastructure,
# and application serving.
#
# Usage:
#   make help          Show all available targets
#   make kgs           Download, set up, and load Neo4j containers
#   make build         Full KG build from scratch (schema + ingest all datasets)
#   make serve         Start FastAPI + Streamlit in the background
#   make serve-stop    Stop both servers
#
# Prerequisites:
#   - .env file with PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD,
#     NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
#   - Docker installed and running (for KG containers)
#   - cypher-shell installed and on PATH (or set CYPHER_SHELL below)
#   - uv installed
#
# Version: 2.0 -- July 2026
# =============================================================================

.PHONY: help \
        download setup load test kgs restart stop start \
        logs-domain logs-epistemic status clean-docker \
        api api-stop api-logs \
        ui  ui-stop  ui-logs  \
        serve serve-stop serve-status \
        build rebuild nightly \
        schema seed-rules indexes \
        portfolio reconcile agents \
        hpd dob ecb hpd-lit rentstab phc001 phc001-dry-run \
        verify clean-landlords


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PYTHON        = uv run python
CYPHER_SHELL  = cypher-shell
SCRIPTS_DIR   = scripts
INGEST        = watchline.ingest

DOCKER_DIR          := docker
DUMPS_DIR           := dumps
DOMAIN_GDRIVE_ID    := 1nqobTwCW6puY6rIFQL2xSqNPrYcRRouY
EPISTEMIC_GDRIVE_ID := 1EW4fESzlmVizppQGUgvhwP8AxCda-Azq

API_PID_FILE := .api.pid
UI_PID_FILE  := .ui.pid
API_LOG      := .api.log
UI_LOG       := .ui.log

# Load .env for cypher-shell authentication
include .env
export

CYPHER_ARGS = -a "$(NEO4J_EPISTEMIC_URI)" \
              -u "$(NEO4J_EPISTEMIC_USER)" \
              -p "$(NEO4J_EPISTEMIC_PASSWORD)" \
              -d "$(NEO4J_EPISTEMIC_DATABASE)"


# ---------------------------------------------------------------------------
# Help
# Uses ## comments on each target for self-documenting output.
# ---------------------------------------------------------------------------

help: ## Show this help message
	@echo ""
	@echo "Watchline NYC"
	@echo "============="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""


# ---------------------------------------------------------------------------
# Neo4j infrastructure (Docker)
# ---------------------------------------------------------------------------

download: ## Download KG dumps from Google Drive into dumps/
	@echo "Checking for gdown..."
	@uv run pip install -q gdown
	@mkdir -p $(DUMPS_DIR)/domain $(DUMPS_DIR)/epistemic
	@echo "Downloading Domain KG dump..."
	@uv run gdown $(DOMAIN_GDRIVE_ID) -O $(DUMPS_DIR)/domain/neo4j.dump
	@echo "Downloading Epistemic KG dump..."
	@uv run gdown $(EPISTEMIC_GDRIVE_ID) -O $(DUMPS_DIR)/epistemic/neo4j.dump
	@du -sh $(DUMPS_DIR)/domain/neo4j.dump $(DUMPS_DIR)/epistemic/neo4j.dump

setup: ## Create and start Neo4j Docker containers
	@bash $(DOCKER_DIR)/setup-kg-containers.sh

load: ## Load knowledge graph dumps into containers
	@bash $(DOCKER_DIR)/load-kgs.sh

test: ## Test that both KGs are up and returning data
	@$(PYTHON) $(DOCKER_DIR)/test_kg.py

kgs: download setup load test ## Download, setup, load, and test in one step

restart: ## Restart both Neo4j containers
	@docker restart neo4j-domain neo4j-epistemic

stop: ## Stop both Neo4j containers
	@docker stop neo4j-domain neo4j-epistemic

start: ## Start both Neo4j containers (if already set up)
	@docker start neo4j-domain neo4j-epistemic

logs-domain: ## Tail logs for the Domain KG container
	@docker logs -f neo4j-domain

logs-epistemic: ## Tail logs for the Epistemic KG container
	@docker logs -f neo4j-epistemic

status: ## Show running status of both Neo4j containers
	@docker ps --filter name=neo4j-domain --filter name=neo4j-epistemic

clean-docker: ## Stop and remove containers and volumes (destructive!)
	@echo "WARNING: This will delete all Neo4j containers and volume data."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@docker stop neo4j-domain neo4j-epistemic 2>/dev/null || true
	@docker rm   neo4j-domain neo4j-epistemic 2>/dev/null || true
	@docker volume rm neo4j-domain neo4j-epistemic 2>/dev/null || true
	@echo "Done."


# ---------------------------------------------------------------------------
# Application serving
# ---------------------------------------------------------------------------

api: ## Start FastAPI server in the background (logs → .api.log)
	@if [ -f $(API_PID_FILE) ] && kill -0 $$(cat $(API_PID_FILE)) 2>/dev/null; then \
		echo "FastAPI is already running (PID $$(cat $(API_PID_FILE)))"; \
	else \
		echo "Starting FastAPI on http://localhost:8080 ..."; \
		uv run uvicorn watchline.fw.server:app --port 8080 > $(API_LOG) 2>&1 & \
		echo $$! > $(API_PID_FILE); \
		echo "FastAPI started (PID $$(cat $(API_PID_FILE))) — logs in $(API_LOG)"; \
	fi

api-stop: ## Stop the FastAPI server
	@if [ -f $(API_PID_FILE) ] && kill -0 $$(cat $(API_PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(API_PID_FILE)) && rm -f $(API_PID_FILE); \
		echo "FastAPI stopped."; \
	else \
		echo "FastAPI is not running."; \
		rm -f $(API_PID_FILE); \
	fi

api-logs: ## Tail FastAPI logs
	@tail -f $(API_LOG)

ui: ## Start Streamlit app in the background (logs → .ui.log)
	@if [ -f $(UI_PID_FILE) ] && kill -0 $$(cat $(UI_PID_FILE)) 2>/dev/null; then \
		echo "Streamlit is already running (PID $$(cat $(UI_PID_FILE)))"; \
	else \
		echo "Starting Streamlit on http://localhost:8501 ..."; \
		uv run streamlit run watchline/ui/app.py > $(UI_LOG) 2>&1 & \
		echo $$! > $(UI_PID_FILE); \
		echo "Streamlit started (PID $$(cat $(UI_PID_FILE))) — logs in $(UI_LOG)"; \
	fi

ui-stop: ## Stop the Streamlit app
	@if [ -f $(UI_PID_FILE) ] && kill -0 $$(cat $(UI_PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(UI_PID_FILE)) && rm -f $(UI_PID_FILE); \
		echo "Streamlit stopped."; \
	else \
		echo "Streamlit is not running."; \
		rm -f $(UI_PID_FILE); \
	fi

ui-logs: ## Tail Streamlit logs
	@tail -f $(UI_LOG)

serve: api ui ## Start both FastAPI and Streamlit in the background

serve-stop: api-stop ui-stop ## Stop both FastAPI and Streamlit

serve-status: ## Show whether FastAPI and Streamlit are running
	@if [ -f $(API_PID_FILE) ] && kill -0 $$(cat $(API_PID_FILE)) 2>/dev/null; then \
		echo "  FastAPI:    running (PID $$(cat $(API_PID_FILE)))"; \
	else \
		echo "  FastAPI:    stopped"; \
	fi
	@if [ -f $(UI_PID_FILE) ] && kill -0 $$(cat $(UI_PID_FILE)) 2>/dev/null; then \
		echo "  Streamlit:  running (PID $$(cat $(UI_PID_FILE)))"; \
	else \
		echo "  Streamlit:  stopped"; \
	fi


# ---------------------------------------------------------------------------
# KG build pipeline -- full build from scratch
# ---------------------------------------------------------------------------

build: schema seed-rules indexes hpd dob ecb hpd-lit rentstab portfolio agents reconcile phc001 ## Full KG build from scratch
	@echo ""
	@echo "Full Watchline KG build complete. Run 'make verify' to confirm."

rebuild: build ## Alias for build

nightly: portfolio agents reconcile ## Re-run portfolio detection + agents + reconcile (incremental)
	@echo ""
	@echo "Nightly update complete."


# ---------------------------------------------------------------------------
# One-time setup targets (run against a fresh Neo4j database)
# ---------------------------------------------------------------------------

schema: ## Apply GRAPH TYPE schema to Neo4j
	@echo "Applying GRAPH TYPE schema..."
	$(CYPHER_SHELL) $(CYPHER_ARGS) --file $(SCRIPTS_DIR)/01_schema.cypher
	@echo "Schema applied."

seed-rules: ## Load all Rule nodes into Neo4j
	@echo "Loading Rule nodes..."
	$(CYPHER_SHELL) $(CYPHER_ARGS) --file $(SCRIPTS_DIR)/02_seed_rules.cypher
	@echo "Rules seeded."

indexes: ## Create performance indexes
	@echo "Creating performance indexes..."
	$(CYPHER_SHELL) $(CYPHER_ARGS) --file $(SCRIPTS_DIR)/03_indexes.cypher
	@echo "Indexes created (building in background — monitor with SHOW INDEXES)."


# ---------------------------------------------------------------------------
# Portfolio detection pipeline
# ---------------------------------------------------------------------------

portfolio: ## Load landlord graph + run WCC/Louvain + write ontology
	@echo "Running portfolio detection pipeline..."
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step init
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step load
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step store
	@echo "Portfolio pipeline complete."

reconcile: ## Link BeneficialControl relationships to Building nodes
	@echo "Reconciling BeneficialControl relationships..."
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step reconcile
	@echo "Reconciliation complete."

portfolio-init: ## Run portfolio init step only
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step init

portfolio-load: ## Run portfolio load step only
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step load

portfolio-store: ## Run portfolio store step only
	$(PYTHON) -m $(INGEST).portfolio.pipeline --step store


# ---------------------------------------------------------------------------
# Managing agent ingestion pipeline
# ---------------------------------------------------------------------------

agents: ## Ingest managing agents from HPD registration contacts
	@echo "Ingesting managing agent contacts..."
	$(PYTHON) -m $(INGEST).agents.pipeline --step load
	$(PYTHON) -m $(INGEST).agents.pipeline --step store
	@echo "Agents pipeline complete."


# ---------------------------------------------------------------------------
# Ingestion pipelines
# ---------------------------------------------------------------------------

hpd: ## Ingest HPD violations (~11M events)
	@echo "Ingesting HPD violations..."
	$(PYTHON) -m $(INGEST).hpd_violations.pipeline --step source
	$(PYTHON) -m $(INGEST).hpd_violations.pipeline --step buildings
	$(PYTHON) -m $(INGEST).hpd_violations.pipeline --step violations
	@echo "HPD violations complete."

dob: ## Ingest DOB violations (~2.5M events)
	@echo "Ingesting DOB violations..."
	$(PYTHON) -m $(INGEST).dob_violations.pipeline --step source
	$(PYTHON) -m $(INGEST).dob_violations.pipeline --step buildings
	$(PYTHON) -m $(INGEST).dob_violations.pipeline --step violations
	@echo "DOB violations complete."

ecb: ## Ingest ECB/OATH violations (~1.8M judgments)
	@echo "Ingesting ECB violations..."
	$(PYTHON) -m $(INGEST).ecb_violations.pipeline --step source
	$(PYTHON) -m $(INGEST).ecb_violations.pipeline --step buildings
	$(PYTHON) -m $(INGEST).ecb_violations.pipeline --step violations
	@echo "ECB violations complete."

hpd-lit: ## Ingest HPD litigations (~239K cases)
	@echo "Ingesting HPD litigations..."
	$(PYTHON) -m $(INGEST).hpd_litigations.pipeline
	@echo "HPD litigations complete."

rentstab: ## Ingest rent stabilization data (~46K buildings)
	@echo "Ingesting rent stabilization data..."
	$(PYTHON) -m $(INGEST).rentstab.pipeline
	@echo "Rent stabilization complete."


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

phc001: ## Evaluate PHC-001 (Persistent Hazardous Conditions)
	@echo "Evaluating PHC-001 (Persistent Hazardous Conditions)..."
	$(PYTHON) -m $(INGEST).phc001.pipeline
	@echo "PHC-001 evaluation complete."

phc001-dry-run: ## Dry run PHC-001 (no writes)
	@echo "PHC-001 dry run (no writes)..."
	$(PYTHON) -m $(INGEST).phc001.pipeline --dry-run


# ---------------------------------------------------------------------------
# Verification and utilities
# ---------------------------------------------------------------------------

verify: ## Run sanity check queries against the live graph
	@echo "Running verification queries..."
	@echo "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC LIMIT 15;" \
		| $(CYPHER_SHELL) $(CYPHER_ARGS) --format plain
	@echo ""
	@echo "MATCH (rel:Relationship {relationship_type: 'BeneficialControl'})-[:INVOLVES_BUILDING]->(bld:Building) MATCH (rel)-[:INVOLVES_ACTOR]->(a:Actor) MATCH (a)-[:SUBJECT_OF]->(c:Claim) RETURN count(DISTINCT bld) AS buildings, count(DISTINCT a) AS networks, count(DISTINCT c) AS claims, count(DISTINCT rel) AS relationships;" \
		| $(CYPHER_SHELL) $(CYPHER_ARGS) --format plain
	@echo ""
	@echo "MATCH (e:Event) RETURN e.source_name AS source, count(e) AS events ORDER BY events DESC;" \
		| $(CYPHER_SHELL) $(CYPHER_ARGS) --format plain
	@echo ""
	@echo "MATCH (a:Actor) RETURN a.actor_type AS type, count(a) AS count ORDER BY count DESC;" \
		| $(CYPHER_SHELL) $(CYPHER_ARGS) --format plain

clean-landlords: ## Clear intermediate Landlord nodes from the graph
	@echo "Clearing intermediate Landlord nodes..."
	@echo "MATCH (n:Landlord) DETACH DELETE n;" | $(CYPHER_SHELL) $(CYPHER_ARGS)
	@echo "Done."
