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
#    (equivalent to: python -m venv .venv && .venv/bin/pip install -e "apps/api[dev]")

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

## 2.1 Installing the API Package

The API is a normal Python distribution (`identitytwin-api`) whose import
package is `app`. Install it in editable mode from `apps/api`:

```bash
cd apps/api
python -m pip install -e ".[dev]"
```

* `-e` (editable) installs the package in "development mode": edits under
  `app/` are picked up immediately, no reinstall needed.
* The `dev` extra installs `pytest`, `pytest-asyncio` and `ruff`.
* The installation puts `app` on the import path, so `pytest`, `alembic`,
  `uvicorn` and the `scripts/` helpers work from any directory.

Only the application package is installed. The Alembic migration directory
(`apps/api/alembic/`), the test suite (`apps/api/tests/`) and the local
configuration files are development scaffolding and are deliberately **not**
part of the installed package - in particular `alembic` must never shadow the
real Alembic library used to run migrations.

Verify the installation:

```bash
cd apps/api
python -c "import app.main, alembic; print(app.main.__file__); print(alembic.__file__)"
python -m pytest tests/ -q
```

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
| **Demo AI Agent** | `77777777-7777-7777-7777-777777777777` | Registered shopping assistant, scope `payout:execute`, ceiling 500.00 |
| **Demo Agent Grant** | `88888888-8888-8888-8888-888888888888` | Delegation for the merchant user, ceiling 250.00, valid 30 days |

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
| `make test` | `make test` | Runs the full pytest suite across security invariants |
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
make dev
```

---

## 7. PayPal Webhook Configuration (Local)

`POST /v1/webhooks/paypal` never trusts a delivery on its face. Every inbound
event is verified with PayPal's own signature verification API
(`POST /v1/notifications/verify-webhook-signature`) using the configured
`PAYPAL_WEBHOOK_ID`. The event is accepted **only** when PayPal answers
`"verification_status": "SUCCESS"`.

Everything else is rejected with HTTP 400 `INVALID_WEBHOOK_SIGNATURE`:
a missing transmission header, a missing webhook id or missing credentials
(PayPal is not contacted at all), a body that is not a JSON object, a PayPal
`FAILURE` verification, a provider error status, a malformed provider
response, and a timeout or network failure.

There is **no development bypass**: a signature that merely *looks* plausible
is never accepted, in any environment. The mock payout adapter cannot verify
signatures, so it never accepts a webhook either.

### 7.1 Configure the credentials and the webhook id

Add to your `.env`:

```bash
# PayPal Sandbox REST app credentials
# (https://developer.paypal.com/dashboard/applications/sandbox)
PAYPAL_CLIENT_ID="<your_sandbox_client_id>"
PAYPAL_CLIENT_SECRET="<your_sandbox_client_secret>"

# Id of the webhook PayPal delivers to this deployment
PAYPAL_WEBHOOK_ID="<your_sandbox_webhook_id>"

# Sandbox host only - never a production endpoint
PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com"
```

`PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` are needed when the webhook
receiver is exercised locally, and are **mandatory at startup whenever
`PAYMENT_PROVIDER="paypal_sandbox"`** (a missing or blank value aborts startup;
`PAYMENT_PROVIDER="mock"` never requires them). The automatic test suite never
uses real credentials.

### 7.2 Find your `PAYPAL_WEBHOOK_ID`

1. Log in to the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications/sandbox)
   and open your Sandbox REST app.
2. Go to **Webhooks** and create (or open) the webhook whose delivery URL points
   at this deployment: `https://<your-host>/v1/webhooks/paypal`.
3. The **Webhook ID** column shows the id (for
   `https://api-m.sandbox.paypal.com/v1/notifications/webhooks/9AB12345...`
   the id is `9AB12345...`).
4. Alternatively list the webhooks of your app with the Sandbox API:
   ```bash
   curl -s -u "$PAYPAL_CLIENT_ID:$PAYPAL_CLIENT_SECRET" \
     "$PAYPAL_BASE_URL/v1/notifications/webhooks"
   ```
   The `id` field of the relevant webhook is the value for `PAYPAL_WEBHOOK_ID`.
5. Restart the API (`make dev`) so the new value is loaded.

### 7.3 Verify it locally

In the dashboard, open **Events -> Simulate -> Webhooks** and send an event to
your webhook. The API log shows the outcome:

```text
HTTP POST /v1/webhooks/paypal - status=200 duration=41.7ms ip=127.0.0.1
```

A rejected delivery logs `status=400` and the API answers with
`{"error": {"code": "INVALID_WEBHOOK_SIGNATURE", ...}}`.

### 7.4 Without a webhook id

If `PAYPAL_WEBHOOK_ID` (or the PayPal credentials) is not configured, **every**
delivery is rejected with HTTP 400 `INVALID_WEBHOOK_SIGNATURE` and PayPal is
never contacted. This is intentional: an unverifiable event is not an event,
and no configuration gap may open an unauthenticated write path into the
reconciliation logic.

### 7.5 Tests never need PayPal connectivity

`make test` runs completely offline. The webhook tests inject an
`httpx.MockTransport` for the OAuth and signature verification endpoints and
additionally fail the test if any code path tries to open a real socket:

- `apps/api/tests/test_webhook_verification.py` - fail-closed verification and
  receiver behaviour.
- `apps/api/tests/test_paypal_provider.py` - adapter level verification
  contract.



---

## 8. Agentic Commerce Demo (Local)

`make seed` also registers a demo AI agent and the delegation grant that
authorizes it, so the agentic path can be exercised immediately:

```bash
# 1. Normalize an agent payout through the Trust Gateway
curl -X POST http://localhost:8000/v1/agentic/payouts \
  -H "Authorization: Bearer dev-merchant-token" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_id": "77777777-7777-7777-7777-777777777777",
        "authorization_grant_id": "88888888-8888-8888-8888-888888888888",
        "session_id": "22222222-2222-2222-2222-222222222222",
        "recipient_email": "vendor@example.com",
        "amount": 120.00,
        "currency": "USD",
        "idempotency_key": "agentic-order-8842"
      }'

# 2. Unauthorized agent -> HTTP 403 AGENT_NOT_REGISTERED
curl -X POST http://localhost:8000/v1/agentic/payouts \
  -H "Authorization: Bearer dev-merchant-token" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"11111111-2222-3333-4444-555555555555", ...}'
```

Notes:

- The grant is a **delegation, not a credential**: the bearer token is still
  required, and the grant only authorizes the agent to act for the merchant
  user it was issued to.
- Repeating the request with the same `idempotency_key` returns the cached
  result (`is_duplicate: true`) and never executes the provider twice.
- The response and the `agentic_commerce_audit` table both carry the agent
  provenance. See `docs/agentic-commerce.md` for the full contract.
