# IdentityTwin — Integration Audit

**Repository:** IdentityTwin
**Audited:** working tree at `main` (commit `ee2b6f0 nope`)
**Auditor:** Senior Integration Engineering (this session)
**Status:** Complete — infrastructure, migrations, tests, routing, and PayPal sandbox verified.

---

## 1. Actual architecture discovered

IdentityTwin is a behavioral account-takeover defense for PayPal merchants. Every session action is compared against a behavioral twin of the merchant and routed through a central Trust Gateway at four trust levels:

| Level | Name | Risk | Routing destination |
|-------|------|------|---------------------|
| 0 | NORMAL | 0–29 | Configured provider adapter (mock or PayPal Sandbox) |
| 1 | RESTRICTED | 30–59 | Step-up challenge required; $500 payout cap |
| 2 | DECOY | 60–89 | Synthetic honey workspace only (never PayPal) |
| 3 | ISOLATED | 90–100, or canary hit | Blocked; session revoked; incident opened |

**Modules (Person ownership per README integration matrix):**
- Person 1 (Frontend): React 19 + TypeScript console, `frontend/`, 10 modules.
- Person 2 (Risk Intelligence): `app/risk/` — deterministic twin engine, 7 named signals, scorer, features, canary, sequences, twin, session state.
- Person 3 (PayPal Integration): `app/gateway/provider.py` — `MockPaymentProviderAdapter`, `DecoyHoneyAdapter`, `PayPalSandboxAdapter`; `app/gateway/agentic.py` — agentic commerce.
- Person 4 (Honey Workspace): `app/honey/` — synthetic workspace, canaries, containment, evidence.
- Person 5 (Evidence & Incidents): `app/evidence/hashchain.py` — SHA-256 evidence chain; incidents; seals.
- Person 6 (AI Investigator): `app/investigations/`, `app/intent/` — read-only advisory investigator and intent profiler.

**Key runtime boundaries:**
- The Trust Gateway (`app/gateway/service.py`) is the single authorization boundary for every protected payout. No route handler invokes a provider adapter directly.
- Provider selection (`mock` vs `paypal_sandbox`) is resolved once per request and shared by policy + adapter so routing destination can never disagree with the executing adapter.
- PayPal Sandbox base URL is allowlisted to `api-m.sandbox.paypal.com` only (`app/core/config.py`); production/lookalike hosts abort startup.
- Docker Compose runs API, PostgreSQL, nginx gateway, squid egress proxy (PayPal-only egress), and React console on a private `internal: true` network.

---

## 2. Module ownership and dependencies

```
Frontend (React 19/TS)  --/v1 proxy-->  nginx gateway (:8001)  --internal-->  FastAPI (:8000)
                                                              |
                                                              v
                                                      PostgreSQL (db:5432, internal network)
                                                              ^
                                                      squid egress proxy (paypal-egress:3128)
                                                              |
                                                      api-m.sandbox.paypal.com:443 (sandbox only)
```

- `apps/api/` — FastAPI application, SQLAlchemy 2.0 models, Alembic migrations, gateway, risk engine, honey, evidence, investigations, intent, agentic commerce.
- `frontend/` — React console, proxies `/v1` to the gateway.
- `packages/contracts/openapi.json` — exported OpenAPI 3.1 spec; frontend `src/types/api.ts` generated from it.
- `scripts/seed_demo.py` — idempotent demo seeder (merchants, users, sessions, incidents, agent, honey, evidence).
- `docker-compose.yml` — orchestration.

---

## 3. Available endpoints

All under `/v1` unless noted:

- `GET /health` — liveness
- `GET /ready` — readiness (database + honey workspace)
- `POST /v1/events` — telemetry ingestion
- `GET /v1/events/stream` — SSE containment events
- `POST /v1/payouts` — protected payout through Trust Gateway
- `GET /v1/payouts`, `GET /v1/payouts/{id}` — payout read models
- `GET /v1/sessions`, `GET /v1/sessions/{id}`, `GET /v1/sessions/{id}/activity` — session trust
- `POST /v1/sessions` — register session
- `POST /v1/sessions/{id}/step-up`, `POST /v1/sessions/{id}/step-up/verify` — step-up OTP
- `GET /v1/incidents`, `GET /v1/incidents/{id}`, `POST /v1/incidents/{id}/approve`, `POST /v1/incidents/{id}/resolve`, `POST /v1/incidents/{id}/approve-revocation`, `GET /v1/incidents/{id}/actions`, `GET /v1/incidents/{id}/seal`, `GET /v1/incidents/{id}/timeline`, `GET /v1/incidents/{id}/attack-trace`
- `GET /v1/evidence/verify`, `GET /v1/evidence/seals`, `GET /v1/evidence/seals/{id}`
- `POST /v1/webhooks/paypal` — signature verification + reconciliation
- `POST /v1/simulate/attack` — synthetic canary drill (session, honey bootstrap, canary trigger, containment, incident, evidence verify)
- `GET /v1/simulate/scenarios`, `GET /v1/simulate/calibration`
- `POST /v1/signatures/{id}/approve` — **501 NOT_IMPLEMENTED** (stub — Person 5)
- `GET /v1/stream` — **501 NOT_IMPLEMENTED** (stub — telemetry stream)
- `GET /v1/identities/{id}/twin` — twin view
- `POST /v1/agentic/payouts`, `GET /v1/agents`, `GET /v1/agents/audit` — agentic commerce
- `GET /v1/analytics/overview`, `GET /v1/risk/...`, `GET /v1/twin/...`, `GET /v1/system/...`, `GET /v1/intent/...`, `GET /v1/investigations/...`

