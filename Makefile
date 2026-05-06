.PHONY: dev prod prod-logs lint lint-frontend format metrics test test-smoke test-unit test-integration test-js

dev:
	docker compose up --build

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build

prod-logs: ## Tail logs from the running prod compose stack
	docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

format:
	docker compose run --rm web uv run ruff format .
	-docker compose run --rm web uv run djlint src/odin/templates --reformat

lint: format lint-frontend
	docker compose run --rm web uv run ruff check .
	docker compose run --rm web uv run ruff format --check .
	docker compose run --rm web uv run pyright
	docker compose run --rm web uv run xenon --max-absolute B --max-modules A --max-average A src/
	docker compose run --rm web uv run bandit -r src/ -c pyproject.toml
	docker compose run --rm web uv run detect-secrets scan --baseline .secrets.baseline

node_modules: package.json package-lock.json
	docker compose run --rm node sh -c "npm ci && touch node_modules"

lint-frontend: node_modules
	docker compose run --rm web uv run djlint src/odin/templates --check
	docker compose run --rm node npx stylelint "src/odin/static/css/**/*.css"
	docker compose run --rm node npx eslint "src/odin/static/js/**/*.js"

metrics:
	docker compose run --rm web uv run radon raw -s .

test: test-unit test-smoke test-integration

test-smoke:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml build web
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait web; \
	EXIT=$$?; \
	docker compose -f docker-compose.yml -f docker-compose.prod.yml stop web; \
	exit $$EXIT

test-unit:
	docker compose run --rm web uv run pytest
	$(MAKE) test-js

test-js: node_modules
	docker compose run --rm node npx vitest run

test-integration:
	START=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	docker compose up -d --wait searxng searxng-valkey; \
	docker compose run --rm web uv run pytest -m integration; \
	TEST_EXIT=$$?; \
	docker compose stop searxng searxng-valkey; \
	ERROR_LOGS=$$(docker compose logs --no-color --since "$$START" 2>&1 | grep -E "ERROR|CRITICAL" | grep -v "searx.botdetection" | grep -v "searx.engines" | grep -v "searx.search.processor" || true); \
	if [ -n "$$ERROR_LOGS" ]; then \
		echo ""; \
		echo "Errors detected in service logs during integration tests:"; \
		echo "$$ERROR_LOGS"; \
		exit 1; \
	fi; \
	exit $$TEST_EXIT
