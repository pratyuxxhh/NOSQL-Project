# Shortcuts for common tasks. Each target is a plain command you can also run directly
# (useful on Windows, where `make` is not installed by default).

.PHONY: up down logs ps seed simulate evaluate benchmark detect test test-backend test-frontend clean

up:         ## Build and start Neo4j, PostgreSQL, backend and frontend
	docker compose up --build -d

down:       ## Stop all services (data volumes are kept)
	docker compose down

logs:       ## Follow logs from all services
	docker compose logs -f

ps:         ## Show service status
	docker compose ps

seed:       ## Load synthetic data with planted rings, users (admin/analyst/viewer) and a simulator API key
	docker compose exec backend python -m app.seed

simulate:   ## Stream live transactions (Ctrl+C to stop)
	docker compose exec backend python -m app.simulator --rate 10 --fraud-every 20

evaluate:   ## Precision / recall / F1: rules vs graph vs graph + propagation
	docker compose exec backend python -m app.evaluation

benchmark:  ## Neo4j vs PostgreSQL traversal benchmark (depth 1-6)
	docker compose exec backend python -m app.benchmark

test: test-backend test-frontend   ## Run all tests

test-backend:   ## Backend unit + integration tests with coverage (needs backend/.venv and Docker)
	cd backend && .venv/bin/python -m pytest --cov=app --cov-report=term-missing

test-frontend:  ## Dashboard smoke tests
	cd frontend && npm test

clean:      ## Stop all services AND delete all data volumes
	docker compose down -v
