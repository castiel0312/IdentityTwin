# Person 3 — PayPal Sandbox Integration & Agentic Commerce: Handoff

**Scope of this document.** It is the final audit and handoff record for the
Person 3 workstream: the PayPal Sandbox provider adapter, provider selection,
payout payload mapping, provider level idempotency, webhook verification and
the internal agentic-commerce adapter.

**Audit performed:** 2026-10-23 (final completion audit); original audit
2026-10-22, on branch `main` at commit `f531c20`, with the Person 3 work
present in the working tree (uncommitted — see
[§9 Repository state](#9-repository-state)).

**Safety constraints observed during the audit.** No payout was executed, no
request was sent to PayPal (sandbox or production), and no credential, token or
secret was read out of `.env`, printed or written to this document. Every
statement about PayPal HTTP behaviour below was produced either from source
code inspection or from an `httpx.MockTransport` stand-in, never from a live
PayPal endpoint.

---

## 1. Evidence vocabulary (read this first)

| Label | Meaning |
| --- | --- |
| **VERIFIED** | Behaviour observed directly in this audit — either by executing the code against a mocked transport, by running the test suite, or by comparing generated artefacts against committed artefacts. |
| **MOCKED** | Behaviour covered by automated tests that use `httpx.MockTransport` (PayPal is simulated). The contract is verified; the real PayPal endpoint is **not** exercised. |
| **UNTESTED (EXTERNAL)** | Behaviour that depends on a live PayPal Sandbox account/endpoint and has **no** automated coverage at all. |

No item in this document is a claim about live PayPal behaviour. The only
evidence of live PayPal connectivity anywhere in the repository is the two
manual probe scripts listed in [§6.4](#64-manual-live-probes-not-part-of-ci),
which were not executed during this audit.

---

## 2. Implemented features

### 2.1 Provider adapter selection

**VERIFIED** (runtime observation).

| `PAYMENT_PROVIDER` | Adapter returned by `get_payment_provider()` | Observed |
| --- | --- | --- |
| `mock` (default) | `MockPaymentProviderAdapter` | confirmed |
| `paypal_sandbox` | `PayPalSandboxAdapter` (requires nonblank Client ID + Secret at startup) | confirmed |
| any other value (e.g. typo) | **startup `ValidationError`**; if the setting is mutated at runtime, `get_payment_provider()` raises `PAYMENT_PROVIDER_UNKNOWN` (500) | confirmed — **fails closed**, an unknown value never silently selects the mock or a real adapter |

* Selection happens in `apps/api/app/gateway/provider.py`
  (`get_payment_provider()`), resolved per request through
  `create_gateway_service()` (`app/gateway/service.py:411`).
* `PAYMENT_PROVIDER` is normalized (case/whitespace) and validated against an
  exhaustive allowlist at settings construction
  (`apps/api/app/core/config.py`), so a typo aborts startup.
* When `paypal_sandbox` is selected, a missing/blank `PAYPAL_CLIENT_ID` or
  `PAYPAL_CLIENT_SECRET` also aborts startup instead of failing at the first
  payout. `mock` never requires PayPal credentials.
* The decoy adapter (`DecoyHoneyAdapter`) is a *separate* accessor
  (`get_decoy_provider()`); it is never reachable through provider selection.
* The three adapters share one protocol, `IPaymentProviderAdapter`
  (`app/gateway/provider.py:71`), so the gateway never sees an adapter type it
  cannot verify.

### 2.2 PayPal Sandbox OAuth2 (client credentials)

**VERIFIED** (request bytes observed through a mock transport) and **MOCKED**
(54 collected tests in `apps/api/tests/test_paypal_provider.py`).

Observed outbound token request:

```
POST https://<sandbox-host>/v1/oauth2/token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded
body: grant_type=client_credentials
Accept: application/json, Accept-Language: en_US
```

* Token cache with a 60-second expiry skew (`app/gateway/provider.py:267`).
  VERIFIED: the cached token is reused; a token inside the skew window is
  refreshed; an expired token is re-fetched.
* Missing credentials raise `AuthenticationRequiredException`
  (`PAYPAL_CREDENTIALS_MISSING`, HTTP 401) **before** any HTTP traffic.
  VERIFIED: no request leaves the process.
* An explicitly empty credential is treated as "not configured" rather than
  falling back to ambient environment credentials
  (`app/gateway/provider.py:229`).
* Error mapping: 401/403 → `PAYPAL_AUTHENTICATION_FAILED` (401), 429 →
  `PAYPAL_RATE_LIMIT` (429), non-200 → `PAYPAL_OAUTH_ERROR` (502), timeout →
  `PAYPAL_OAUTH_TIMEOUT` (504), network error → `PAYPAL_NETWORK_ERROR` (502),
  missing/invalid `access_token` or non-JSON body → `PAYPAL_OAUTH_INVALID_PAYLOAD` (502).
* A 401 on the *payout* call invalidates the cached token
  (`app/gateway/provider.py:413`).

### 2.3 Payout payload mapping

**VERIFIED** (outbound payload observed) and **MOCKED** (automated contract tests).

Observed body for `POST /v1/payments/payouts`:

```json
{
  "sender_batch_header": {
    "sender_batch_id": "IDTWIN-F8C1A67DF57F",
    "email_subject": "IdentityTwin Protected Disbursement",
    "email_message": "Invoice #4021"
  },
  "items": [
    {
      "recipient_type": "EMAIL",
      "amount": { "value": "1250.50", "currency": "USD" },
      "note": "Invoice #4021",
      "sender_item_id": "ITEM-C8CA60EAB568",
      "receiver": "payee@example.com"
    }
  ]
}
```

* Amount is always rendered with two decimals (`f"{amount:.2f}"`), currency is
  passed through verbatim, the recipient is sent as `recipient_type: EMAIL`.
* `email_message` / `note` fall back to fixed wording when
  `reference_note` is absent.
* `sender_batch_id` and `sender_item_id` are freshly generated per call
  (`IDTWIN-<hex>` / `ITEM-<hex>`); they are **not** derived from the
  idempotency key — see [§2.4](#24-idempotency) for how provider level
  idempotency is actually achieved.
* Response mapping: `batch_header.payout_batch_id` becomes
  `provider_transaction_id` (falling back to the generated batch id),
  `batch_status`, `time_created`, `time_completed`, recipient, amount, currency
  and merchant id are kept in the audit `details`.
* The persisted provider identity is `paypal_sandbox` and the environment
  marker is `paypal_sandbox`; the mock adapter reports `mock_adapter` /
  `synthetic_mock`; the decoy reports `honey_synthetic_decoy` /
  `honey_sandbox_simulation`. The adapter that actually ran is always the one
  recorded (`resolve_provider_name`, `app/gateway/provider.py:79`).

### 2.4 Idempotency

Three independent layers, all **VERIFIED** by automated tests:

1. **Gateway layer** (`app/gateway/service.py:88`) — merchant-scoped
   `(merchant_id, idempotency_key)` unique record.
   * Same key + same payload hash → cached response, `is_duplicate: true`, the
     provider is **not** invoked a second time.
   * Same key + different payload hash → `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` (403).
   * Status `processing` → `IDEMPOTENCY_IN_PROGRESS` (409).
   * Status `provider_executed` / `needs_reconciliation` →
     `PAYOUT_ALREADY_EXECUTED_RECONCILIATION_REQUIRED` (403), never a re-execution.
   * Status `failed` → the key stays retryable and the existing row is reused.
2. **Provider layer** (`build_paypal_request_id`, `app/gateway/provider.py:43`) —
   the gateway key is sent as the `PayPal-Request-Id` header.
   * VERIFIED: a 17-character key is forwarded verbatim (`idem-key-00000001`).
   * VERIFIED: an 80-character key is mapped to a deterministic 38-character
     SHA-256 prefix (`66edbde83cc90c1a080ec3e598dc99cec90d57`) because PayPal
     rejects `PayPal-Request-Id` values longer than 38 characters. The mapping
     is stable across calls, so provider level replay protection is preserved.
3. **Agentic layer** (`_assert_idempotency_context`, `app/gateway/agentic.py:323`)
   — an agent may not reuse a key that is bound to a human payout or to another
     agent: `AGENT_IDEMPOTENCY_KEY_CONFLICT` (409).

**Ambiguity handling (VERIFIED).** If the provider was invoked and the final
outcome is unknown (timeout, or a post-provider DB failure), the idempotency
record is written as `provider_executed` with the provider reference, and the
key is permanently blocked from re-execution
(`app/gateway/service.py:358`). A *definitive* provider failure (rejection,
rate limit, explicit `success: false`) leaves the key retryable.

### 2.5 Risk-level isolation

**VERIFIED** (matrix test + adapter call counters) and documented in
`docs/security-boundaries.md`.

| Trust level | Gateway action | Provider adapter invoked? | Recorded status |
| --- | --- | --- | --- |
| `NORMAL` | `ALLOW` | yes (configured adapter) | `completed` |
| `RESTRICTED` | `REQUIRE_STEP_UP` | **no** (unless a server-verified step-up challenge is present) | `rejected` |
| `DECOY` | `DECOY_FORWARD` | **no** — only `DecoyHoneyAdapter` | `decoy_completed` |
| `ISOLATED` | `BLOCK` | **no** | `blocked` (+ session isolation + incident) |

* `RESTRICTED` above `RESTRICTED_PAYOUT_LIMIT` is rejected even with step-up
  (`app/gateway/policy.py:69`).
* A step-up token is only honoured when it is a real, unconsumed, unexpired
  challenge bound to the same session and merchant; a forged or consumed token
  is rejected.
* Ownership and session-state checks run before any adapter call: a foreign,
  inactive, expired or unknown session never reaches a provider.
* Structural invariant (AST scan, `apps/api/tests/test_no_bypass.py:23`): no
  module outside `app/gateway` may import the provider adapters or their
  getters. VERIFIED: the scan passes with the agentic route and service in place.

### 2.6 Webhook verification (`POST /v1/webhooks/paypal`)

**VERIFIED** (executed against a mocked PayPal) and **MOCKED** (56 automated
tests in `apps/api/tests/test_webhook_verification.py`, plus 3 in
`tests/test_hardening_readiness.py`).

Observed accept/reject matrix:

| Scenario | Result |
| --- | --- |
| PayPal answers `verification_status: "SUCCESS"` (HTTP 200) | **accepted** |
| PayPal answers `verification_status: "FAILURE"` | rejected (400) |
| PayPal answers HTTP 500 | rejected (400) |
| A transmission header is missing | rejected, PayPal is **not** contacted |
| Body is not a JSON object | rejected, PayPal is **not** contacted |
| Adapter unconfigured (no webhook id / no credentials) | rejected, PayPal is **not** contacted |
| Mock adapter asked to verify | always rejected |
| Timeout / network failure during verification | rejected |

* Verification is delegated to PayPal's own
  `POST /v1/notifications/verify-webhook-signature` endpoint using the
  configured `PAYPAL_WEBHOOK_ID`; the mock payout adapter is deliberately
  **not** used as a verifier (`app/gateway/webhooks.py:14`).
* There is **no development bypass**: a "plausible looking" signature is never
  accepted in any environment (this was an explicit hardening change — the
  previous implementation accepted any signature that did not contain the word
  "invalid").
* After a successful verification the event is deduplicated
  (`paypal-webhook-<event_id>`, 7-day TTL) and reconciled against
  `PayoutRequestRecord.provider_reference`:
  `PAYMENT.PAYOUTSBATCH.SUCCESS` / `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` →
  `reconciled_completed`; the `DENIED`/`BLOCKED` family → `provider_denied`.
* The deduplication row and the reconciled payout status are committed in one
  transaction, so a crash cannot mark an event processed while the payout
  still has the old status.
* Platform-wide dedup rows have a foreign key to `merchants`. The receiver
  lazily persists one inactive system merchant (`00000000-...-000000000000`,
  slug `__identitytwin_webhooks__`) before writing the row, and tolerates a
  concurrent insert. This fixes a PostgreSQL-only failure that SQLite tests
  (foreign keys disabled) had hidden.
* A verified event without a body `id` is keyed by the verified
  `paypal-transmission-id`; a SHA-256 body digest remains a defensive final
  fallback instead of collapsing into `UNKNOWN_EVENT`.
* A forged webhook never reconciles a payout (VERIFIED by test).

### 2.7 Agentic-commerce integration

**VERIFIED** (33 automated tests) — full contract in `docs/agentic-commerce.md`,
API contract in `docs/api-contracts.md` §9.

* `POST /v1/agentic/payouts` (`app/api/routes/agentic.py`) — internal contract,
  no third-party agentic payment specification is implemented.
* The adapter (`app/gateway/agentic.py`) resolves the agent and its delegation
  from a **server-side registry** (`agent_registrations`,
  `agent_authorization_grants`) and normalizes the request into the canonical
  `PayoutRequest`; the Trust Gateway then performs risk evaluation, routing and
  provider execution exactly as for human traffic.
* Fail-closed authorization ladder (all HTTP 403 unless noted):
  `AGENT_NOT_REGISTERED`, `AGENT_MERCHANT_MISMATCH`, `AGENT_NOT_ACTIVE`,
  `AGENT_AUTHORIZATION_MISSING`, `AGENT_AUTHORIZATION_AGENT_MISMATCH`,
  `AGENT_AUTHORIZATION_MERCHANT_MISMATCH`, `AGENT_AUTHORIZATION_PRINCIPAL_MISMATCH`,
  `AGENT_AUTHORIZATION_REVOKED`, `AGENT_AUTHORIZATION_CONSUMED`,
  `AGENT_AUTHORIZATION_EXPIRED`, `AGENT_AUTHORIZATION_SESSION_MISMATCH`,
  `AGENT_SCOPE_NOT_GRANTED`, `AGENT_AMOUNT_LIMIT_EXCEEDED`;
  `AGENT_IDEMPOTENCY_KEY_CONFLICT` (409); unknown request fields → 422.
* Server-owned identity: merchant id comes from the authenticated principal,
  agent identity/scopes/limits from the registry. `trust_level`, `risk_score`
  and `merchant_id` cannot be smuggled into the body (`extra="forbid"`).
* A grant is a **delegation, not a credential**: the merchant bearer token is
  still required, and the grant only authorizes the agent to act for the
  merchant user it was issued to.
* A grant with `consumed_at` set is rejected unless the request is the exact
  idempotent replay of the attempt that consumed it (the caller can retrieve
  its own cached result). The adapter does **not** auto-consume grants: an
  administrative process must set `consumed_at`; see §7.9.
* Provenance: a bounded `[agent:<uuid>]` marker is appended to the business
  reference, and every authorized attempt (success or failure) is written to
  `agentic_commerce_audit`.
* Routing parity: agent traffic is evaluated by the same risk engine, so
  `RESTRICTED` needs step-up, `DECOY` reaches only the honey workspace and
  `ISOLATED` is blocked and opens an incident.

### 2.8 Environment configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAYMENT_PROVIDER` | `mock` | `mock` or `paypal_sandbox` |
| `PAYPAL_CLIENT_ID` | `""` | Sandbox REST app client id |
| `PAYPAL_CLIENT_SECRET` | `""` | Sandbox REST app client secret |
| `PAYPAL_WEBHOOK_ID` | `""` | Webhook id used for signature verification |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` | PayPal REST base URL |
| `PAYPAL_REQUEST_TIMEOUT` | `10.0` | Per-request HTTP timeout (seconds) |

* Defined in `apps/api/app/core/config.py:186`; template in `.env.example:33`.
* `PAYPAL_REQUEST_TIMEOUT` is validated to be `> 0`.
* Credentials are never logged by the adapter (no token, secret, signature or
  payload appears in any log statement); the tests assert this
  (`test_webhook_handling_never_logs_credentials_or_sensitive_payloads`).

### 2.9 API contracts

**VERIFIED** (regenerated and compared).

* `packages/contracts/openapi.json` is **semantically identical** to the spec
  generated from the running application (20 paths, 3164 lines, deep-equality
  check passed) — no drift between code and the published contract.
* Payout contract: `POST /v1/payouts` → `PayoutResponse`.
* Agentic contract: `POST /v1/agentic/payouts` → `AgenticCommerceResponse`
  (the full payout response plus agent provenance).
* Webhook contract: `POST /v1/webhooks/paypal` → `processed` / `duplicate`,
  HTTP 400 `INVALID_WEBHOOK_SIGNATURE` on any verification failure.
* Error envelope and standard error codes are documented in
  `docs/api-contracts.md` §"Standard Error Response Format".

---

## 3. Test evidence

### 3.1 Full suite (VERIFIED, run during this audit)

```
$ .venv/bin/python -m pytest apps/api/tests
435 passed, 1 warning in 9.4s
```

The single warning is `StarletteDeprecationWarning` from
`fastapi.testclient` (third-party, unrelated to Person 3 code).

Per-file collection counts (Person 3 relevant files in bold):

| Test file | Tests | Area |
| --- | --- | --- |
| **`tests/test_paypal_provider.py`** | **54** | OAuth, payload contract, error mapping, request-id mapping, webhook verification (adapter level) |
| **`tests/test_paypal_config.py`** | **46** | Sandbox base-URL allowlist: approved value, canonicalization, production/lookalike hosts, insecure schemes, malformed URLs, missing configuration, adapter defense in depth, mocked-transport seam |
| **`tests/test_payment_provider_config.py`** | **44** | Provider allowlist: unknown/blank/non-string rejection, startup credential readiness for `paypal_sandbox`, mock mode without credentials, secret-free errors, runtime adapter selection |
| **`tests/test_webhook_verification.py`** | **56** | fail-closed verification, receiver behaviour, dedup, reconciliation, secret hygiene |
| **`tests/test_gateway_routing.py`** | **37** | risk-level isolation, live policy/provider consistency, provider selection, idempotency states, reconciliation guard |
| **`tests/test_provider_provenance.py`** | **16** | the recorded provider identity always matches the adapter that ran |
| **`tests/test_agentic_commerce.py`** | **33** | agentic authorization ladder, idempotency isolation, routing parity, audit trail |
| `tests/test_hardening_readiness.py` | 12 | step-up limits, webhook hardening, adapter happy/error paths |
| `tests/test_no_bypass.py` | 7 | AST provider-import invariant, provider invocation matrix, canary→block sequence |
| `tests/test_payouts.py`, `test_gateway.py`, `test_step_up.py`, `test_authorization.py`, `test_health.py`, `test_sessions.py`, `test_events.py`, `test_security_audit.py`, `test_incidents_and_stubs.py` | 46 | platform-level regression coverage |
| `tests/risk/*` (Person 2) | 84 | risk engine, twin API, behavioural scenarios, synthetic calibration |

### 3.2 Lint (VERIFIED)

```
$ .venv/bin/ruff check apps/api/app apps/api/tests scripts
All checks passed!
$ .venv/bin/ruff format --check apps/api/app apps/api/tests scripts
97 files already formatted
$ make lint      # same command via the Makefile
All checks passed!
```

### 3.3 Safety guards inside the test suite (VERIFIED)

* `tests/test_paypal_provider.py` patches `httpx.HTTPTransport.handle_request`
  with an autouse fixture that **fails the test** if any code path tries to
  open a real socket. Every PayPal interaction in that module goes through an
  `httpx.MockTransport` against the reserved `.test` host.
* The same module blanks the ambient `PAYPAL_*` settings, so a real sandbox
  credential in `.env` can never be used by the suite.
* The webhook module repeats the same guard (`tests/test_webhook_verification.py:127`).
* `tests/test_payment_provider_config.py` adds an autouse guard that makes any
  `httpx.HTTPTransport.handle_request` call fail, and it only constructs
  `Settings` / selects adapters, so provider-readiness tests perform no I/O.
* Caveat: the guard patches the **synchronous** `httpx.HTTPTransport`
  only. An asynchronous call path that bypasses `httpx.HTTPTransport` would
  not be caught by it. No such path exists in the current code (all provider
  calls use the synchronous client), but the guard is not a complete sandbox.

### 3.4 What is **not** covered by any automated test (UNTESTED — EXTERNAL)

| External behaviour | Status |
| --- | --- |
| A real OAuth call against `api-m.sandbox.paypal.com` | UNTESTED (EXTERNAL) — only the manual probes in §6.4 touch it |
| A real `/v1/payments/payouts` call and a real sandbox disbursement | UNTESTED (EXTERNAL) — **no** automated test may create a real transfer |
| PayPal's real `verify-webhook-signature` response shape/rate limits | UNTESTED (EXTERNAL) — the request/response contract is mocked |
| A real PayPal webhook delivery (dashboard "Simulate → Webhooks") | UNTESTED (EXTERNAL) — documented procedure in `docs/local-development.md` §7.3 |
| PayPal webhook id discovery via `GET /v1/notifications/webhooks` | UNTESTED (EXTERNAL) — documented in §7.2 |
| Sandbox recipient-address behaviour (invalid/unverified payees) | UNTESTED (EXTERNAL) |
| PayPal-specific rate limit windows / quota behaviour | UNTESTED (EXTERNAL) — the 429 mapping is mocked |

---

## 4. Local setup

### 4.1 Install

```bash
git clone <repo> && cd IdentityTwin
cp .env.example .env          # then fill in the values you need (see §5)
make install                  # creates .venv and runs: pip install -e "apps/api[dev]"
```

Without `make`:

```bash
cd apps/api && python -m pip install -e ".[dev]"
```

The API is distributed as the single import package `app`; the Alembic
migration directory, the test suite and the local configuration files are
deliberately **not** installed (in particular `alembic` must never shadow the
real Alembic library). See `docs/local-development.md` §2.1.

### 4.2 Database and seed data

```bash
make migrate     # alembic upgrade head
make seed        # demo merchant, sessions, agent registration + delegation grant
```

### 4.3 Run

```bash
make dev         # uvicorn app.main:app --reload on :8000
```

### 4.4 Verify

```bash
make test        # 435 passed, fully offline
make lint        # ruff check
```

---

## 5. Configuration requirements

### 5.1 Minimum for the offline demo (no PayPal account needed)

```bash
PAYMENT_PROVIDER="mock"
```

All payouts are executed against the synthetic mock adapter: no network, no
credentials, synthetic transaction ids (`SYNTH-MOCK-TXN-…`), and the mock
adapter refuses to verify webhooks.

### 5.2 Minimum for PayPal Sandbox execution

```bash
PAYMENT_PROVIDER="paypal_sandbox"
PAYPAL_CLIENT_ID="<sandbox client id>"
PAYPAL_CLIENT_SECRET="<sandbox client secret>"
PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com"
PAYPAL_REQUEST_TIMEOUT=10.0
```

Credentials come from a **Sandbox** REST app in the PayPal Developer Dashboard.
Never place production credentials in `.env` — see [§7.1](#71-p1--resolved-paypal_base_url-sandbox-host-enforcement).
If either credential is missing or blank, the API **refuses to start** (see
[§7.3](#73-p2--resolved-startup-validation-of-the-paypal-configuration)).

### 5.3 Required for inbound webhooks

```bash
PAYPAL_WEBHOOK_ID="<webhook id of the webhook that delivers to this deployment>"
```

While `PAYPAL_WEBHOOK_ID` is empty **every** inbound delivery is rejected with
HTTP 400 and PayPal is never contacted (fail closed). The id is shown in the
dashboard (your app → Webhooks) or via
`GET $PAYPAL_BASE_URL/v1/notifications/webhooks`.

### 5.4 Things that are *not* configurable (by design)

* Webhook signature verification is **never** bypassed by configuration —
  there is no "skip verification" flag in any environment.
* The mock payout adapter can never accept a webhook.
* `POST /v1/payouts` and `POST /v1/agentic/payouts` cannot bypass the Trust
  Gateway, and no route outside `app/gateway` may import a provider adapter
  (AST invariant, `tests/test_no_bypass.py`).

---

## 6. Demo instructions

### 6.1 Demo 1 — human payout through the gateway (mock provider)

```bash
curl -X POST http://localhost:8000/v1/payouts \
  -H "Authorization: Bearer dev-merchant-token" \
  -H "Content-Type: application/json" \
  -d '{
        "session_id": "22222222-2222-2222-2222-222222222222",
        "recipient_email": "contractor@supplier.com",
        "amount": 1250.00,
        "currency": "USD",
        "reference_note": "Invoice #8921",
        "idempotency_key": "payout-idem-9812401"
      }'
```

Expected: HTTP 200, `status: "completed"`, `routing_destination: "PROVIDER_MOCK"`,
`provider_reference: "SYNTH-MOCK-TXN-…"`.

*Repeat the identical request* → the cached response with `is_duplicate: true`
and no second provider invocation.

### 6.2 Demo 2 — agentic payout (mock provider)

```bash
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
```

Expected: HTTP 200 with the payout response **plus** `agent_id`,
`agent_display_name`, `agent_type`, `authorization_grant_id`,
`delegated_by_user_id` and `agent_intent`.

Seeded demo identity (`scripts/seed_demo.py`):

| Item | Value |
| --- | --- |
| Demo agent id | `77777777-7777-7777-7777-777777777777` ("Acme Shopping Assistant", `shopping_assistant`) |
| Demo grant id | `88888888-8888-8888-8888-888888888888` (scope `payout:execute`, delegated by user `11111111-1111-1111-1111-111111111111`) |
| Agent amount cap | `500.00` |
| Grant amount cap | `250.00` (effective cap = `min(agent, grant)` = 250) |
| Demo session | `22222222-2222-2222-2222-222222222222` (NORMAL trust state) |

Negative demo — an unregistered agent:

```bash
curl -i -X POST http://localhost:8000/v1/agentic/payouts \
  -H "Authorization: Bearer dev-merchant-token" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"11111111-2222-3333-4444-555555555555", ...}'
```

Expected: HTTP 403 `AGENT_NOT_REGISTERED`.

### 6.3 Demo 3 — webhook fail-closed behaviour (mock provider)

```bash
curl -i -X POST http://localhost:8000/v1/webhooks/paypal \
  -H "Content-Type: application/json" \
  -d '{"id":"WH-1","event_type":"PAYMENT.PAYOUTSBATCH.SUCCESS","resource":{}}'
```

Expected: HTTP 400 `INVALID_WEBHOOK_SIGNATURE` — with the mock provider no
delivery can ever be accepted.

With `PAYPAL_WEBHOOK_ID` and sandbox credentials configured, use the PayPal
dashboard (**Events → Simulate → Webhooks**) to send a real event; the API log
shows `status=200` for a verified delivery and `status=400` for a rejected one.

### 6.4 Manual live probes (NOT part of CI)

Two untracked helper scripts exist in the working tree for manual exploration:

* `paypal_live_probe_api.py`
* `paypal_live_probe_connection.py`

They perform a **real** OAuth call against the configured `PAYPAL_BASE_URL`.
They are deliberately not named `*_test.py`, so pytest can never collect them.
**They were not executed during this audit.** Treat them as developer scratch
tools, decide whether they belong in the repository, and never run them
against production credentials.

---

## 7. Known limitations and findings

### 7.1 (P1 — resolved) `PAYPAL_BASE_URL` sandbox-host enforcement

**Status: FIXED** (was a verified gap in the original audit).

* `PAYPAL_BASE_URL` is now validated by an explicit allowlist at settings
  initialization (`validate_paypal_base_url` in
  `apps/api/app/core/config.py`), i.e. at startup and before any provider
  request can occur. The only accepted value is
  `https://api-m.sandbox.paypal.com`; production hosts, lookalike hosts, the
  retired `api.sandbox.paypal.com` host, non-`https` schemes, embedded
  credentials, non-default ports and URLs with a path/query/fragment are all
  rejected with a startup `ValidationError`.
* The adapter re-validates any base URL it is constructed with **unless** a
  mocked transport is injected (the test seam), so a programmatic override
  cannot reach the network with a non-Sandbox host.
* Tests: `apps/api/tests/test_paypal_config.py` (approved value,
  canonicalization, production host, lookalikes, malformed/insecure URLs,
  missing configuration, adapter defense in depth, mocked-transport seam).
* `README.md` §7 has been updated so its sandbox-only claim matches the actual
  enforcement.
* Residual note: this is a configuration boundary, not evidence that live
  PayPal Sandbox behaviour has been verified (see §3.4). Provider selection and
  credential readiness are covered separately in §7.3.

### 7.2 (P2 — resolved) `routing_destination` was frozen at import time

**Status: FIXED.**

The policy used to be instantiated once at import with
`provider_mode=settings.PAYMENT_PROVIDER`, while the adapter was resolved per
request. After changing `settings.PAYMENT_PROVIDER` at runtime, the adapter
switched to `PayPalSandboxAdapter` but the policy still reported `mock`.

* **Fix**: `get_gateway_policy()` now resolves the provider mode per call from
  the same validated source used by the adapter factory
  (`get_configured_payment_provider_name()`).
  `create_gateway_service()` resolves the policy first and passes that policy's
  `provider_mode` to `get_payment_provider(...)`, so the routing destination and
  the executing adapter come from one explicit decision.
* **Invariants preserved**: `RESTRICTED`, `DECOY` and `ISOLATED` never invoke
  the PayPal adapter; `NORMAL` (and step-up-cleared `RESTRICTED`) use exactly
  the provider named by the routing destination.
* **Regression coverage**: `apps/api/tests/test_gateway_routing.py` now asserts
  that policy destinations follow live configuration changes, that policy and
  adapter derive from the same runtime mode, and that non-`NORMAL` states never
  reach a configured PayPal adapter. PayPal is still exercised only through
  `httpx.MockTransport` / recording doubles.

### 7.3 (P2 — resolved) Startup validation of the PayPal configuration

**Status: FIXED** (was a verified gap in the original audit).

* `PAYMENT_PROVIDER` is validated at settings initialization against an
  exhaustive allowlist (`mock`, `paypal_sandbox`). Unknown values, blanks and
  non-string values abort startup with a `ValidationError`; they are never
  mapped to the mock adapter. `get_payment_provider()` repeats the check at
  runtime (defense in depth) and raises `PAYMENT_PROVIDER_UNKNOWN` instead of
  selecting a different adapter.
* With `PAYMENT_PROVIDER="paypal_sandbox"`, a missing or whitespace-only
  `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` aborts startup. The error names
  the missing variables only — credential values never appear in the
  `ValidationError` (also enforced by `hide_input_in_errors=True`).
* `PAYMENT_PROVIDER="mock"` keeps the offline workflow: no PayPal credentials
  required.
* Tests: `apps/api/tests/test_payment_provider_config.py` (44 tests) covers
  unknown/blank provider values, both missing credentials, blank credentials,
  valid Sandbox configuration, mock without credentials, env-var driven
  startup, secret-free errors, the base-URL allowlist interaction, and runtime
  selection. The tests make no PayPal requests.
* Not changed: `GET /ready` still does not report provider configuration;
  startup now fails earlier, but a readiness signal would help operators
  distinguish a booting service from a misconfigured one.

### 7.4 (P2) Provider timeout is not retried and has no reconciliation worker

* A `PAYPAL_PAYOUT_TIMEOUT` leaves the idempotency record in
  `provider_executed` and blocks retries — deliberately, to avoid double
  execution — but **no background reconciliation job exists** to resolve those
  records. Someone must reconcile them (via the PayPal batch id) manually.
* There is no automatic retry with backoff for 429s; the client is expected to
  retry the HTTP call (the key stays retryable because a rate-limit error is a
  definitive "provider did not execute").

### 7.5 (P2) Webhook reconciliation is minimal (some findings fixed)

**Fixed during the final audit:** platform deduplication previously referenced
an unseeded all-zero merchant UUID, so a real PostgreSQL deployment rejected
every verified webhook with a foreign-key error (the SQLite suite hid this
because foreign keys are disabled). The receiver now ensures a persisted
system merchant exists, commits the dedup record and payout status atomically,
and keys deliveries without an event id by a body digest.

Remaining:

* Only `provider_reference == payout_batch_id` is matched; item-level events
  (`sender_item_id`) are not mapped back to individual payouts — the API only
  creates one-item batches, so this is currently acceptable, but it will need
  revisiting if multi-item batches are introduced.
* Reconciliation only flips the payout status; it does not write an incident
  or an evidence record for a denied batch.
* A webhook cannot resolve an idempotency record that was parked as
  `provider_executed` before a payout row existed (see §7.4).

### 7.6 (P3) No live-payroll regression environment

Every automated test is offline by design. There is no scheduled job against
PayPal Sandbox, so an upstream contract change (field rename, new required
field, different error body) would only be discovered during a manual demo.
Recommended: a nightly (credentialed, non-CI) smoke job that performs one
sandbox payout of a nominal amount to a sandbox test address and asserts the
`batch_header` shape.

### 7.7 (P3) Documentation hygiene

**Fixed during the final audit:**

* The 17 absolute `file:///Users/khoria/...` links in
  `docs/security-boundaries.md` are now repository-relative.
* Stale "336 tests" references and the duplicate `PAYPAL_CLIENT_ID` line in
  `README.md`, and a duplicated sentence in `docs/local-development.md`, were
  corrected.
* This handoff is now linked from `README.md` and
  `docs/architecture.md`.

### 7.8 (P3) Uncommitted working tree

The Person 3 files are modified/untracked in the working tree (see §9).
Nothing has been committed or pushed by this audit.

### 7.9 (P2) Single-use grants require an explicit administrative action

`agent_authorization_grants.consumed_at` is a single-use marker, but neither
the agentic service nor a management endpoint sets it automatically. A grant is
therefore reusable until it expires unless an operator marks it consumed. This
is deliberate (a grant is a delegation, not a bearer capability), but it means
"single-use" is opt-in rather than guaranteed by the API. Adding an explicit
`single_use` flag plus automatic consumption is a future change that must be
coordinated with the authorization model.

---

## 8. Handoff points

### 8.1 For Person 1 — platform / infrastructure / contracts

| # | Item | Why it matters | Reference |
| --- | --- | --- | --- |
| P1-1 | ~~**Add a sandbox guard for `PAYPAL_BASE_URL`**~~ — **done**: allowlist validated at settings init and in the adapter; see `test_paypal_config.py`. ~~Remaining decision: cross-validate `PAYMENT_PROVIDER=paypal_sandbox` against credential presence~~ — **also done** (`test_payment_provider_config.py`); unknown provider values now abort startup. | Prevents a single env var from redirecting payouts to production PayPal or silently changing the execution path. | §7.1, §7.3, `app/core/config.py` |
| P1-2 | Decide whether `paypal_live_probe_api.py` / `paypal_live_probe_connection.py` enter the repository (they are untracked scratch scripts) | They contain no secrets but do perform live calls; they must never be collected by pytest. | §6.4 |
| P1-3 | ~~Add a provider configuration check to `GET /ready`~~ — startup validation now covers missing credentials and unknown providers (§7.3). Remaining: an explicit readiness/log signal naming the selected adapter (never the values). | Fail fast instead of at the first payout. | §7.3 |
| P1-4 | ~~Make the `routing_destination` label consistent with the adapter that ran~~ — **done**: the policy resolves live configuration and the gateway derives its adapter from that policy mode; see `test_gateway_routing.py`. | The label used to be frozen at import time, so it could disagree with the adapter that actually ran. | §7.2, `app/gateway/policy.py`, `app/gateway/service.py` |
| P1-5 | ~~Fix the 17 absolute `file:///Users/khoria/...` links in `docs/security-boundaries.md`~~ — **done** during the final audit; they are now relative links. | Broken links for every other teammate. | §7.7 |
| P1-6 | Keep `packages/contracts/openapi.json` in sync when the agentic or payout schemas change | The contract is currently byte-equivalent to the generated spec. | §2.9 |
| P1-7 | Decide the CI install path: `pip install -e "apps/api[dev]"` is now the single, non-masking install command (the old fallback dependency list was removed) | A packaging failure must fail the build, not silently install a different dependency set. | `Makefile`, `.github/workflows/ci.yml` |

### 8.2 For Person 2 — risk intelligence / behavioural twin

| # | Item | Why it matters | Reference |
| --- | --- | --- | --- |
| P2-1 | Agent traffic is evaluated by the same risk engine and the same `TrustGatewayPolicy` — **no** agent-specific bypass exists and none should be added | The agentic path inherits `RESTRICTED` / `DECOY` / `ISOLATED` routing unchanged. | §2.5, §2.7 |
| P2-2 | The gateway passes `device_id` and `ip_address` from the authoritative session record into `RiskEvaluationRequest` | Person 2's signals are already fed by the payout path; the agentic path inherits this because it normalizes into the canonical `PayoutRequest`. | `app/gateway/service.py:149` |
| P2-3 | If new trust levels / reason codes are introduced, keep `GatewayAction` ↔ provider-call matrix intact | `RESTRICTED`/`DECOY`/`ISOLATED` must never invoke a provider adapter; the AST invariant and the invocation-matrix test enforce it. | §2.5 |
| P2-4 | `AgenticCommerceAudit` stores the risk decision outcome (`status`, `outcome`, `reason_codes` in the gateway response, `agent_context`) | This is the join point between agent activity and risk evidence. Extend the audit model additively if new agent telemetry is needed. | `app/gateway/agentic.py:440` |
| P2-5 | Amount limits for agents are enforced **before** the risk engine runs (grant cap + agent cap, `min()` of both) | A risk-score-based limit would be a second, independent control — worth deciding explicitly, since today an agent cannot exceed its delegated cap but a human payout has no equivalent delegation cap. | `app/gateway/agentic.py:301` |
| P2-6 | `RISK_THRESHOLD_*` and `RESTRICTED_PAYOUT_LIMIT` drive the routing outcome for agent traffic as well | When thresholds change, re-run the agentic routing-parity tests. | `app/gateway/policy.py` |

---

## 9. Repository state

* Branch: `main`, HEAD `f531c20` ("p2 work is done bitchessssss !").
* 44 paths are modified or untracked in the working tree; the Person 3 work
  (provider hardening, webhook hardening, provenance, agentic commerce,
  packaging fix, documentation) is **not committed**.
* Two files carry an incidental mode change only (`scripts/generate_synthetic.py`,
  `scripts/run_calibration.py`: `100644` → `100755`). The selected Ruff policy
  does not include `EXE001`, so this is not lint-required; keep it if the team
  wants the shebang scripts directly executable, otherwise revert it.
* **Nothing was committed or pushed by this audit.** Committing and pushing are
  left to the repository owner.

---

## 10. Audit verdict

| Area | Verdict |
| --- | --- |
| Provider adapter selection | **Verified** — deterministic; the default is the mock adapter and unknown values fail closed (never fall back to mock) |
| PayPal Sandbox OAuth | **Verified against a mock transport**; live call untested |
| Payout payload mapping | **Verified against a mock transport**; live disbursement untested |
| Idempotency (gateway / provider / agentic) | **Verified** by automated tests and runtime observation |
| Risk-level isolation | **Verified** — matrix enforced by test + AST invariant |
| Webhook verification | **Verified** — fail closed in every tested path; live deliveries untested |
| Agentic-commerce integration | **Verified** — 33 tests, full authorization ladder, audit trail |
| Environment configuration | **Verified** — sandbox host allowlist enforced at settings init and in the adapter (§7.1) |
| API contracts | **Verified** — generated spec equals the committed contract |
| Test suite / lint | **Verified** — 435 passed, Ruff clean, 97 files formatted |
| Live PayPal integration | **Untested (external)** — no automated coverage by design |
