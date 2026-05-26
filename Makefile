.PHONY: dev prod prod-logs down lint lint-frontend lint-markdown lint-links format metrics readability test test-smoke test-unit test-integration test-js

dev:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml up --build

prod:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.prod.yml up --build

prod-logs: ## Tail logs from the running prod compose stack
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.prod.yml logs -f

down: ## Tear down this worktree's dev and prod compose stacks
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.prod.yml down --remove-orphans

format:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run ruff format .
	-docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run djlint src/odin/templates --reformat

lint: format lint-frontend lint-markdown lint-links
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run ruff check .
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run ruff format --check .
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run pyright
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run xenon --max-absolute B --max-modules A --max-average A src/
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run bandit -r src/ -c pyproject.toml

node_modules: package.json package-lock.json
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node sh -c "npm ci && touch node_modules"

lint-frontend: node_modules
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run djlint src/odin/templates --check
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node npx stylelint --config config/.stylelintrc.json "static/css/**/*.css"
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node npx eslint --config config/eslint.config.js "static/js/**/*.js"

lint-markdown: node_modules
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node npx markdownlint-cli2 --config config/.markdownlint.jsonc "**/*.md" "!node_modules" "!.git" "!.ruff_cache" "!.pytest_cache" "!.notes.md"

lint-links: node_modules
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node sh -c "find . -name '*.md' -not -path './node_modules/*' -not -path './.git/*' -not -path './.ruff_cache/*' -not -path './.pytest_cache/*' -not -name '.notes.md' -print0 | xargs -0 -n1 npx markdown-link-check --quiet --config config/.markdown-link-check.json"

metrics:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run radon raw -s .

readability:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run python scripts/readability.py

test: test-unit test-smoke test-integration

test-smoke:
	./scripts/test-smoke.sh

test-unit:
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm web uv run pytest
	$(MAKE) test-js

test-js: node_modules
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm node npx vitest run --config config/vitest.config.js

test-integration:
	START=$$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml up -d --wait odin-valkey; \
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml run --rm -e SMTP_TEST_RECIPIENT web uv run pytest -m integration; \
	TEST_EXIT=$$?; \
	docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml stop odin-valkey; \
	ERROR_LOGS=$$(docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.override.yml logs --no-color --since "$$START" 2>&1 | grep -E "ERROR|CRITICAL" || true); \
	if [ -n "$$ERROR_LOGS" ]; then \
		echo ""; \
		echo "Errors detected in service logs during integration tests:"; \
		echo "$$ERROR_LOGS"; \
		exit 1; \
	fi; \
	exit $$TEST_EXIT
