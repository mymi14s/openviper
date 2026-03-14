# ────────────────────────────────────────────────────────────────────────────
# OpenViper Makefile — Developer Workflow
# ────────────────────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON ?= python3
PIP ?= pip

SRC := openviper
TESTS := tests
ALL := $(SRC) $(TESTS)

# Colours (ANSI)
CYAN  := \033[36m
GREEN := \033[32m
RESET := \033[0m

# ── Help ────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help message
	@printf "$(CYAN)OpenViper$(RESET) — available targets:\n\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Installation ────────────────────────────────────────────────────────────
.PHONY: install install-dev install-pre-commit
install: ## Install the package in development mode
	$(PIP) install -e ".[dev,docs]"

install-dev: install install-pre-commit ## Install with pre-commit hooks

install-pre-commit: ## Install pre-commit hooks
	pre-commit install

# ── Formatting ──────────────────────────────────────────────────────────────
.PHONY: format format-check
format: ## Auto-format code with black & isort
	black $(ALL)
	isort $(ALL)

format-check: ## Check formatting without making changes
	black --check --diff $(ALL)
	isort --check-only --diff $(ALL)

# ── Linting ─────────────────────────────────────────────────────────────────
.PHONY: lint lint-ruff lint-flake8 lint-pylint
lint: lint-ruff lint-flake8 lint-pylint ## Run all linters

lint-ruff: ## Lint with ruff
	ruff check $(SRC)

lint-flake8: ## Lint with flake8
	flake8 $(SRC)

lint-pylint: ## Lint with pylint (source only)
	pylint $(SRC) --exit-zero

# ── Type checking ──────────────────────────────────────────────────────────
.PHONY: type-check
type-check: ## Run mypy static type checking
	mypy $(SRC)

# ── Testing ─────────────────────────────────────────────────────────────────
.PHONY: test test-fast test-verbose test-cov
test: ## Run the full test suite
	pytest $(TESTS)

test-fast: ## Run tests in parallel with xdist
	pytest $(TESTS) -n auto --dist loadscope

test-verbose: ## Run tests with verbose output
	pytest $(TESTS) -v --tb=short

test-cov: ## Run tests with coverage report
	pytest $(TESTS) --cov=$(SRC) --cov-report=term-missing --cov-report=html

# ── Quality (all-in-one) ───────────────────────────────────────────────────
.PHONY: quality
quality: format-check lint type-check test ## Run ALL quality checks (CI equivalent)

# ── Security ────────────────────────────────────────────────────────────────
.PHONY: security
security: ## Run security scans (bandit + safety)
	bandit -r $(SRC) -c pyproject.toml -q || true
	safety check || true

# ── Documentation ──────────────────────────────────────────────────────────
.PHONY: docs docs-serve
docs: ## Build Sphinx documentation
	cd docs && $(MAKE) html

docs-serve: docs ## Build docs and open in browser
	open docs/_build/html/index.html 2>/dev/null || xdg-open docs/_build/html/index.html

# ── Cleanup ─────────────────────────────────────────────────────────────────
.PHONY: clean clean-pyc clean-build clean-test clean-all
clean-pyc: ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true

clean-build: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info .eggs/

clean-test: ## Remove test & coverage artifacts
	rm -rf .pytest_cache/ htmlcov/ .coverage .mypy_cache/

clean: clean-pyc clean-build clean-test ## Remove all generated files

clean-all: clean ## Deep clean including .venv
	rm -rf .venv/
