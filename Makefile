.DEFAULT_GOAL := help

UV ?= uv
PYTEST_ARGS ?=
LOAD_DSN ?= host=localhost port=5432 dbname=outbox user=postgres password=postgres
LOAD_EVENTS ?= 100000
LOAD_EVENT_TYPE ?= load.test

export LOAD_DSN LOAD_EVENTS LOAD_EVENT_TYPE

.PHONY: help install test test-fast lint lint-fix format format-check typecheck pre-commit verify \
	load-reset load-seed load-status load-drain load-sustained load-matrix load-lease-recovery

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install the project with development dependencies
	$(UV) sync --extra dev

test: ## Run the complete test suite
	$(UV) run pytest $(PYTEST_ARGS)

test-fast: ## Run tests quietly without coverage collection
	$(UV) run pytest -q --no-cov $(PYTEST_ARGS)

lint: ## Check Python code with Ruff
	$(UV) run ruff check src tests

lint-fix: ## Fix auto-fixable Ruff violations
	$(UV) run ruff check --fix src tests

format: ## Format Python code with Ruff
	$(UV) run ruff format src tests

format-check: ## Check Python formatting without modifying files
	$(UV) run ruff format --check src tests

typecheck: ## Run static type checks with Pyright
	$(UV) run pyright

pre-commit: ## Run all pre-commit hooks
	$(UV) run pre-commit run --all-files

verify: format-check lint typecheck test ## Run all verification checks

load-reset: ## Remove all events from the load-test database
	psql "$(LOAD_DSN)" -f load_tests/sql/reset.sql

load-seed: ## Insert LOAD_EVENTS pending benchmark events
	psql "$(LOAD_DSN)" -v event_count="$(LOAD_EVENTS)" -v event_type="$(LOAD_EVENT_TYPE)" -f load_tests/sql/seed.sql

load-status: ## Show event counts grouped by status
	psql "$(LOAD_DSN)" -v event_type="$(LOAD_EVENT_TYPE)" -f load_tests/sql/status.sql

load-drain: ## Seed and drain a finite event backlog
	bash load_tests/scripts/run_drain.sh

load-sustained: ## Produce events with pgbench while workers consume them
	bash load_tests/scripts/run_sustained.sh

load-matrix: ## Benchmark combinations of process and batch counts
	bash load_tests/scripts/run_matrix.sh

load-lease-recovery: ## Verify reclaim after an abrupt worker crash
	bash load_tests/scripts/run_lease_recovery.sh
