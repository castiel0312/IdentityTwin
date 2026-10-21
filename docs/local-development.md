# IdentityTwin Local Development Guide

This guide walks you through setting up and running the IdentityTwin Trust Gateway API locally.

---

## 1. Prerequisites

- **Python**: 3.11 or higher
- **Make**: Available on macOS and Linux
- **Docker & Docker Compose** *(Optional, for PostgreSQL testing)*
- **Node.js 18+** *(Optional, for frontend client code generation)*

---

## 2. Quickstart (Under 2 Minutes)

```bash
# 1. Clone repository and navigate to root
cd IdentityTwin

# 2. Copy development environment file
cp .env.example .env

# 3. Create virtual environment and install dependencies
make install

# 4. Run database migrations
make migrate

# 5. Seed test data (merchants, users, sessions in all 4 trust states, and incidents)
make seed

# 6. Start the API development server
make dev
```

The API will be running at `http://localhost:8000`.
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc Documentation: `http://localhost:8000/redoc`
- OpenAPI JSON Schema: `http://localhost:8000/openapi.json`
- Liveness Probe: `http://localhost:8000/health`
- Readiness Probe: `http://localhost:8000/ready`

---

## 3. Pre-Seeded Development Entities

Running `make seed` populates the local database with deterministic test fixtures:

| Entity | UUID / Value | Description |
| :--- | :--- | :--- |
| **Merchant ID** | `00000000-0000-0000-0000-000000000001` | Acme Payments Demo Co. |
| **Merchant User** | `11111111-1111-1111-1111-111111111111` | `merchant-dev@identitytwin.local` (`merchant` role) |
| **Analyst User** | `00000000-0000-0000-0000-000000000002` | `analyst-dev@identitytwin.local` (`analyst` role) |
| **Normal Session** | `22222222-2222-2222-2222-222222222222` | Trust: `NORMAL` (Score: 0.0) — Payouts succeed |
| **Restricted Session**| `33333333-3333-3333-3333-333333333333` | Trust: `RESTRICTED` (Score: 55.0) — Payouts rejected (step-up required) |
| **Decoy Session** | `44444444-4444-4444-4444-444444444444` | Trust: `DECOY` (Score: 75.0) — Payouts routed to honey simulator |
| **Isolated Session** | `55555555-5555-5555-5555-555555555555` | Trust: `ISOLATED` (Score: 95.0) — Payouts blocked |
| **Demo Incident** | `66666666-6666-6666-6666-666666666666` | Open anomaly incident ready for analyst review |

---

## 4. Development Authentication Headers

When testing with `curl`, Postman, or HTTP clients:

### Merchant Call:
```bash
curl -X POST http://localhost:8000/v1/payouts \
  -H "Authorization: Bearer dev-merchant-token" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "22222222-2222-2222-2222-222222222222",
    "recipient_email": "contractor@supplier.com",
    "amount": 500.00,
    "currency": "USD",
    "idempotency_key": "unique-client-key-101"
  }'
```

### Analyst Call:
```bash
curl -X POST http://localhost:8000/v1/incidents/66666666-6666-6666-6666-666666666666/approve \
  -H "Authorization: Bearer dev-analyst-token" \
  -H "Content-Type: application/json" \
  -d '{
    "notes": "Verified secondary authentication factor with merchant admin."
  }'
```

---

## 5. Makefile Command Reference

| Target | Command | Description |
| :--- | :--- | :--- |
| `make install` | `make install` | Creates virtualenv `.venv` and installs all dependencies |
| `make dev` | `make dev` | Launches FastAPI server on `0.0.0.0:8000` with hot reload |
| `make test` | `make test` | Runs the full 27-test pytest suite across security invariants |
| `make lint` | `make lint` | Runs Ruff linter across application code, tests, and scripts |
| `make format` | `make format` | Formats all code with Ruff formatter |
| `make migrate` | `make migrate` | Executes Alembic migrations (`alembic upgrade head`) |
| `make seed` | `make seed` | Populates demo data and test fixtures |
| `make openapi` | `make openapi` | Exports `packages/contracts/openapi.json` from live application |
| `make clean` | `make clean` | Removes pytest caches, temp DBs, and bytecode |

---

## 6. PostgreSQL & Docker Compose (Optional)

To run with PostgreSQL instead of the default local SQLite database:

```bash
# 1. Start PostgreSQL container
docker compose up -d db

# 2. Update .env:
# DATABASE_URL="postgresql://identitytwin_user:identitytwin_pass@localhost:5432/identitytwin"

# 3. Run migrations and seed PostgreSQL
make migrate
make seed

# 4. Start API container or run local dev
docker compose up api
```
