# SESSION CREATION PERMISSION AUDIT

**Scope:** Why a Merchant Operator can view sessions on a selected customer identity but cannot create a new session.

**Audit method:** Static code and contract review only. Per the engagement constraints, **no commands were executed against a running system, no code was changed, and no live sessions were interrupted or exercised.** All findings are file/line-verified against the repository at commit `86e287a`.

---

## FINAL DECISION: INTENTIONALLY RESTRICTED

Merchant Operator session creation **on behalf of a selected customer identity is intentionally out of the product's permission model.** It is not a missing button, a stalled refactor, a dead feature flag, or a defect.

A Merchant Operator **can** create exactly one kind of session: their **own** (self-registration). Creating a session for the identity profile being viewed is deliberately excluded from every role. The restriction is enforced by construction on the backend (the create endpoint is hard-bound to the authenticated principal's own `user_id`), not merely by hiding a button on the frontend.

---

## 1. Role mapping

The codebase has three RBAC roles (`apps/api/app/core/security.py:22-25`, `RoleEnum`):

| Brief terminology | Codebase role | Console persona | Notes |
|---|---|---|---|
| Merchant Operator | `merchant` | "Merchant operator" (`dev-merchant-token`, `frontend/src/lib/auth-types.ts:36-47`) | Merchant-scoped tenant user |
| Merchant Admin | **no distinct role exists** | — | Tenant admins are represented by the same `merchant` role; there is no separate `merchant_admin` role in `RoleEnum`, the `users.role` column (`app/models/principal.py:41`), or the console personas |
| Platform Admin | `admin` | — (`X-Dev-Role: admin` in dev auth only) | `require_role()` grants admin a global pass-through (`security.py:238`) |

Role values carried by sessions/identities (`users.role`) default to `"merchant"`.

---

## 2. Frontend findings

### 2.1 Identity detail page is a pure projection surface

`frontend/src/pages/identity-detail.tsx` renders the selected identity's cards and session table read-only. The only action is **Refresh** (line 41). There is **no Create Session action, no dialog, no API wrapper** for it:

- `frontend/src/lib/api.ts` exposes no call to `POST /v1/sessions`. The generated type `create_session_v1_sessions_post` exists in `frontend/src/types/api.ts:4798`, but **no component in the entire console invokes it** (grep for `create_session|createSession` returns only the unrelated intent-profile mutation, `intent-profiler.tsx:32`).
- The sessions list page states the design intent outright — `frontend/src/pages/sessions.tsx:74`:

  > "Sessions appear here as they are created through the backend."

- The console's operating principle is consistent across modules: *"All values are projected from backend state; the console does not recompute scores"* (`sessions.tsx:155`). Mutations the console *does* offer (payout execution, incident actions, intent profiles, investigations, simulations) all have server-side role authorization and are documented as one-shot, non-retrying server actions (payout dialog: `retry: false`, "Execute once", "No automatic retry" — `payout-dialog.tsx:137,365,380`).

### 2.2 Role-gating pattern used elsewhere

Where the console surfaces a role-restricted action, it does so **server-driven and even shows denied actions transparently** (e.g. incident actions fetched from `GET .../actions` with `required_roles` and reasons, `incident-actions.tsx:69-94`; e2e test `console.spec.ts:154-163` asserts Merchant Operator sees "Unavailable actions (3)" rather than hidden buttons). Session creation appears **nowhere in that matrix** — it was not merely hidden; it was never part of the operator action set.

---

## 3. Backend findings

### 3.1 The one create endpoint is owner-bound by design

`POST /v1/sessions` (`apps/api/app/api/routes/sessions.py:102-125`) exists and is **not role-gated** (any authenticated role may call it), but it **ignores any "target identity" concept entirely** — the session is created for the *caller*:

```python
def create_session(request, principal=Depends(get_current_principal), db=...):
    new_session = SessionRecord(
        user_id=principal.user_id,          # ← caller's own user, hardcoded
        merchant_id=principal.merchant_id,  # ← tenant scope from server-validated token
        ...
    )
```

Key properties already satisfied by this endpoint:

- **Session IDs are backend-generated** — `session_id` defaults to `uuid.uuid4()` in the model (`app/models/session.py:21-23`), and `SessionCreateRequest` rejects client-set identifiers with `extra="forbid"` and only accepts `device_fingerprint`/`ip_address` (`app/schemas/sessions.py:44-51`). A comment in the schema states the principle: *"Client cannot set trust_level or risk_score! They are initialized server-side."*
- **Tenant scope is resolved server-side** from the authenticated principal; a cross-tenant GET is already proven 403 by `apps/api/tests/test_sessions.py:28-32`.

**There is no `POST /v1/identities/{user_id}/sessions` endpoint.** The identity routes (`app/api/routes/twin.py`) are GET-only (list, detail, twin profile).

### 3.2 The restriction is a documented security boundary

`docs/security-boundaries.md:21` states it verbatim:

> **Ownership Verification**: Requests claiming to act on a session are checked against `session.merchant_id == principal.merchant_id` and `session.user_id == principal.user_id`. Mismatched ownership results in immediate HTTP 403 Forbidden.

This is not aspirational — it is actively enforced downstream:

- **Event ingestion binding** — `EventService.ingest_event` rejects any event for a session whose `user_id != principal.user_id` (`app/services/event_service.py:43-47`), which drives the risk engine and behavioral twin updates.
- **Step-up challenge binding** — `POST /sessions/{id}/step-up` requires `session.user_id == principal.user_id` (`routes/sessions.py:155-158`).
- **Session ownership enforcement** is asserted as an invariant by the security gate: *"Payouts and event ingestion enforce row-level session ownership matching the authenticated principal's user and merchant UUID"* (`docs/security-boundaries.md:114`, tests in `test_security_audit.py`, `test_no_bypass.py`).

**Consequence:** even if an operator could author a session for a customer identity, it would be a **dead record** — the customer's principal would (correctly) be refused permission to ingest events, request step-up, or execute payouts through it, because the customer never authenticated through it. Meanwhile its very existence would pollute the session statistics, risk baselines, and evidence-adjacent state of that identity. The system's behavioral twin model treats a session as *evidence of a real login with observed telemetry*; an operator-fabricated session would falsify that evidence surface, contradicting the product's anti-fabrication posture (tamper-evident vault, "not an immutability proof" caveats, server-side-derived flags).

### 3.3 The durable-event and SSE plumbing exists and is role-agnostic

For completeness — the realtime circuit that the brief's "required behavior" assumes is fully present:

- **Durable creation event:** SQLAlchemy flush hooks (`app/services/domain_events.py:16-29,176-177`) emit a tenant-scoped `session.changed` outbox row with `operation: "created"` **automatically for any session insert**, with a 30-day retention (`prune_expired_domain_events`). No extra work is needed to record creation.
- **Authenticated SSE:** `GET /v1/events/stream` streams the outbox merchant-scoped by `principal.merchant_id` (`routes/events.py:19-47`); the frontend hook `useContainmentStream` (`frontend/src/lib/sse.ts:141+`) is connected globally in `AppShell` (`app-shell.tsx:205`) and on `session.changed` invalidates exactly the keys needed — `["sessions"]`, `["identities"]`, `["identity"]` (`sse.ts:57-65`). **A newly created session would appear on the identity profile immediately** via this path. Missing a validation is not the issue.
- **No idempotency guard on session creation:** `POST /v1/sessions` has none (unlike payouts, which use database-backed idempotency). Duplicate submission prevention for the existing endpoint relies on client discipline only. This is a gap **within** the already-enabled scope and would be mandatory work if the restriction were ever lifted.

### 3.4 No pending/abandoned implementation

Alembic migrations, repositories, schemas, OpenAPI export, docs (`api-contracts.md` — which documents list/get/step-up but not an operator create-for-identity endpoint), e2e tests, and the capability matrix (`system_service.py:59-117`, which enumerates capabilities per module and lists none for session creation) all point the same direction: this is not a half-built feature.

---

## 4. Intended permissions

| Action | Merchant Operator (`merchant`) | Risk Analyst (`analyst`) | Platform Admin (`admin`) |
|---|---|---|---|
| View customer identity profiles & their sessions (own tenant) | ✅ (`GET /v1/identities`, `GET /v1/identities/{id}`, `GET /v1/sessions?user_id=`) | ✅ | ✅ |
| Create a session **for themselves** | ✅ `POST /v1/sessions` (owner-bound; client SDK self-registration) | ✅ | ✅ |
| Create a session **for a selected customer identity** | ❌ **Not in the permission model** | ❌ | ❌ |
| Ingest events / step-up on a session | ✅ only if `session.user_id == principal.user_id` (server-enforced 403 otherwise) | ✅ (same owner-binding) | ✅ (same owner-binding) |
| Approve/resolve incidents | ❌ (`IncidentApprovalRequiredException`, `incident_service.py:90-93`) | ✅ | ✅ |

The asymmetry the brief describes ("can view but cannot create") is therefore by construction: **viewing is a scoped read projection; creating is an owner-authenticated action reserved for the session's own principal.**

---

## 5. Which workflow creates sessions instead

1. **Customer/SDK self-registration** — `POST /v1/sessions`, called by the *authenticated customer principal* (per the architecture, the "Merchant Client" posts telemetry and registers its session — `README.md` §2). This is the production path; the session starts NORMAL/0.0 and accrues risk only through ingest-bound events.
2. **Seed script** — `scripts/seed_demo.py` provisions demo sessions across trust levels for non-production tenants.
3. **Synthetic attack drill** — `POST /v1/simulate/attack` (`routes/stubs.py:120`) creates a simulated session for the calling principal in non-production environments only.
4. Realtime observation — the console then sees those sessions through `GET /v1/sessions`, `/v1/identities/{id}`, and the `session.changed` SSE stream.

---

## 6. Verification performed (static) and per-role expectations

| Check | Result |
|---|---|
| Frontend exposes a create-session control for identity profiles | **No** — read-only detail page; no API wrapper exists |
| A create endpoint reachable by an operator exists | **Yes, owner-bound only** (`POST /v1/sessions` → `principal.user_id`) |
| Backend route for create-for-arbitrary-identity | **Does not exist** |
| Session ID generation | Backend-only (`uuid.uuid4` model default; request schema `extra="forbid"`) |
| Durable creation event | Yes — `session.changed` `created` outbox row emitted transactionally at flush |
| SSE connectivity & immediate display plumbing | Yes — `/v1/events/stream` ↔ `useContainmentStream` ↔ `["identity"]` invalidation (not independently exercised live per constraints; see `docs/REMAINING_BLOCKERS.md` note on live cross-page verification) |
| Cross-tenant access prevention | Enforced on every session read/act path (`merchant_id` from token; 403 tests exist: `test_sessions.py:28-32`, `test_security_audit.py`); creation would inherit tenant scope from the token, and no route exists that could span tenants |
| Duplicate-submission prevention | **Gap in the existing endpoint** (no idempotency key, unlike payouts); console mutations elsewhere are single-shot/no-retry by convention |

**Not executed (by constraint):** live API calls with `dev-merchant-token` / `dev-analyst-token` / `X-Dev-Role: admin`, tenant-isolation end-to-end runs, and Playwright e2e. The existing suite already covers the closest invariants (`test_sessions.py`, `test_authorization.py`, `test_security_audit.py`, e2e `console.spec.ts`), and nothing in the diff to the permissions above requires new behavior to demonstrate the decision.

---

## 7. If this restriction is ever revisited

For the record, enabling operator session creation on an identity profile would require the following — none of which is authorized by this audit (no code was changed):

1. **Backend:** a new route, e.g. `POST /v1/identities/{user_id}/sessions`, that (a) resolves the target user and rejects `IDENTITY_NOT_FOUND` / `IDENTITY_OWNERSHIP_MISMATCH` unless `user.merchant_id == principal.merchant_id`, (b) requires an explicit role policy — since *no* role currently holds create-for-others, one must be granted deliberately (naturally `merchant`/`admin` for tenant-provisioning use cases), (c) generates `session_id` server-side as the model already does, and (d) accepts an **Idempotency-Key** to prevent duplicate submissions (extend the payout-style DB-backed idempotency).
2. **Boundary waiver:** reconcile with `docs/security-boundaries.md:21` owner-verification, because the created record must not silently become the basis of a behavioral twin/risk baseline without real telemetry; at minimum it should start as a provisioned-session lifecycle (e.g. `pending`/`expired`) distinct from telemetry-backed sessions.
3. **Frontend:** a Create Session dialog on `identity-detail.tsx` following the established one-shot mutation pattern (`retry: false`, disable-while-pending, "Execute once" confirm dialog, authoritative outcome display). The SSE-triggered refresh of `["identity"]`/`["sessions"]` requires no change.
4. **Tests:** role matrix (403 for ungranted roles), cross-tenant (403), duplicate key replays (deduplicated, no second row), outbox `session.changed` created-event, and e2e for immediate display.

---

## 8. Summary

The Merchant Operator's inability to create a session on a customer identity profile is **the interface honoring the backend's documented ownership security boundary**, not an incomplete frontend. Sessions are owner-authored artifacts in IdentityTwin: the customer principal registers its own session (`POST /v1/sessions`), the risk/telemetry pipeline deepens it, and the console — for all three roles — only *observes* those sessions, tenant-scoped, through the durable `session.changed` SSE stream.

**DECISION: INTENTIONALLY RESTRICTED.**
