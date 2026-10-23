# IdentityTwin API

The FastAPI service of **IdentityTwin** — the behavioral identity verification
and policy-enforced Trust Gateway for merchant payment operations.

This directory contains the installable Python distribution `identitytwin-api`
(the import package is `app`).

```text
apps/api/
├── app/            # import package (schemas, models, repositories, gateway, risk, api)
├── alembic/        # database migrations (not part of the installed package)
├── tests/          # automated test suite (not part of the installed package)
├── alembic.ini     # Alembic configuration
└── pyproject.toml  # build + tool configuration
```

## Install

From this directory:

```bash
python -m pip install -e ".[dev]"
```

`-e` installs the package in editable mode, so changes under `app/` are picked
up without reinstalling. The `dev` extra adds `pytest`, `pytest-asyncio` and
`ruff`.

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Test and lint

```bash
pytest tests/
ruff check app tests
ruff format --check app tests
```

## Documentation

- Repository overview, quickstart and integration matrix: [`../../README.md`](../../README.md)
- Architecture specification: [`../../docs/architecture.md`](../../docs/architecture.md)
- API contracts: [`../../docs/api-contracts.md`](../../docs/api-contracts.md)
- Security boundaries: [`../../docs/security-boundaries.md`](../../docs/security-boundaries.md)
- Agentic commerce contract: [`../../docs/agentic-commerce.md`](../../docs/agentic-commerce.md)
- Local development guide: [`../../docs/local-development.md`](../../docs/local-development.md)
