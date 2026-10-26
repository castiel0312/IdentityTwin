# Frontend Delivery Report

Date: 2026-10-26

## Scope

Delivered a React 19 + strict TypeScript console for all ten IdentityTwin modules,
backed by the existing FastAPI service:

1. Overview
2. Payouts and payout detail
3. Risk intelligence and decision detail
4. Incidents and incident detail
5. Sessions & identities, session detail and identity detail
6. Honey workspace and workspace detail
7. Evidence vault and seal detail
8. Agentic commerce, agent detail and audit trail
9. Simulation & calibration
10. System & access

The console includes responsive layouts, loading/empty/error/success states,
permission-denied states, keyboard-accessible Radix primitives, typed forms,
pagination, filtering and detail navigation.

## Backend additions

Backend changes are read-only projections and narrowly scoped workflow helpers.
They do not move scoring, policy or payout execution into the frontend.

- Added read-model routes/services for payouts, analytics, system context,
  identities, agents, evidence seals, honey operator views, risk
  configuration/decisions, session activity, incident filters/actions/seal,
  and simulation/calibration.
- Added `apps/api/tests/test_read_models.py` contract tests.
- Extended the deterministic seed with payout, risk, event, twin, incident,
  agent, evidence, honey and canary records.
- Corrected the seeded behavioral twin to store salted device hashes, coarse IP
  buckets and hashed recipients, matching the risk engine's comparison model.
  Re-running `make seed` now repairs those demo baselines in an existing
  development database as well.
- Fixed `make seed` to seed `apps/api/identitytwin_dev.db`, the database used by
  `make dev`.
- Regenerated `packages/contracts/openapi.json` (64 paths) and
  `frontend/src/types/api.ts`.

## Security and correctness decisions

- Backend remains authoritative for authentication, tenant isolation, scoring,
  policy, payout execution, idempotency, incidents and evidence.
- No client-side risk scoring and no fabricated API fallback.
- Payout and agentic payout mutations use explicit `retry: false`; a transport
  failure is reported as an unknown outcome. A new user-initiated attempt uses a
  new idempotency key.
- Consequential payouts require review and confirmation. RESTRICTED payouts
  require verified single-use step-up before submission.
- Provider outcomes are rendered from the gateway response, including rejected,
  blocked and decoy outcomes.
- Cross-tenant resource reads return 404; the console does not widen scope.
- Honey operator views are separate read-only projections. Canary secrets and
  `raw_world_meta` are not rendered.
- Simulation exposes only the implemented backend drill and surfaces production
  rejection rather than simulating a pass locally.
- Evidence copy states that a passing result proves chain/checkpoint consistency,
  not database immutability, independent custody or tamper-proof administration.
- SSE uses authenticated `fetch` streaming with bearer headers, reconnects with
  `Last-Event-ID`, deduplicates replayed ids, and never puts the token in a query
  string.
- Development personas are available only in the Vite development build and are
  visibly labelled development-only. Production login currently uses a pasted
  bearer token stored in tab-scoped `sessionStorage`, never `localStorage`.

## Verification results

### Backend

```text
ruff check apps/api/app apps/api/tests scripts
All checks passed!

pytest -o addopts="-ra"
469 passed, 1 warning in 11.06s
```

The warning is Starlette's upstream `httpx` TestClient deprecation notice.

```text
make openapi
Total API Paths: 64

cd frontend && npm run openapi:types
Generated from packages/contracts/openapi.json
```

### Frontend

```text
npm run typecheck
Passed (tsc -b --noEmit)

npm test
Test Files  5 passed (5)
Tests       18 passed (18)

npm run lint
0 errors, 5 warnings
```

All five lint warnings are `react-refresh/only-export-components` advisories for
shared UI variant and auth context exports. There are no lint errors.

```text
npm run build
Passed
dist/assets/index-*.js    1,289.81 kB | gzip: 366.63 kB
dist/assets/index-*.css      37.71 kB | gzip:   7.73 kB
```

Vite emits a chunk-size advisory above 500 kB and removes annotation comments
inside Zod's distributed files. The build itself succeeds.

```text
npx playwright test
10 passed (14.9s)
```

Playwright uses an isolated API on `127.0.0.1:8010`, Vite on
`127.0.0.1:5174`, and the disposable SQLite database
`apps/api/identitytwin_e2e.db`.

Covered E2E journeys:

- All-module navigation with no fabricated fallback
- Payout filtering and authoritative detail
- One-shot payout review, execution and gateway result
- Evidence chain/seal verification wording
- Agentic payout with server-resolved grant and recorded outcome
- Synthetic drill execution and real record links
- Merchant role denial for incident actions
- Development-auth disclosure and sign-out cleanup
- Real API-unreachable failure state
- Analyst-only incident actions

### Unit/integration tests

- Auth: development sessions, token persistence, no `localStorage` writes,
  unauthorized sign-out.
- API client: typed requests, error mapping, no generic retries.
- SSE: parser, dedupe, reconnect with `Last-Event-ID`, unauthorized status.
- Payout dialog: single submission despite a retrying query client; RESTRICTED
  step-up token propagation.
- Incident actions: server-authorized rendering and permission-denied state.

## Known gaps

1. OIDC is still a backend `501` hook. Production authentication is a pasted
   bearer token. This is a placeholder, not a complete IdP login flow.
2. Tokens are stored in tab-scoped `sessionStorage`. This is not `localStorage`,
   but it is still accessible to successful XSS. Short-lived least-privilege
   tokens and CSP/XSS hardening remain required.
3. PayPal is sandbox-only. Webhook verification fails closed. No real funds are
   moved by the demo.
4. Evidence verification is consistency evidence, not proof of immutability,
   independent custody or absence of administrator tampering.
5. The simulation drill writes synthetic records into the tenant database and is
   disabled in production. A successful drill is not production fraud proof.
6. The E2E suite runs Chromium only against SQLite. Cross-browser and
   PostgreSQL-backed E2E runs are not part of this delivery.
7. No automated axe/WCAG conformance suite is wired into CI. The UI uses
   labelled controls and accessible Radix primitives, but this is not a formal
   accessibility certification.
8. The production bundle currently emits a chunk-size advisory. Route-level code
   splitting is a future optimization.
9. `/v1/stream` and `/v1/signatures/{id}/approve` remain backend `501` stubs. The
   console uses the implemented `/v1/events/stream` SSE endpoint.
10. All work remains uncommitted; nothing was committed as part of this delivery.
