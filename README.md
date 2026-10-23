# IdentityTwin — Behavioral Identity & Trust Gateway

> **Hackathon Security Product**: Behavioral identity verification and policy-enforced trust gateway for merchant payment operations.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-red.svg)](https://www.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Tests-435%20Passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

---

## 1. Executive Summary & Mission

IdentityTwin prevents account takeover, credential stuffing, and unauthorized money movement in merchant payment operations. Instead of treating identity as a binary login check, IdentityTwin continuously assesses behavioral signals (keystroke flight times, mouse trajectories, session anomalies) and routes protected operations through a **centralized Trust Gateway**.

This repository contains the **Backend Foundation and Trust Gateway (Person 1)**:
- Core FastAPI v1 REST application with structured logging and consistent error contracts.
- Centralized gateway routing policy enforcing 4 distinct trust levels.
- Protected payout execution sequence with database-backed idempotency guards.
- Safe payment provider adapter abstractions (`MockPaymentProviderAdapter`, `DecoyHoneyAdapter`, and official `PayPalSandboxAdapter`).
- Shared telemetry ingestion API (`POST /v1/events`) with 7 deterministic behavioral risk signals.
- Inbound PayPal webhook receiver (`POST /v1/webhooks/paypal`) with cryptographic signature verification and reconciliation.
- Incident review and approval APIs with strict Role-Based Access Control (RBAC).
- SQLAlchemy 2.0 models and Alembic migrations.
- Exported OpenAPI specification for frontend and team integration.
- Automated test suite covering all security invariants.

---

## 2. Architecture & Trust Gateway Policy

```mermaid
graph TD
    Client[Merchant Client / React App] -->|Events Telemetry| E[POST /v1/events]
    Client -->|Protected Payout| P[POST /v1/payouts]
    Analyst[Analyst Dashboard] -->|Incident Review| I[GET & POST /v1/incidents]
    PayPal[PayPal Webhooks] -->|Batch Reconcile| W[POST /v1/webhooks/paypal]

    subgraph TrustGateway[IdentityTwin Trust Gateway]
        Auth[Auth Guard & Session Scope]
        Idem[Idempotency & Duplicate Check]
        Risk[Risk Engine: 7 Named Signals]
        Policy[Centralized Policy Enforcement]
        Audit[Audit & Decision Logger]
    end

    P --> Auth
    E --> Auth
    I --> Auth
    W --> Idem

    Auth --> Idem --> Risk --> Policy --> Audit

    subgraph ExecutionDestinations[Enforced Routing Execution]
        Prov[Mock / PayPal Sandbox Provider]
        Decoy[Synthetic Honey Confinement]
        Rej[Step-Up Challenge Required]
        Block[Session Isolation Block]
    end

    Policy -->|Level 0: NORMAL Score < 30| Prov
    Policy -->|Level 1: RESTRICTED 30 <= Score < 60| Rej
    Policy -->|Level 2: DECOY 60 <= Score < 90| Decoy
    Policy -->|Level 3: ISOLATED Score >= 90 or Canary| Block

    Audit --> DB[(PostgreSQL / SQLite)]
```

### Trust Levels & Invariants (PRD Thresholds)

| Trust Level | Risk Score | Payout Action | Routing Destination | Security Invariant |
| :--- | :--- | :--- | :--- | :--- |
| **`NORMAL` (Level 0)** | `0.0 - 29.9` | `ALLOW` | `PROVIDER_MOCK` / `PROVIDER_PAYPAL` | Transaction proceeds to configured provider adapter exactly once. |
| **`RESTRICTED` (Level 1)** | `30.0 - 59.9` | `REQUIRE_STEP_UP` | `RESTRICTED_REJECT` | Payout limit enforced ($500.00). Step-up challenge token required. Never silently bypasses policy. |
| **`DECOY` (Level 2)** | `60.0 - 89.9` | `DECOY_FORWARD` | `DECOY_HONEY` | Routed exclusively to synthetic honey simulator. **Never moves funds or contacts PayPal.** |
| **`ISOLATED` (Level 3)** | `90.0 - 100.0` or Canary | `BLOCK` | `ISOLATED_BLOCK` | Payout blocked immediately. Session revoked/terminated. Auditable Incident recorded. |

---

## 3. Repository Structure

```
IdentityTwin/
├── apps/
│   └── api/
│       ├── app/
│       │   ├── main.py                     # Application factory, lifespan, CORS, middleware
│       │   ├── core/
│       │   │   ├── config.py               # Pydantic BaseSettings, production validation guards
│       │   │   ├── security.py             # AuthenticatedPrincipal, RBAC, dev-auth abstraction
│       │   │   └── exceptions.py           # Custom exception hierarchy & JSON error handler
│       │   ├── api/
│       │   │   ├── router.py               # Assembled API v1 and health routers
│       │   │   └── routes/
│       │   │       ├── health.py           # /health (liveness) & /ready (readiness)
│       │   │       ├── events.py           # POST /v1/events (telemetry ingestion)
│       │   │       ├── payouts.py          # POST /v1/payouts (protected gateway execution)
│       │   │       ├── sessions.py         # GET /v1/sessions & GET /v1/sessions/{id}
│       │   │       └── incidents.py        # GET & POST /v1/incidents (analyst approval)
│       │   ├── schemas/                    # Pydantic request/response schemas
│       │   ├── models/                     # SQLAlchemy 2.0 ORM models (incl. agent registry)
│       │   ├── db/
│       │   │   ├── session.py              # Engine, SessionLocal, get_db, readiness probe
│       │   │   └── repositories/           # Session, Event, Payout, Incident, Idempotency repos
│       │   ├── gateway/
│       │   │   ├── service.py              # Central TrustGatewayService (9-step execution)
│       │   │   ├── agentic.py              # Internal agentic commerce adapter & service
│       │   │   ├── policy.py               # Centralized TrustGatewayPolicy routing rules
│       │   │   ├── routing.py              # Routing decision models & destinations
│       │   │   └── provider.py             # Mock, PayPal Sandbox & honey decoy adapters
│       │   ├── risk/
│       │   │   ├── service.py              # Deterministic baseline risk engine & interface
│       │   │   └── schemas.py              # Risk evaluation models, named signals
│       │   └── services/                   # EventService, IncidentService
│       ├── tests/                          # 435 comprehensive automated tests
│       ├── alembic/                        # Database migration scripts
│       ├── alembic.ini                     # Alembic configuration
│       ├── pyproject.toml                  # Python package configuration & dependencies
│       └── Dockerfile                      # Production container definition
├── packages/
│   └── contracts/
│       ├── README.md                       # Contracts guide for other teammates
│       └── openapi.json                    # Exported OpenAPI 3.1.0 specification
├── docs/
│   ├── architecture.md                     # Architecture specification & Mermaid diagram
│   ├── agentic-commerce.md                 # Internal agentic commerce contract (Person 3)
│   ├── api-contracts.md                    # Detailed endpoint contracts and JSON payloads
│   ├── security-boundaries.md              # Security boundaries & production roadmap
│   └── local-development.md                # Local setup guide & command reference
├── scripts/
│   ├── seed_demo.py                        # Seeds test merchants, users, sessions, incidents
│   └── export_openapi.py                   # Exports openapi.json from live FastAPI app
├── .env.example                            # Safe environment variable placeholders
├── .gitignore                              # Git exclusion rules
├── docker-compose.yml                      # API and PostgreSQL orchestration
├── Makefile                                # Developer workflow commands
└── README.md
```

---

## 4. Quickstart Guide

### 1. Setup Environment
```bash
cp .env.example .env
make install
```

`make install` creates `.venv` and installs the API package in editable mode
(`pip install -e "apps/api[dev]"`). To install it by hand instead:
```bash
cd apps/api && python -m pip install -e ".[dev]"
```
See [`docs/local-development.md`](docs/local-development.md) §2.1.

### 2. Run Migrations & Seed Demo Data
```bash
make migrate
make seed
```

### 3. Start Development Server
```bash
make dev
```
API runs on `http://localhost:8000`.
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Liveness Probe: `http://localhost:8000/health`
- Readiness Probe: `http://localhost:8000/ready`

---

## 5. Automated Tests & Quality Checks

Run the automated test suite (435 tests covering all security boundaries, step-up verification, provider isolation matrix, agentic commerce authorization, and AST bypass checks):

```bash
make test
```

Run linting and formatting:
```bash
make lint
make format
```

Export OpenAPI contracts without drift:
```bash
make openapi
```

---

## 6. Teammate Handoff & Integration Matrix

| Teammate | Focus Area | Integration Touchpoint | Status |
| :--- | :--- | :--- | :--- |
| **Frontend** | React Dashboard | `packages/contracts/openapi.json` — Generate TypeScript types via `npx openapi-typescript`. | Contract Ready (20 paths) |
| **Person 2** | Risk Intelligence | Implement `IRiskEngineService` in `app/risk/service.py`. Consume `SecurityEvent` telemetry. | 7 Named Signals Connected |
| **Person 3** | PayPal Integration | `PayPalSandboxAdapter` in `app/gateway/provider.py`. Connect PayPal Sandbox credentials in `.env`. Internal agentic commerce adapter in `app/gateway/agentic.py` (`POST /v1/agentic/payouts`). | Sandbox Adapter Ready |
| **Person 4** | Honey Workspace | `DecoyHoneyAdapter` in `app/gateway/provider.py`. Confinement routing is automated. | Honey Routing Verified |
| **Person 5** | Evidence & Incidents | Consume `SecurityEvent`, `RiskDecisionRecord`, and `AnalystActionRecord` from database. | Evidence Integrity Ready |
| **Person 6** | AI Investigator | Read incident telemetry via `GET /v1/incidents/{id}`. | Read API Ready |

---

## 7. PayPal Sandbox Integration & Demo Setup

### Configuring Live PayPal Sandbox
To connect live PayPal Sandbox credentials for demo execution:
1. Log in to [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications/sandbox).
2. Create or select a REST API Sandbox Application.
3. Copy **Client ID** and **Secret** to your `.env`:
   ```bash
   PAYMENT_PROVIDER="paypal_sandbox"
   PAYPAL_CLIENT_ID="<your_sandbox_client_id>"
   PAYPAL_CLIENT_SECRET="<your_sandbox_client_secret>"
   PAYPAL_WEBHOOK_ID="<your_webhook_id>"
   PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com"
   ```
   `PAYPAL_BASE_URL` is **validated at startup against an explicit allowlist**
   of official PayPal Sandbox hosts (`api-m.sandbox.paypal.com` only). Any
   other value — the production host, a lookalike, a legacy Sandbox host, a
   non-`https` scheme, an embedded credential, a non-default port, or a URL
   with a path/query — aborts startup with a configuration error. The adapter
   enforces the same allowlist when it is built without an injected test
   transport, so a bad value cannot reach the network even if it bypasses
   settings initialization. Tests inject an `httpx.MockTransport` to point the
   adapter at a fake host without weakening this check.
   `PAYMENT_PROVIDER` is validated the same way: only `mock` or
   `paypal_sandbox` are accepted, and selecting `paypal_sandbox` with a missing
   or blank `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` **aborts startup**.
   Unknown values never silently fall back to the mock provider. The mock
   workflow never requires PayPal credentials.
4. Normal eligible payouts (`TrustLevel.NORMAL`) will automatically execute via official PayPal Payouts REST API (`/v1/payments/payouts`) with `PayPal-Request-Id` idempotency tracking.
5. In the absence of live PayPal credentials, use `PAYMENT_PROVIDER="mock"`, which provides safe synthetic transactions without network dependencies. Explicitly selecting `paypal_sandbox` without credentials is a startup error, not an automatic fallback.
6. **Webhook Verification**: `POST /v1/webhooks/paypal` verifies every delivery with PayPal's own `/v1/notifications/verify-webhook-signature` endpoint using `PAYPAL_WEBHOOK_ID`. A delivery is accepted only when PayPal answers `verification_status: SUCCESS`; a missing webhook id, a missing credential, a failed verification and a provider outage are all rejected with HTTP 400. See `docs/local-development.md` §7 for the local setup.

### Security Invariants & Notes
1. **Sandbox-Only Boundary**: The system is restricted to the PayPal Sandbox. The only accepted `PAYPAL_BASE_URL` is `https://api-m.sandbox.paypal.com`; the settings initializer rejects every production, lookalike, malformed or insecure value (see `apps/api/app/core/config.py`) and the adapter re-validates any programmatic override that is not paired with a mocked test transport. This is a configuration boundary, not a guarantee that live PayPal behaviour has been verified — see `docs/p3-paypal-integration-handoff.md` for what is tested versus untested against the real Sandbox.
2. **Development Authentication**: Uses static Bearer tokens and `X-Dev-*` headers for rapid local testing. In production (`ENVIRONMENT=production`), development authentication is strictly rejected; enterprise OIDC/OAuth2 with cryptographic JWKS validation must be configured.
3. **Canary Interaction Protection**: Any canary interaction immediately triggers Level 3 isolation, revokes the user session, and records an auditable incident regardless of initial risk score.



---

## 8. Agentic Commerce Integration (Person 3)

AI agents can act faster than any human, so IdentityTwin gives them **no privilege of their own**: an agent request is a *shape* that must be normalized into the canonical Trust Gateway request before anything can happen.

```
Agent request ──▶ internal adapter (authorize + normalize) ──▶ Trust Gateway ──▶ Provider / Honey / Block
```

- **Endpoint**: `POST /v1/agentic/payouts` (`apps/api/app/api/routes/agentic.py`).
- **Adapter**: `IAgenticCommerceAdapter` / `AgenticCommerceAdapter` / `AgenticCommerceService` in `apps/api/app/gateway/agentic.py`.
- **Contract**: `docs/agentic-commerce.md` (internal contract, request/response, error codes, idempotency rules).

### What an agent may and may not state
| Agent **may** state | Agent **may never** state |
| :--- | :--- |
| which registered agent it is (`agent_id`) | its own display name, type, vendor or scopes |
| which delegation authorizes it (`authorization_grant_id`) | trust level, risk score or routing destination |
| the intended transaction (recipient, amount, currency, note) | the merchant, the user or the risk outcome |
| its idempotency key and optional step-up token | any provider, endpoint or credential |

Everything else — merchant identity, agent identity, scopes, amount ceilings, trust level, routing — is resolved server side.

### Guarantees
1. **No bypass to PayPal**: the agentic path contains no provider adapter import; execution happens only inside `TrustGatewayService`.
2. **Fail-closed authorization**: unknown, foreign, suspended, expired, revoked, consumed, out-of-scope or over-limit delegations are rejected with HTTP 403 before any provider call.
3. **Risk parity**: `RESTRICTED` still requires step-up, `DECOY` still reaches only the honey workspace, `ISOLATED` is still blocked and opens an incident.
4. **Idempotency preserved & isolated**: the caller's key is forwarded verbatim (retries are deduplicated), and an agent may never reuse a key that belongs to a human payout or to another agent.
5. **Attribution**: every authorized attempt is written to `agentic_commerce_audit` (agent → grant → payout).

### Demo
```bash
make migrate && make seed     # seeds demo agent 7777... with grant 8888...
curl -X POST http://localhost:8000/v1/agentic/payouts \
  -H "Authorization: Bearer dev-merchant-token" -H "Content-Type: application/json" \
  -d '{"agent_id":"77777777-7777-7777-7777-777777777777",
       "authorization_grant_id":"88888888-8888-8888-8888-888888888888",
       "session_id":"22222222-2222-2222-2222-222222222222",
       "recipient_email":"vendor@example.com","amount":120.00,
       "currency":"USD","idempotency_key":"agentic-order-8842"}'
```
