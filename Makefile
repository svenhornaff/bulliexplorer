SRC := app tests
REMOTE := brooklyn@62.238.122.200
SSH_KEY := ~/.ssh/bulliexplorer_hetzner
SSH := ssh -i $(SSH_KEY)
RSYNC_EXCLUDE := --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
	--exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='.coverage' \
	--exclude='htmlcov' --exclude='.env' --exclude='.pi' --exclude='.DS_Store'

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
	uv run detect-secrets scan app/ > /tmp/secrets-scan.json && \
		python3 -c "\
import json, sys; \
a=json.load(open('.secrets.baseline')); b=json.load(open('/tmp/secrets-scan.json')); \
a.pop('generated_at',None); b.pop('generated_at',None); \
sys.exit(0 if a==b else (print('detect-secrets: baseline mismatch',file=sys.stderr) or 1))"
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

.PHONY: deploy
deploy: ci ## Deploy to production (runs ci first)
	rsync -avz $(RSYNC_EXCLUDE) -e "$(SSH)" ./ $(REMOTE):~/bulliexplorer/
	$(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml up -d --build && docker compose -f docker-compose.prod.yml exec app alembic upgrade head'

.PHONY: deploy-logs
deploy-logs: ## Tail production logs
	$(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml logs -f --tail=50'

.PHONY: deploy-status
deploy-status: ## Check production container status
	$(SSH) $(REMOTE) 'cd ~/bulliexplorer && docker compose -f docker-compose.prod.yml ps'

.PHONY: deploy-ssh
deploy-ssh: ## SSH into the server
	$(SSH) $(REMOTE)
