.PHONY: help setup load test restart stop start clean download \
        api ui serve serve-stop api-stop ui-stop api-logs ui-logs

DOCKER_DIR          := docker
DUMPS_DIR           := dumps
DOMAIN_GDRIVE_ID    := 1nqobTwCW6puY6rIFQL2xSqNPrYcRRouY
EPISTEMIC_GDRIVE_ID := 1EW4fESzlmVizppQGUgvhwP8AxCda-Azq

API_PID_FILE        := .api.pid
UI_PID_FILE         := .ui.pid
API_LOG             := .api.log
UI_LOG              := .ui.log

help: ## Show this help message
	@echo "WatchlineNYC - Neo4j Knowledge Graph Management"
	@echo "================================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Neo4j ────────────────────────────────────────────────────────────────────

download: ## Download KG dumps from Google Drive into dumps/ directories
	@echo "Checking for gdown..."
	@pip install -q gdown
	@echo "Creating dump directories..."
	@mkdir -p $(DUMPS_DIR)/domain
	@mkdir -p $(DUMPS_DIR)/epistemic
	@echo "Downloading Domain KG dump..."
	@gdown $(DOMAIN_GDRIVE_ID) -O $(DUMPS_DIR)/domain/neo4j.dump
	@echo "Downloading Epistemic KG dump..."
	@gdown $(EPISTEMIC_GDRIVE_ID) -O $(DUMPS_DIR)/epistemic/neo4j.dump
	@echo "Downloads complete:"
	@du -sh $(DUMPS_DIR)/domain/neo4j.dump
	@du -sh $(DUMPS_DIR)/epistemic/neo4j.dump

setup: ## Create and start Neo4j Docker containers
	@echo "Setting up Neo4j containers..."
	@bash $(DOCKER_DIR)/setup-kg-containers.sh

load: ## Load knowledge graph dumps into containers
	@echo "Loading knowledge graphs..."
	@bash $(DOCKER_DIR)/load-kgs.sh

test: ## Test that both KGs are up and returning data
	@echo "Testing knowledge graph connections..."
	@python3 $(DOCKER_DIR)/test_kg.py

kgs: download setup load ## Download, setup, load, and test in one step

restart: ## Restart both Neo4j containers
	@echo "Restarting containers..."
	@docker restart neo4j-domain neo4j-epistemic

stop: ## Stop both Neo4j containers
	@echo "Stopping containers..."
	@docker stop neo4j-domain neo4j-epistemic

start: ## Start both Neo4j containers (if already set up)
	@echo "Starting containers..."
	@docker start neo4j-domain neo4j-epistemic

logs-domain: ## Tail logs for the Domain KG
	@docker logs -f neo4j-domain

logs-epistemic: ## Tail logs for the Epistemic KG
	@docker logs -f neo4j-epistemic

status: ## Show running status of both containers
	@docker ps --filter name=neo4j-domain --filter name=neo4j-epistemic

clean: ## Stop and remove containers and volumes (destructive!)
	@echo "WARNING: This will delete all containers and volume data."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@docker stop neo4j-domain neo4j-epistemic 2>/dev/null || true
	@docker rm neo4j-domain neo4j-epistemic 2>/dev/null || true
	@docker volume rm neo4j-domain neo4j-epistemic 2>/dev/null || true
	@echo "Done."

# ── Application ──────────────────────────────────────────────────────────────

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
