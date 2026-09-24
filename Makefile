.PHONY: install-frontend install-backend install dev-frontend dev-backend \
	test-frontend test-backend lint typecheck format-check check

install-frontend: ## Install frontend dependencies from the lockfile
	cd frontend && npm ci

install-backend: ## Install backend dependencies from the lockfile
	cd backend && uv sync --frozen --extra dev

install: install-frontend install-backend ## Install all dependencies

dev-frontend: ## Start the Vite dev server
	cd frontend && npm run dev

dev-backend: ## Start the FastAPI dev server (http://127.0.0.1:8000)
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test-frontend: ## Run frontend tests (Vitest + Testing Library + axe)
	cd frontend && npm test

test-backend: ## Run backend tests (pytest)
	cd backend && uv run pytest

lint: ## Lint frontend (ESLint) and backend (Ruff)
	cd frontend && npm run lint
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .

typecheck: ## Type-check frontend (tsc) and backend (mypy)
	cd frontend && npm run typecheck
	cd backend && uv run mypy app

format-check: ## Verify formatting (Prettier + Ruff format)
	cd frontend && npm run format:check
	cd backend && uv run ruff format --check .

check: lint typecheck format-check test-frontend test-backend ## Run all required checks
