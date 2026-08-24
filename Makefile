SRC := app tests

.PHONY: build-env
build-env: ## Create .venv + install all dependencies
	uv sync

.PHONY: format
format: ## Format code (mutating)
	uv run ruff format $(SRC)
	uv run ruff check $(SRC) --fix

.PHONY: lint
lint: ## Lint + types (report only)
	uv run ruff format $(SRC) --check
	uv run ruff check $(SRC)
	uv run pyright $(SRC)

.PHONY: test
test: ## Run tests (coverage floor via addopts)
	uv run pytest

.PHONY: security
security: ## bandit + detect-secrets + pip-audit
	uv run bandit -r app -c pyproject.toml
	uv run detect-secrets scan app/ | diff .secrets.baseline -
	uv run pip-audit

.PHONY: dev
dev: ## Run the app locally with reload
	uv run uvicorn app.main:app --reload

.PHONY: db-upgrade
db-upgrade: ## Apply Alembic migrations
	uv run alembic upgrade head

.PHONY: db-revision
db-revision: ## Autogenerate a new migration — usage: make db-revision m="add campsite table"
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: clean
clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name htmlcov -exec rm -rf {} +

.PHONY: ci
ci: lint test security ## Full CI pipeline
