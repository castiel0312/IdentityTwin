.PHONY: install dev test lint format migrate openapi seed clean

PYTHON ?= python3
VENV ?= .venv
PIP ?= $(VENV)/bin/pip
PYTEST ?= $(VENV)/bin/pytest
RUFF ?= $(VENV)/bin/ruff
UVICORN ?= $(VENV)/bin/uvicorn
ALEMBIC ?= $(VENV)/bin/alembic

install:
	@echo "Creating virtual environment and installing dependencies..."
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e apps/api[dev] || $(PIP) install "fastapi>=0.100.0" "uvicorn[standard]>=0.23.0" "pydantic>=2.0" "pydantic-settings>=2.0" "sqlalchemy>=2.0.0" "alembic>=1.12.0" "httpx>=0.24.0" "pytest>=7.0.0" "psycopg2-binary>=2.9.0" "ruff>=0.1.0"
	@echo "Installation complete."

dev:
	@echo "Starting IdentityTwin API development server..."
	cd apps/api && PYTHONPATH=. ../../$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

test:
	@echo "Running test suite..."
	cd apps/api && PYTHONPATH=. ../../$(PYTEST) -v tests/

lint:
	@echo "Running linter..."
	$(RUFF) check apps/api/app apps/api/tests scripts

format:
	@echo "Formatting code..."
	$(RUFF) format apps/api/app apps/api/tests scripts

migrate:
	@echo "Running database migrations..."
	cd apps/api && PYTHONPATH=. ../../$(ALEMBIC) upgrade head

openapi:
	@echo "Exporting OpenAPI specification to packages/contracts/openapi.json..."
	PYTHONPATH=apps/api $(VENV)/bin/python scripts/export_openapi.py

seed:
	@echo "Seeding demo database with test principals, sessions, and incidents..."
	PYTHONPATH=apps/api $(VENV)/bin/python scripts/seed_demo.py

clean:
	rm -rf .pytest_cache .ruff_cache apps/api/.pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f identitytwin_dev.db identitytwin_test.db