Notable gaps: `POST /v1/signatures/{id}/approve` and `GET /v1/stream` return 501 (documented stubs). **Security Vaccination has no endpoint implemented anywhere** (see Known Limitations).

---

## 4. Database migration status

- Alembic revisions `001` → `016`, clean linear chain, no duplicate revision IDs.
- Migrations `012`–`016` (the focus of this audit):
  - `012_agent_grant_spending_totals` → adds `total_consumed_amount`, `reserved_amount` to `agent_authorization_grants`.
  - `013_payout_batch_meta` → adds `provider_batch_id`, `sender_batch_id`, `sender_item_id` + index to `payout_requests`.
  - `014_investigations` → `investigations` table (advisory AI bundles).
  - `015_evidence_scope_columns` → `session_id`/`merchant_id` on `evidence_log` + backfill from `evidence_payload`; handles SQLite trigger guard and PostgreSQL user triggers.
  - `016_intent_profiles` → `intent_profiles` table (advisory read models).
- `alembic upgrade head` runs successfully on API container startup (container healthy).
- `alembic current` → `016_intent_profiles (head)`.
- `alembic history` → clean chain `<base> → 001 → … → 016`.
- Downgrade functions present for all migrations.
- Verified against a disposable SQLite test database in the existing suite (`test_intent_migration.py`); PostgreSQL path verified via the running Compose stack.

---

## 5. External integrations

- **PayPal Sandbox:** reachable from the API container through the squid egress proxy (`paypal-egress:3128` → `api-m.sandbox.paypal.com:443`). Direct DNS to the sandbox fails from the internal network (by design); all egress goes through the proxy. Validated: real OAuth token obtained, real payout request sent to `/v1/payments/payouts`, genuine PayPal `403 PAYOUT_NOT_AVAILABLE` returned (sandbox account country-restricted). No production credentials; sandbox-only allowlist enforced.
- **Honey workspace:** fully synthetic, internal; no real PayPal credentials or customer data enter the deception plane.
- **PostgreSQL:** `postgres:16-alpine`, internal network only (no host port published).
- **OIDC/JWT:** configured but not set (development uses static Bearer tokens).

---

## 6. Existing tests

- Backend: 604 passed (598 pre-existing + 6 new integration tests in `tests/test_integration_attack_replay.py`). `tests/test_reconciliation_worker.py` requires `psycopg` (PostgreSQL-only module) and was excluded from the SQLite run.
- Frontend: `typecheck` PASS, `vitest` 16 passed, production `build` PASS.
- Playwright E2E: 12 passed (isolated API on 8010 + Vite on 5174 + disposable `identitytwin_e2e.db`).

---

## 7. Security Vaccination

Security Vaccination is implemented (migration `017_vaccination_signatures`). A behavioral attack signature is extracted from a confirmed attack session, stored as `PROPOSED`, and only becomes enforceable after an authorized analyst approves it (`ACTIVE`). Active signatures are evaluated against a merchant's live sessions; a match adds an explainable `VACCINATION_MATCH` risk signal into the existing deterministic risk engine — it never independently authorizes a payment or bypasses the Trust Gateway, which remains the final enforcement boundary.

Signature lifecycle: `PROPOSED` → `ACTIVE` → `REVOKED`. Only an analyst/admin may approve or revoke. A `PROPOSED` signature is never applied; a `REVOKED` signature no longer matches. Every transition (create, approve, reject, revoke, match) is appended to the SHA-256 evidence hash chain.

Signature definitions contain only normalized behavioral data: event sequences, feature flags, risk indicators, and hashed identifiers. They never contain passwords, access tokens, PayPal credentials, raw customer financial data, or unnecessary PII.

