.PHONY: help install lint fmt typecheck test test-unit test-integration up down logs clean

help:
	@echo "Aurelius Capital — development commands"
	@echo ""
	@echo "  install          Install dependencies"
	@echo "  lint             Run ruff linter"
	@echo "  fmt              Format code with ruff"
	@echo "  typecheck        Run mypy"
	@echo "  test-unit        Run unit tests (no Docker needed)"
	@echo "  test-integration Run integration tests (Docker needed)"
	@echo "  test             Run all tests"
	@echo "  up               Start Docker stack"
	@echo "  down             Stop Docker stack"
	@echo "  logs             Tail application logs"
	@echo "  clean            Remove containers and volumes"

install:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/aurelius

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	docker compose -f docker-compose.test.yml up -d --wait
	pytest tests/integration/ -v --tb=short; \
	docker compose -f docker-compose.test.yml down

test: test-unit test-integration

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
