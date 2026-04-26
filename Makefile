.PHONY: dev prod lint format metrics test test-integration

dev:
	docker-compose up --build

prod:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up --build

format:
	docker-compose run --rm web uv run ruff format .

lint: format
	docker-compose run --rm web uv run ruff check .
	docker-compose run --rm web uv run ruff format --check .
	docker-compose run --rm web uv run pyright
	docker-compose run --rm web uv run xenon --max-absolute B --max-modules A --max-average A .
	docker-compose run --rm web uv run bandit -r . -c pyproject.toml
	docker-compose run --rm web uv run detect-secrets scan --baseline .secrets.baseline

metrics:
	docker-compose run --rm web uv run radon raw -s .

test: test-unit test-integration

test-unit:
	docker-compose run --rm web uv run pytest

test-integration:
	docker-compose up -d --wait searxng searxng-valkey
	docker-compose run --rm web uv run pytest -m integration; \
	EXIT=$$?; docker-compose stop searxng searxng-valkey; exit $$EXIT
