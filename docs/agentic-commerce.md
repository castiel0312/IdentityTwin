# Agentic Commerce Contract (Person 3)

> Internal contract for AI-agent initiated commerce. There is **no third-party
> agentic payment specification implemented in this repository**: the shapes
> below are an *internal IdentityTwin contract* between an AI agent (or the
> merchant application embedding one) and the Trust Gateway.

---

## 1. Why this contract exists

An AI agent can act far faster than a human. That is exactly why it must not be
allowed to act *outside* the Trust Gateway. IdentityTwin therefore treats agent
traffic as a **shape transformation problem**, not a trust problem:

```
Agent request  --->  INTERNAL ADAPTER  --->  Trust Gateway  --->  Provider / Honey / Block
 (agent shaped)      (authorize +          (risk + policy +
                     normalize)            idempotency)
```

The agent may only state **what** it wants to do and **which delegation**
allows it. It may never state who it is, how trusted it is, how risky the
transaction is, or which merchant it acts for. Everything else is resolved
server side.

## 2. Non-negotiable invariants

| # | Invariant | Enforcement |
| :--- | :--- | :--- |
| 1 | **No bypass route to PayPal.** The agentic path never touches a provider adapter. | `app/gateway/agentic.py` imports no provider adapter; `tests/test_agentic_commerce.py::test_agentic_modules_never_import_payment_providers_directly` fails on any such import. |
| 2 | **Merchant identity is server owned.** The merchant always comes from the authenticated principal. | `PayoutRequest` has no merchant field; the agent request schema forbids unknown fields. |
| 3 | **Agent identity is server resolved.** Display name, type, vendor, scopes and limits come from the registry, never from the body. | `AgenticCommerceRequest` only carries `agent_id`; `AgenticCommerceAdapter.authorize()` resolves everything else. |
| 4 | **Risk evaluation is unchanged.** Agent traffic is scored by the same risk engine as human traffic. | The adapter delegates to `TrustGatewayService.execute_payout()`; Person 2's engine is untouched. |
| 5 | **Idempotency is preserved.** The caller supplied key is forwarded verbatim, so agent retries are deduplicated exactly like human retries. | `AgenticCommerceAdapter.normalize()` copies `idempotency_key` unchanged. |
| 6 | **A delegation is not a credential.** A grant never authenticates anybody; the caller must additionally present a valid merchant session. | `get_current_principal()` is still enforced on the route. |
| 7 | **Every authorized attempt that reaches execution is attributable.** Successful, blocked/decoy, duplicate-replay and failed executions are written to the agentic audit trail; requests rejected during authorization never reach the gateway. | `AgenticCommerceService._record_audit()`. |

## 3. The internal adapter interface

`app/gateway/agentic.py`

```python
@runtime_checkable
class IAgenticCommerceAdapter(Protocol):
    def authorize(
        self,
        db: Session,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
    ) -> AgentAuthorizationDecision: ...

    def normalize(
        self,
        request: AgenticCommerceRequest,
        principal: AuthenticatedPrincipal,
        decision: AgentAuthorizationDecision,
    ) -> PayoutRequest: ...
```

* `authorize()` resolves the acting agent and its delegation from the registry
  and fails closed. It returns the server resolved `AgentIdentity` plus the
  `AgentAuthorizationContext` (delegating user, scopes, ceiling, expiry).
* `normalize()` turns the agent shaped request into the canonical
  `PayoutRequest` consumed by the Trust Gateway. It is a pure transformation:
  no provider call, no policy decision, no state mutation.

`AgenticCommerceService.submit()` is the orchestrator used by the HTTP layer:

1. `adapter.authorize(...)` — delegation checks (fail closed).
2. `adapter.normalize(...)` — agent shape -> gateway shape.
3. `gateway_service.execute_payout(...)` — the *only* execution path.
4. Audit record written for the outcome.

## 4. Data model

| Table | Purpose |
| :--- | :--- |
| `agent_registrations` | Who the agent is: merchant, display name, type, vendor, scopes, status, per-agent amount ceiling. |
| `agent_authorization_grants` | The delegation: agent + merchant + user (+ optional session), scopes, max amount, issued/expiry/consumed/revoked. |
| `agentic_commerce_audit` | Append-only trail: agent, grant, merchant, user, session, payout, idempotency key, amount, outcome, authorization context. |

Migration: `apps/api/alembic/versions/005_agentic_commerce.py`.

Demo rows are seeded by `scripts/seed_demo.py` (agent `7777...`, grant `8888...`).

## 5. Endpoint

### `POST /v1/agentic/payouts`

Request body (`AgenticCommerceRequest`, unknown fields rejected):

