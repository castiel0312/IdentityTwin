# IdentityTwin Trust Console

React console for the IdentityTwin behavioral identity and trust gateway. The
console is a read/write client for the FastAPI backend in `apps/api`; it does
not score risk, approve policy, execute payouts, or simulate backend data in the
browser.

## Stack

- React 19, strict TypeScript, Vite 7
- Tailwind CSS 3 with shadcn/ui-style Radix primitives
- React Router 6, TanStack Query 5
- React Hook Form + Zod
- Recharts, Lucide
- OpenAPI-generated types from `packages/contracts/openapi.json`
- Vitest + React Testing Library, Playwright

## Run locally

The console expects the API to be running and seeded.

```bash
# From the repository root
cp .env.example .env
make install
make migrate
make seed
make dev
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/v1` and `/health` to
`http://127.0.0.1:8000` by default.

To target a different API during development:

```bash
VITE_API_PROXY=http://127.0.0.1:8010 npm run dev
```

For a separately hosted frontend, set `VITE_API_BASE_URL` at build time (for
example `https://api.example.com`) and configure backend CORS and
authentication for that origin. With no value, requests use same-origin `/v1`.

> The old root-level `identitytwin_dev.db` is not used by `make dev` or
> `make seed`. Both now operate on `apps/api/identitytwin_dev.db`.

## Authentication

### Development personas

The login page exposes development personas only when the frontend is running
with Vite's development build. Each persona is validated against
`GET /v1/system/context` before the session is accepted.

| Persona | Role | Purpose |
| --- | --- | --- |
| Merchant operator | merchant | Merchant data, payouts, read-only intelligence |
| Risk analyst | analyst | All read-only intelligence plus incident actions |
| Other merchant | merchant | Tenant-isolation demonstration; seeded with no records |

Development headers are sent only for development personas. The backend must be
running with `ALLOW_DEV_AUTH=true`; this is the local-development default. Never
enable development auth in production.

### Production token login

OIDC is still a backend `501` integration hook. Until it is implemented, the
production login form accepts a bearer token issued by your identity provider or
gateway. The token is validated against `/v1/system/context` and kept in
**`sessionStorage`**, scoped to the tab, never in `localStorage`. Signing out
clears it. A successful sign-in is not proof of token quality: use short-lived,
least-privilege tokens and standard XSS protections.

## Modules

| Module | Primary routes | Notes |
| --- | --- | --- |
| Overview | `/` | Server aggregate metrics and containment stream |
| Payouts | `/payouts`, `/payouts/:payoutId` | Review, confirm, execute, authoritative provider result |
| Risk intelligence | `/risk`, `/risk/decisions/:decisionId` | Read-only decisions, signals and configured weights |
| Incidents | `/incidents`, `/incidents/:incidentId` | Timeline, attack trace, seal, role-gated analyst actions |
| Sessions & identities | `/sessions`, `/sessions/:sessionId`, `/identities/:userId` | Live trust state, session activity and identity projections |
| Honey workspace | `/honey`, `/honey/:sessionId` | Synthetic decoy workspaces and canaries; no canary secrets rendered |
| Evidence vault | `/evidence`, `/evidence/:sealId` | Chain/checkpoint verification with explicit limits |
| Agentic commerce | `/agents`, `/agents/:agentId`, `/agents/audit` | Registered agents, scoped grants, agent-initiated payout flow |
| Simulation & calibration | `/simulation` | Deterministic scenario replay and the implemented incident drill |
| System & access | `/system` | Principal, environment, capabilities and development-auth disclosure |

## Backend authority and safety rules

- **No fabricated fallback.** API failures produce explicit error states. If the
  API is unreachable, the console does not substitute demo records.
- **No client-side scoring.** Risk scores, trust levels, policy actions and
  reason codes are rendered exactly as returned by the backend.
- **Consequential actions require review.** Payout confirmation and agentic
  payout submission both show a review step and require an explicit
  confirmation.
- **No generic payout retries.** Payout mutations use `retry: false`. A
  transport failure is reported as an unknown outcome and the user is directed
  to inspect the ledger. A new submission always uses a newly generated
  idempotency key, never an automatic replay.
- **Step-up before submission.** RESTRICTED payouts complete step-up
  verification before the payout request is submitted. The token is single-use
  and never retried.
- **Authoritative result.** The confirmation dialog shows the gateway's actual
  status, action, trust level, score, reason codes and provider reference,
  including rejection, decoy and blocked outcomes.
- **Tenant isolation.** Cross-tenant reads are rejected by the backend with 404;
  the console does not widen a principal's scope.
- **Honey isolation.** Honey detail renders only the operator-safe projection.
  Synthetic data is labelled and canary secrets, `raw_world_meta` and attacker
  credentials are never rendered.
- **Simulation guard.** The attack drill is available only outside production;
  a production rejection is displayed as a backend error, not simulated
  client-side.
- **Evidence honesty.** A passing verification proves consistency with the
  available chain and latest checkpoint/seal range. It does not prove database
  immutability, independent custody, or that an administrator could not alter
  records and re-seal them. Verification failures are distinguished from
  network/server failures.
- **SSE authentication.** Live events use authenticated `fetch` streaming to
  `GET /v1/events/stream`. The bearer token stays in the `Authorization` header,
  never in the query string. The client reconnects with `Last-Event-ID` and
  deduplicates replayed event ids. Native `EventSource` is not used because it
  cannot attach bearer headers.

## API contract

The checked-in OpenAPI contract is the source of truth for backend integration:

```bash
# From the repository root
make openapi
cd frontend
npm run openapi:types
```

`src/types/api.ts` is generated. Do not hand-edit it.

If the backend changes, run the backend tests, regenerate the contract, regenerate
the types, and run `npm run typecheck`.

## Verification

```bash
cd frontend

npm run typecheck   # strict TypeScript project build
npm run lint        # ESLint flat config
npm test            # Vitest + React Testing Library
npm run build       # production bundle
npm run test:e2e    # Playwright against an isolated backend
```

### End-to-end isolation

`npm run test:e2e` starts its own API and Vite server:

- API: `127.0.0.1:8010`
- Vite: `127.0.0.1:5174`
- Database: `apps/api/identitytwin_e2e.db` (deleted and re-seeded for every run)

It never mutates the developer database or reuses the developer servers. It
requires the repository virtualenv at `.venv` and runs the backend seed script
against the disposable E2E database.

## Current gaps

- OIDC/OAuth login is not implemented by the backend (`501`); production token
  login is a documented placeholder until the identity-provider flow exists.
- PayPal is sandbox-only. Webhook signature verification fails closed.
- The browser must not be treated as a trust boundary. Backend authorization,
  tenant scoping, step-up validation, idempotency and risk decisions remain
  authoritative.
- Evidence verification is consistency evidence, not a cryptographic
  immutability or independent-custody proof.
- The Playwright suite covers the main merchant and analyst journeys, not every
  permission/error permutation. Backend contract tests cover the projection
  endpoints.
- No automated accessibility audit (axe/WCAG conformance) is wired into CI yet;
  the UI uses labelled controls and Radix primitives, but this is not a formal
  conformance claim.
- The production bundle currently emits Vite's advisory for a chunk larger than
  500 kB. It builds successfully; route-level code splitting is a future
  optimization.
