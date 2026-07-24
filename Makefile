# Simple Kanban — developer & demo shortcuts.
#
# Wraps the commands already documented in CLAUDE.md so a newcomer or agent can
# run one target instead of a multi-step sequence. Run `make` (or `make help`)
# to list everything.
#
#   make up    → the one-command full stack: `docker compose up --build`
#                (Postgres + the combined app image serving the built SPA,
#                mirroring the single production artifact per ADR 0003).
#   make dev   → the local hot-reload loop (Postgres in Docker, backend +
#                frontend running natively with live reload).
#
# Requires Docker (v2 `docker compose`), and — for the native dev/test targets —
# `uv` (backend) and `npm` (frontend). Recipe lines use TAB indentation.

# Directories
BACKEND  := backend
FRONTEND := frontend

# Per-worktree ephemeral DB (KAN-240). Each git worktree gets its own throwaway
# Postgres on a private port so parallel worktrees don't share :5432 (and one
# worktree's `alembic upgrade head` can't stamp a revision the others lack).
#   WT_SLUG — filesystem-safe name for THIS worktree (its directory basename).
#   WT_PORT — a stable host port derived from this worktree's absolute path
#             (deterministic per path, range ~15432–17431), so re-running
#             `make worktree-db` here always reuses the same port.
WT_SLUG := $(shell basename "$(CURDIR)")
WT_PORT := $(shell echo "$(CURDIR)" | cksum | awk '{print 15432 + ($$1 % 2000)}')
WT_DB_URL := postgresql+psycopg://kanban:kanban@localhost:$(WT_PORT)/kanban

# Per-worktree e2e ports (KAN-391). The e2e ports are ENV-overridable
# (FRONTEND_PORT / BACKEND_PORT, defaulting to 5173 / 8000) so a worktree run can
# dodge a foreign app squatting on the defaults. These derive stable, per-path
# offsets the same way WT_PORT does, so `make worktree-e2e` here always reuses the
# same ports and won't clash with the primary checkout's 5173/8000.
WT_FRONTEND_PORT := $(shell echo "$(CURDIR)fe" | cksum | awk '{print 5200 + ($$1 % 300)}')
WT_BACKEND_PORT  := $(shell echo "$(CURDIR)be" | cksum | awk '{print 8100 + ($$1 % 300)}')

.DEFAULT_GOAL := help

.PHONY: help up demo down down-v clean db install migrate dev \
        test test-integration e2e lint check \
        worktree-db worktree-db-url worktree-db-down worktree-e2e

help: ## Show this help (the default target)
	@awk 'BEGIN {FS = ":.*##"; printf "\nSimple Kanban — make targets\n\nUsage: make <target>\n\n"} \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
		END { printf "\n" }' $(MAKEFILE_LIST)

up: ## Full stack in Docker (db + app image serving the SPA) — the one-command loop; open http://localhost:8000
	docker compose up --build

demo: up ## Alias for `up` — the one-command demo of the whole app

down: ## Stop and remove the compose containers (keeps the pgdata volume)
	docker compose down

down-v: ## DESTRUCTIVE: `down` and also delete the Postgres data volume
	docker compose down -v

clean: down-v ## DESTRUCTIVE alias for `down-v` — tear everything down incl. the DB volume

db: ## Start just Postgres in the background (for the native hot-reload dev loop)
	docker compose up -d db

worktree-db: ## Start an EPHEMERAL Postgres for THIS worktree on its own port; prints the DATABASE_URL to export
	@if [ -z "$$(docker ps -q -f name=^/kanban-db-$(WT_SLUG)$$)" ]; then \
		docker rm -f kanban-db-$(WT_SLUG) >/dev/null 2>&1 || true; \
		docker run -d --rm --name kanban-db-$(WT_SLUG) \
			-e POSTGRES_USER=kanban -e POSTGRES_PASSWORD=kanban -e POSTGRES_DB=kanban \
			-p $(WT_PORT):5432 postgres:17 >/dev/null; \
		printf 'Starting kanban-db-%s on :%s ' "$(WT_SLUG)" "$(WT_PORT)"; \
	else \
		printf 'kanban-db-%s already running on :%s ' "$(WT_SLUG)" "$(WT_PORT)"; \
	fi
	@until docker exec kanban-db-$(WT_SLUG) pg_isready -U kanban -d kanban >/dev/null 2>&1; do \
		printf '.'; sleep 1; \
	done; echo ' ready.'
	@echo 'export DATABASE_URL=$(WT_DB_URL)'
	@echo '# ^ run the line above (or: export DATABASE_URL=$$(make -s worktree-db-url)) then `make migrate`'

worktree-db-url: ## Print just this worktree's DATABASE_URL
	@echo '$(WT_DB_URL)'

worktree-db-down: ## Stop & remove THIS worktree's ephemeral Postgres
	@docker rm -f kanban-db-$(WT_SLUG) >/dev/null 2>&1 && echo 'Removed kanban-db-$(WT_SLUG).' || echo 'No kanban-db-$(WT_SLUG) container to remove.'

worktree-e2e: ## Run Playwright e2e on THIS worktree's own ports + ephemeral DB (needs `make worktree-db` first)
	@echo 'e2e on frontend :$(WT_FRONTEND_PORT), backend :$(WT_BACKEND_PORT), db $(WT_DB_URL)'
	cd $(FRONTEND) && DATABASE_URL=$(WT_DB_URL) FRONTEND_PORT=$(WT_FRONTEND_PORT) BACKEND_PORT=$(WT_BACKEND_PORT) npm run e2e

install: ## Install deps: backend `uv sync` + frontend `npm ci`
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci

migrate: ## Apply DB migrations (backend `alembic upgrade head`)
	cd $(BACKEND) && uv run alembic upgrade head

dev: db migrate ## Local hot-reload loop: Postgres (Docker) + backend uvicorn --reload + Vite together; Ctrl-C stops both. Open http://localhost:5173
	@trap 'kill 0' EXIT; \
	(cd $(BACKEND) && uv run uvicorn app.main:app --reload) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

test: ## Fast backend unit tests (no DB / Docker needed)
	cd $(BACKEND) && uv run pytest tests/unit

test-integration: ## Backend integration tests vs a throwaway Postgres (needs a running Docker daemon)
	cd $(BACKEND) && uv run pytest tests/integration

e2e: ## Playwright frontend e2e smoke (run `make db` first — it needs a local Postgres)
	cd $(FRONTEND) && npm run e2e

lint: ## Lint backend (ruff) + frontend (svelte-check)
	cd $(BACKEND) && uv run ruff check .
	cd $(FRONTEND) && npm run check

check: lint ## Alias for `lint` — backend ruff + frontend svelte-check
