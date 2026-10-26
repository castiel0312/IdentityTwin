# IdentityTwin API Contracts

This directory contains the authoritative, machine-generated OpenAPI specification for the IdentityTwin backend API.

## Contracts File
- `openapi.json`: OpenAPI 3.1.0 specification generated directly from the FastAPI application.

## Exporting Updated Contracts
Whenever routes, Pydantic schemas, or validation rules change in `apps/api`, run:
```bash
make openapi
# or
PYTHONPATH=apps/api python scripts/export_openapi.py
```

## Subsystem Integration Guide

### 1. Frontend Teammate (React + TypeScript + Vite)
- The console lives in `frontend/` and consumes generated types from
  `frontend/src/types/api.ts`.
- Regenerate types after changing the contract:
  ```bash
  make openapi
  cd frontend && npm run openapi:types
  ```
- Stable endpoints include:
  - `POST /v1/events` for sending keystroke/mouse/navigation telemetry.
  - `GET /v1/sessions` and `GET /v1/sessions/{session_id}` for session trust badges.
  - `POST /v1/payouts` for executing protected merchant payouts.
  - `GET /v1/payouts` and `GET /v1/payouts/{payout_id}` for the payout ledger and authoritative result detail.
  - `POST /v1/agentic/payouts` for AI agent initiated payouts (internal adapter contract, see `docs/agentic-commerce.md`).
  - `GET /v1/incidents`, incident timeline/attack-trace/seal, and role-gated analyst actions.
  - `GET /v1/analytics/overview`, `GET /v1/risk/config`, `GET /v1/risk/decisions` and read-model projections for identities, agents, honey operator views, evidence seals, simulation/calibration and system context.
  - `GET /v1/events/stream` for authenticated SSE (bearer header, never a query token).
- See `frontend/README.md` for module coverage, authentication, test commands and
  security limitations. `POST /v1/stream` remains a `501` compatibility stub;
  the console uses `/v1/events/stream`.

### 2. Risk Intelligence Teammate (Person 2)
- Interface to implement: `apps/api/app/risk/service.py` (`IRiskEngineService`).
- Replace `DeterministicRiskEngineService` with your behavioral evaluation models.
- Consume stored events from `SecurityEvent` model (`apps/api/app/models/event.py`).
- Return `RiskEvaluationResult` populated with named risk signals (e.g. `MOUSE_VELOCITY_ANOMALY`, `IP_VELOCITY_ANOMALY`) and reason codes.
- Do NOT change gateway policy routing directly; emit your risk score (0-100) and evaluated trust level.

### 3. PayPal Integration Teammate (Person 3)
- Interface to implement: `apps/api/app/gateway/provider.py` (`IPaymentProviderAdapter`).
- Replace or configure `PAYMENT_PROVIDER=paypal_sandbox` in `.env`.
- Implement `PayPalSandboxAdapter` communicating with PayPal Sandbox REST APIs (v1/payments/payouts).
- Map real PayPal transaction IDs to `provider_reference` and preserve full provider response in `provider_payload`.
- **CRITICAL INVARIANT**: Your adapter will ONLY be invoked when the Gateway evaluates trust state as `NORMAL` / `ALLOW`. Under `RESTRICTED`, `DECOY`, or `ISOLATED`, the Gateway guarantees your adapter is NEVER called.
- Agentic commerce: the internal adapter `apps/api/app/gateway/agentic.py` (`IAgenticCommerceAdapter`) normalizes AI agent requests into the canonical `PayoutRequest` and delegates to the Trust Gateway. It never imports a provider adapter: agent traffic reaches PayPal only through the gateway. Contract: `docs/agentic-commerce.md`.

### 4. Honey Workspace Teammate (Person 4)
- Interface to implement: `apps/api/app/gateway/provider.py` (`DecoyHoneyAdapter`).
- Sessions in `DECOY` trust level are automatically routed to `RoutingDestination.DECOY_HONEY`.
- Maintain synthetic confinement state. Never forward requests to real payment processors.

### 5. Evidence & Incident Investigation Teammate (Person 5)
- Consume auditable records from:
  - `security_events`: All behavioral and security signals.
  - `risk_decisions`: Immutable decision logs with timestamp, score, and signals.
  - `analyst_actions`: Full audit trail of incident reviews, approvals, and resolutions.
- Read-only queries can use `IncidentRepository` and `GET /v1/incidents/{incident_id}`.

### 6. AI-Assisted Investigation Teammate (Person 6)
- Connect to `GET /v1/incidents/{incident_id}` to retrieve structured evidence summaries.
- Use read-only database connections or API client to synthesize investigation reports.
- Do NOT bypass the gateway to execute actions or modify trust levels directly.
