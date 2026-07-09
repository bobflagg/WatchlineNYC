# =============================================================================
# Watchline NYC — Makefile
#
# Top-level orchestrator. Delegates to:
#   Makefile.evidentiary  evidentiary KG build pipeline  (targets: evidentiary-*)
#   Makefile.discovery    discovery KG ingestion pipeline (targets: discovery-*)
#
# Usage:
#   make help                      Show all available targets
#   make kgs                       Download, set up, and load Neo4j containers
#   make evidentiary-build         Full evidentiary KG build from scratch
#   make discovery-ingest-all      Full discovery KG ingestion (schema -> events -> portfolio)
#   make serve                     Start FastAPI + Streamlit in the background
#
# Prerequisites (.env):
#   PGHOST, PGPORT, PGDATABASE (=wow), PGUSER, PGPASSWORD
#   NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
#   NEO4J_EVIDENTIARY_DATABASE, NEO4J_DISCOVERY_DATABASE
#   NEO4J_EPISTEMIC_URI, NEO4J_EPISTEMIC_USER,
#   NEO4J_EPISTEMIC_PASSWORD, NEO4J_EPISTEMIC_DATABASE
#
# Version: 3.0 — July 2026 (reconciliation)
# =============================================================================

include .env
export

PYTHON       ?= uv run python
CYPHER_SHELL ?= cypher-shell

include Makefile.evidentiary
include Makefile.discovery

DOCKER_DIR          := docker
DUMPS_DIR           := dumps
DISCOVERY_GDRIVE_ID := 1nqobTwCW6puY6rIFQL2xSqNPrYcRRouY
EVIDENTIARY_GDRIVE_ID := 1EW4fESzlmVizppQGUgvhwP8AxCda-Azq

API_PID_FILE := .api.pid
UI_PID_FILE  := .ui.pid
API_LOG      := .api.log
UI_LOG       := .ui.log

.PHONY: help install \
        download setup load test kgs restart stop start \
        logs-discovery logs-evidentiary status clean-docker \
        verify \
        api api-stop api-logs \
        ui ui-stop ui-logs \
        serve serve-stop serve-status


# ---------------------------------------------------------------------------
# Help — aggregates targets from this file and both sub-Makefiles
# ---------------------------------------------------------------------------

help: ## Show all available targets
	@echo ""
	@echo "Watchline NYC"
	@echo "============="
	@echo ""
	@echo "  Infrastructure & serving:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' Makefile | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-32s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Evidentiary KG  (evidentiary-*):"
	@grep -hE '^evidentiary-[a-zA-Z_-]+:.*?## \[ev\].*$$' Makefile.evidentiary | \
		sed 's/:.*## \[ev\] /\t/' | \
		awk 'BEGIN {FS = "\t"}; {printf "  \033[33m%-32s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Discovery KG    (discovery-*):"
	@grep -hE '^discovery-[a-zA-Z_-]+:.*?## \[dc\].*$$' Makefile.discovery | \
		sed 's/:.*## \[dc\] /\t/' | \
		awk 'BEGIN {FS = "\t"}; {printf "  \033[32m%-32s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Install Python dependencies (uv)
	uv sync

verify: ## Run Phase 5 cross-graph consistency checks against both live KGs
	$(PYTHON) scripts/verify_consistency.py


# ---------------------------------------------------------------------------
# Neo4j infrastructure (Docker)
# ---------------------------------------------------------------------------

download: ## Download KG dumps from Google Drive into dumps/
	@echo "Checking for gdown..."
	@uv run pip install -q gdown
	@mkdir -p $(DUMPS_DIR)/discovery $(DUMPS_DIR)/evidentiary
	@echo "Downloading Discovery KG dump..."
	@uv run gdown $(DISCOVERY_GDRIVE_ID) -O $(DUMPS_DIR)/discovery/neo4j.dump
	@echo "Downloading Evidentiary KG dump..."
	@uv run gdown $(EVIDENTIARY_GDRIVE_ID) -O $(DUMPS_DIR)/evidentiary/neo4j.dump
	@du -sh $(DUMPS_DIR)/discovery/neo4j.dump $(DUMPS_DIR)/evidentiary/neo4j.dump

setup: ## Create and start Neo4j Docker containers
	@bash $(DOCKER_DIR)/setup-kg-containers.sh

load: ## Load knowledge graph dumps into containers
	@bash $(DOCKER_DIR)/load-kgs.sh

test: ## Test that both KGs are up and returning data
	@$(PYTHON) $(DOCKER_DIR)/test_kg.py

kgs: download setup load test ## Download, setup, load, and test in one step

restart: ## Restart both Neo4j containers
	@docker restart neo4j-discovery neo4j-evidentiary

stop: ## Stop both Neo4j containers
	@docker stop neo4j-discovery neo4j-evidentiary

start: ## Start both Neo4j containers (if already set up)
	@docker start neo4j-discovery neo4j-evidentiary

logs-discovery: ## Tail logs for the Discovery KG container
	@docker logs -f neo4j-discovery

logs-evidentiary: ## Tail logs for the Evidentiary KG container
	@docker logs -f neo4j-evidentiary

status: ## Show running status of both Neo4j containers
	@docker ps --filter name=neo4j-discovery --filter name=neo4j-evidentiary

clean-docker: ## Stop and remove both containers and their volumes (destructive!)
	@echo "WARNING: This will delete all Neo4j container data."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@docker stop neo4j-discovery neo4j-evidentiary 2>/dev/null || true
	@docker rm   neo4j-discovery neo4j-evidentiary 2>/dev/null || true
	@docker volume rm neo4j-discovery neo4j-evidentiary 2>/dev/null || true
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
