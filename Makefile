.DEFAULT_GOAL := help

UV ?= uv
PYTEST_ARGS ?=

.PHONY: help install test test-fast lint lint-fix format format-check typecheck pre-commit verify

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

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