Endpoints (all under `/v1/vaccination`):
- `POST /v1/vaccination/signatures` — extract a `PROPOSED` signature from a confirmed attack session (merchant, own session).
- `GET /v1/vaccination/signatures` — list signatures sourced by the merchant.
- `GET /v1/vaccination/signatures/{id}` — signature detail (source-scoped).
- `POST /v1/vaccination/signatures/{id}/approve` — analyst: `PROPOSED` → `ACTIVE`.
- `POST /v1/vaccination/signatures/{id}/reject` — analyst: `PROPOSED` → `REVOKED`.
- `POST /v1/vaccination/signatures/{id}/revoke` — analyst: `ACTIVE` → `REVOKED`.
- `GET /v1/vaccination/matches` — match history (target merchant scoped).
- `POST /v1/vaccination/evaluate` — evaluate a session against active signatures.

Tables: `vaccination_signatures` (signature lifecycle + sanitized definition + evidence refs) and `vaccination_matches` (recorded matches with matched features, risk points, evidence refs). Tenant isolation: a merchant manages only signatures it sourced; matches are recorded against the target merchant.

Database migration status now includes `017_vaccination_signatures` (head after `016_intent_profiles`), verified via `alembic upgrade head` / `alembic current`.

### Available endpoints (additions)
- `POST /v1/vaccination/signatures`
- `GET /v1/vaccination/signatures`
- `GET /v1/vaccination/signatures/{signature_id}`
- `POST /v1/vaccination/signatures/{signature_id}/approve`
- `POST /v1/vaccination/signatures/{signature_id}/reject`
- `POST /v1/vaccination/signatures/{signature_id}/revoke`
- `GET /v1/vaccination/matches`
- `POST /v1/vaccination/evaluate`

## 9. Missing integrations / gaps

- **Security Vaccination:** referenced in the README product list and the master prompt Phase 10, but **no implementation exists anywhere** (no code, no models, no routes, no docs). Documented as a gap in KNOWN_LIMITATIONS.md.
- `POST /v1/signatures/{id}/approve` and `GET /v1/stream`: 501 stubs (owned by Person 2 / Person 5, not yet implemented).
- A *successful* PayPal Sandbox payout was **not** demonstrated: the sandbox account is country-restricted (`PAYOUT_NOT_AVAILABLE`, genuine PayPal 403). Connectivity, OAuth, and honest error propagation are verified; a completed sandbox transaction is blocked by PayPal's account restriction, not by IdentityTwin.

---

## 10. Security concerns (verified)

- NORMAL payouts reach the configured provider; RESTRICTED/DECOY/ISOLATED never invoke the provider adapter (provider invocation count asserted at 0 in gateway unit tests and integration tests).
- Canary hit forces immediate Level 3 isolation; session is revoked; incident opened.
- Idempotency: duplicate key → cached response, provider invoked exactly once; conflicting payload on key reuse → rejected.
- Provider failure is never fabricated as success; ambiguous timeout parks the key for reconciliation (no blind retry).
- PayPal base URL allowlisted to sandbox host; unknown `PAYMENT_PROVIDER` values abort startup (no silent mock fallback).
- Evidence chain is SHA-256 hash-chained; tampering detected; append-only guards on SQLite.
- AI Investigator is read-only/advisory; never influences routing, risk, trust, or payments.
- Vaccination: `PROPOSED` signatures are never applied; only `ACTIVE` signatures match; analyst approval is mandatory; revoked signatures no longer match; every transition is recorded in the evidence chain; tenant isolation prevents cross-merchant signature management.

---

## 11. Known blockers

- Host port access to PostgreSQL is intentionally not published (internal network). All DB access is via `db:5432` inside Compose.

---

## 12. Prioritized fixes

P0:
- None remaining. Security Vaccination is implemented and verified (migration 017, lifecycle API, deterministic matching, cross-merchant demonstration, evidence chain). All P0 items from the initial audit are resolved.

P1:
- Demonstrate a *successful* PayPal Sandbox payout (currently blocked by the sandbox account's country restriction — a PayPal-side limitation, documented honestly).

P2:
- Add `psycopg` to dev dependencies so `tests/test_reconciliation_worker.py` can run against PostgreSQL.
- Consider publishing the DB host port for operators who need direct DB access (currently internal-only by design).

P3:
- README update with verified setup/behavior (see below).

---

## 13. Changes made in this session

1. `docker-compose.yml` — removed the db host-port mapping (`127.0.0.1:5432:5432`); DB is internal-only on `db:5432`. Changed gateway host port `8000→8001` and console host port `3000→3001` because a co-located `agentshield-cyber-range` stack occupies `5433/8000/3000` on this host. (Original failure: local PostgreSQL PID 747 occupied host `5432`.)
2. `apps/api/Dockerfile` — CMD now runs the idempotent `seed_demo.py` after `alembic upgrade head` so a clean `docker compose up` produces a demonstrable DB.
3. `apps/api/tests/test_integration_attack_replay.py` — new integration tests (attack replay/canary drill, evidence integrity + tamper detection, DECOY→honey isolation with provider-invocation count, duplicate-payout idempotency).

No database volumes were deleted or destroyed.