| Field | Type | Required | Notes |
| :--- | :--- | :--- | :--- |
| `agent_id` | UUID | yes | The registered agent that acts. |
| `authorization_grant_id` | UUID | yes | The delegation that authorizes this action. |
| `session_id` | UUID | yes | The merchant session the agent acts within. |
| `recipient_email` | string | yes | Payout recipient. |
| `amount` | float | yes | `> 0`, `<= 100000`. |
| `currency` | string | no | ISO-4217, default `USD`. |
| `reference_note` | string | no | Business reference (audit only). |
| `idempotency_key` | string | yes | 8-128 chars, preserved verbatim. |
| `step_up_token` | string | no | Required when the session is RESTRICTED. |
| `agent_intent` | string | no | Free text description of the agent intent, recorded for audit only. |

Response body (`AgenticCommerceResponse`): the complete Trust Gateway payout
response (`payout_id`, `decision_id`, `status`, `trust_level`, `action`,
`routing_destination`, `risk_score`, `reason_codes`, `provider_reference`,
`amount`, `currency`, `recipient_email`, `created_at`, `is_duplicate`) plus the
agent provenance (`agent_id`, `agent_display_name`, `agent_type`,
`authorization_grant_id`, `delegated_by_user_id`, `agent_intent`).

```bash
curl -X POST http://localhost:8000/v1/agentic/payouts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_id": "77777777-7777-7777-7777-777777777777",
        "authorization_grant_id": "88888888-8888-8888-8888-888888888888",
        "session_id": "22222222-2222-2222-2222-222222222222",
        "recipient_email": "vendor@example.com",
        "amount": 120.00,
        "currency": "USD",
        "idempotency_key": "agentic-order-8842",
        "agent_intent": "Settle invoice 8842 for the merchant"
      }'
```

### Error codes

| Code | HTTP | Meaning |
| :--- | :--- | :--- |
| `AGENT_NOT_REGISTERED` | 403 | Unknown agent reference. |
| `AGENT_MERCHANT_MISMATCH` | 403 | Agent belongs to another merchant. |
| `AGENT_NOT_ACTIVE` | 403 | Agent registration suspended/revoked. |
| `AGENT_AUTHORIZATION_MISSING` | 403 | Unknown grant. |
| `AGENT_AUTHORIZATION_AGENT_MISMATCH` | 403 | Grant was issued to another agent. |
| `AGENT_AUTHORIZATION_MERCHANT_MISMATCH` | 403 | Grant belongs to another merchant. |
| `AGENT_AUTHORIZATION_PRINCIPAL_MISMATCH` | 403 | Grant was issued to another user. |
| `AGENT_AUTHORIZATION_REVOKED` | 403 | Grant revoked. |
| `AGENT_AUTHORIZATION_CONSUMED` | 403 | Grant is marked consumed; only the exact idempotent replay of its original request is allowed. |
| `AGENT_AUTHORIZATION_EXPIRED` | 403 | Grant expired. |
| `AGENT_AUTHORIZATION_SESSION_MISMATCH` | 403 | Grant is bound to another session. |
| `AGENT_SCOPE_NOT_GRANTED` | 403 | `payout:execute` not granted. |
| `AGENT_AMOUNT_LIMIT_EXCEEDED` | 403 | Amount above the delegated/registered ceiling. |
| `AGENT_IDEMPOTENCY_KEY_CONFLICT` | 409 | Key already bound to another execution context. |
| `VALIDATION_ERROR` | 422 | Missing agent context or unknown field. |
| `SESSION_NOT_FOUND` / `SESSION_OWNERSHIP_MISMATCH` | 404 / 403 | The Trust Gateway refused the session. |

### Routing outcomes (identical to human traffic)

| Session trust state | Agent request outcome | Provider touched |
| :--- | :--- | :--- |
| `NORMAL` | `completed` / `ALLOW` | yes, exactly once |
| `RESTRICTED` | `rejected` / `REQUIRE_STEP_UP` | no |
| `DECOY` | `decoy_completed` / `DECOY_FORWARD` | no (honey workspace only) |
| `ISOLATED` | `blocked` / `BLOCK` + incident | no |

## 6. Idempotency and context isolation

The Trust Gateway namespaces idempotency keys by `(merchant_id, key)`. A naive
agentic endpoint would therefore let an agent replay the key of a direct human
payout and inherit its cached result. The adapter blocks this:

* if the key is already bound to a payout **without** an agentic audit row
  (a human payout), the request is rejected with `AGENT_IDEMPOTENCY_KEY_CONFLICT`;
* if the key is bound to a **different agent**, it is rejected the same way;
* if the key belongs to the **same agent**, the request is a legitimate retry
  and the cached gateway response is returned (`is_duplicate: true`).

## 7. Operational notes

* Agent registration and grant issuance are **administrative, merchant scoped
  operations** (repository + seed script today). A future management endpoint
  must reuse the same checks; it must never let a caller mint a grant for
  another merchant.
* `agent_authorization_grants.consumed_at` is a single-use marker. The adapter
  does not auto-consume grants, so a retry of the same request keeps returning
  the cached result; a merchant may still issue genuinely single-use grants.
* The audit trail is the integration point for the evidence pipeline (Person 5):
  `agentic_commerce_audit` links agent -> grant -> payout.
