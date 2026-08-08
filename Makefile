# WatchlineNYC Discovery — developer tasks.
# Streamlit UI lifecycle plus a couple of conveniences. Recipes use TABS
# (GNU Make 3.81 on macOS has no .RECIPEPREFIX).

APP     := watchline/discovery/ui/app.py
PORT    ?= 8501
LOGFILE := .streamlit-ui.log

# Deployment: build the Neo4j dump used to seed the POC stack (see deploy/README.md).
# `neo4j-admin database dump` is an on-host, OFFLINE op — override NEO4J_ADMIN to
# reach your source, e.g. NEO4J_ADMIN='docker exec neo4j neo4j-admin'.
NEO4J_ADMIN ?= neo4j-admin
DUMP_DB     ?= discovery
DUMP_DIR    ?= dumps

# Deploy stack (deploy/docker-compose.yml). Recipes run from deploy/ so .env and
# the relative build contexts (.., ../sidecar) resolve.
COMPOSE_DIR := deploy

.DEFAULT_GOAL := help

.PHONY: help ui-start ui-stop ui-restart ui-status ui-logs dump deploy-build deploy-up deploy-down deploy-logs deploy-local

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

ui-start: ## Start the Streamlit UI in the background (override PORT=…, WATCHLINE_MODEL=…)
	@if pgrep -f "streamlit run $(APP)" >/dev/null 2>&1; then \
		echo "UI already running -> http://localhost:$(PORT)"; \
	else \
		nohup uv run streamlit run $(APP) --server.port $(PORT) \
			--server.headless true --browser.gatherUsageStats false \
			</dev/null >$(LOGFILE) 2>&1 & \
		echo "UI started -> http://localhost:$(PORT)  (give it a few seconds; logs: make ui-logs)"; \
	fi

ui-stop: ## Stop the Streamlit UI
	@pkill -f "streamlit run $(APP)" 2>/dev/null && echo "UI stopped." || echo "UI not running."

ui-restart: ## Restart the Streamlit UI
	@$(MAKE) --no-print-directory ui-stop; sleep 1; $(MAKE) --no-print-directory ui-start

ui-status: ## Report whether the UI is running
	@if pgrep -f "streamlit run $(APP)" >/dev/null 2>&1; then \
		echo "UI running -> http://localhost:$(PORT)"; \
	else \
		echo "UI not running."; \
	fi

ui-logs: ## Tail the UI logs
	@touch $(LOGFILE); tail -n 40 -f $(LOGFILE)

dump: ## Build the Neo4j dump for deploy seeding (DB must be STOPPED; see deploy/README.md)
	@mkdir -p $(DUMP_DIR)
	@echo "Dumping '$(DUMP_DB)' -> $(DUMP_DIR)/$(DUMP_DB).dump  (the database must be offline/STOPPED)"
	$(NEO4J_ADMIN) database dump $(DUMP_DB) --to-path=$(DUMP_DIR) --overwrite-destination=true
	@echo "Next: upload $(DUMP_DIR)/$(DUMP_DB).dump to Google Drive (share: anyone with link -> Viewer),"
	@echo "      then set DISCOVERY_GDRIVE_ID in deploy/.env."

deploy-build: ## Build the deploy stack images (Neo4j+seed, Geosupport, Streamlit)
	cd $(COMPOSE_DIR) && docker compose build

deploy-up: ## Build and start the deploy stack, detached (needs deploy/.env)
	@test -f $(COMPOSE_DIR)/.env || { echo "Create $(COMPOSE_DIR)/.env first: cp $(COMPOSE_DIR)/.env.example $(COMPOSE_DIR)/.env"; exit 1; }
	cd $(COMPOSE_DIR) && docker compose up -d --build

deploy-down: ## Stop the deploy stack (keeps volumes, so the seeded graph persists)
	cd $(COMPOSE_DIR) && docker compose down

deploy-logs: ## Tail the deploy stack logs
	cd $(COMPOSE_DIR) && docker compose logs -f

deploy-local: ## Smoke test locally against your running Neo4j Desktop graph (http://localhost:8501)
	cd $(COMPOSE_DIR) && docker compose -f docker-compose.local.yml up --build
