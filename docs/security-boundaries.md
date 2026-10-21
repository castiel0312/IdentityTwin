# IdentityTwin Security Boundaries and Threat Model

This document defines the security boundaries of the IdentityTwin Trust Gateway, detailing what it protects, what falls outside its interception surface, and guidelines for production deployment.

---

## 1. Protected Security Perimeter

The Trust Gateway acts as the authoritative control checkpoint for all sensitive financial operations. It actively protects:

### A. Protected Payment Operations (`POST /v1/payouts`)
- **Single Chokepoint Enforcement**: All money movement operations MUST pass through `TrustGatewayService`. No individual route handler, background worker, or external script has direct access to the payment provider adapter.
- **Provider Isolation Invariant**: Under non-eligible trust levels (`RESTRICTED`, `DECOY`, `ISOLATED`), payment provider adapters (PayPal / banking rails) are physically prevented from executing.
- **Idempotency Execution Guard**: Protects against double-spend, network retry duplicates, and replay attacks via database-backed hash and unique key checks.
- **Payload Tampering Protection**: If a client replays an existing idempotency key with modified amounts, currencies, or recipients, the request is rejected with `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`.
- **Post-Provider Crash Safety**: If a database error occurs after the payment provider executes, the idempotency record is locked to `provider_executed`. Subsequent retries are strictly blocked from re-invoking the provider, preventing double payout executions.
- **Fail-Closed Corrupt Trust Handling**: Sessions with unrecognized, invalid, or tampered trust states fail-closed to `ISOLATED` and block all protected transactions.

### B. Session and Identity Authorization
- **Authoritative Principal Resolution**: The caller's merchant scope, user ID, and role are resolved exclusively through server-validated authentication tokens.
- **Ownership Verification**: Requests claiming to act on a session are checked against `session.merchant_id == principal.merchant_id` and `session.user_id == principal.user_id`. Mismatched ownership results in immediate HTTP 403 Forbidden.
- **Anti-Tampering Guard**: Clients cannot supply `trust_level`, `risk_score`, or `routing_destination` in request bodies. Pydantic schemas enforce `extra="forbid"`, and policy evaluation calculates trust independently.
- **Dev Auth Hardening**: `X-Dev-*` headers cannot bypass token requirements; unauthenticated requests without recognized bearer tokens are rejected with HTTP 401.

### C. Incident & Investigation Integrity
- **Role-Based Access Control (RBAC)**: Only principals with the `analyst` or `admin` role may approve or resolve security incidents. Merchants cannot self-approve incidents.
- **Cross-Merchant Isolation**: Analysts are strictly scoped to their assigned merchant domain. Cross-merchant approval attempts are blocked.
- **Non-Execution Invariant**: Incident approval only updates the review state and audit log; it does NOT automatically disengage isolation or execute payouts.

---

## 2. Boundaries and Non-Intercepted Surfaces

The Trust Gateway is an application-level security control for payment and identity trust. It does **NOT** intercept:

1. **Direct Bank / Provider Inbound Webhooks**: Inbound PayPal or banking notifications should terminate at a dedicated webhook verification service before updating IdentityTwin session states.
2. **Infrastructure-Level DDoS / Layer 4 Attacks**: Volumetric DDoS mitigation must be handled upstream by a WAF / reverse proxy (Cloudflare, AWS CloudFront, or NGINX).
3. **Internal Database Direct Access**: Database credentials must be protected at the network layer with PostgreSQL VPC security groups and TLS encryption.
4. **Offline Hardware Theft**: Physical device theft without biometric session anomaly detection falls to endpoint mobile device management (MDM).

---

## 3. Authentication Abstraction and Production Transition

### Local Development Authentication
To enable frictionless local development and cross-role automated testing without external OAuth providers:
- `ALLOW_DEV_AUTH=true` is permitted **only** when `ENVIRONMENT=development`.
- Development tokens (`dev-merchant-token`, `dev-analyst-token`) or `X-Dev-*` headers simulate authenticated principals.

### Production Security Guards
- **Strict Startup Guard**: `apps/api/app/core/config.py` enforces that if `ENVIRONMENT=production`, `ALLOW_DEV_AUTH` must be `false` and SQLite connection strings are rejected.
- **Production OIDC Hook**: In production, `get_current_principal` verifies JWT bearer tokens signed by an enterprise OIDC/OAuth2 identity provider (e.g., Auth0, Okta, AWS Cognito, Google Cloud Identity) using cryptographic JWKS validation.

```mermaid
graph LR
    subgraph Development Mode
        DevCaller[Local Test / cURL] -->|Bearer dev-merchant-token| DevAuth[Dev Auth Abstraction]
        DevAuth --> Principal[Authoritative Principal]
    end

    subgraph Production Mode
        ProdCaller[Merchant Browser / App] -->|Bearer JWT Token| OIDC[OIDC / JWKS Provider]
        OIDC -->|Cryptographic Verification| Principal
    end
```

---

## 4. Credential and Data Privacy Guarantees

- **No Secret / Token Persistence**: Raw passwords, API secrets, and Bearer tokens are never stored in database tables or logs.
- **Sanitized Request Logging**: The logging middleware intercepts all HTTP requests and logs timing, method, URL path, and client IP, but explicitly redacts request headers (`Authorization`) and request body payloads.
- **Synthetic Test Mock**: `MockPaymentProviderAdapter` generates explicit `SYNTH-MOCK-TXN-...` identifiers with clear simulation warnings. It never claims real money moved.

---

## 5. Gateway Invariants and Proof Tests

The IdentityTwin Trust Gateway enforces fundamental mathematical and architectural security guarantees across all money-movement operations. Every invariant is backed by automated proof tests:

| Invariant Guarantee | Verification Mechanism & Proof Test | Test File |
| :--- | :--- | :--- |
| **No Payment Adapter Bypass** | AST scan asserts zero modules outside `app/gateway` import provider adapters or provider getters. | `test_ast_scan_no_provider_imports_outside_gateway` in [`test_no_bypass.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_no_bypass.py) |
| **Provider Invocation Matrix** | Configured payment provider adapter is called exactly once for `NORMAL`, and zero times for `RESTRICTED`, `DECOY`, `ISOLATED`, or `revoked`. | `test_provider_invocation_matrix_trust_levels`, `test_provider_invocation_matrix_revoked_session` in [`test_no_bypass.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_no_bypass.py) |
| **Hero Attack & Canary Isolation** | Canary interaction immediately transitions session to Level 3 (`ISOLATED`), revokes session in DB, creates critical security incident, and denies subsequent payout attempts (provider count = 0). | `test_hero_attack_sequence_canary_to_payout_block` in [`test_no_bypass.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_no_bypass.py) |
| **Server-Issued Step-Up Verification** | Client cannot forge step-up tokens. Tokens are single-use, 5-minute time-bound OTP challenges bound to session and merchant. | `test_forged_step_up_token_rejected`, `test_reused_step_up_token_rejected`, `test_expired_step_up_challenge_rejected`, `test_other_session_step_up_token_rejected` in [`test_step_up.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_step_up.py) |
| **Restricted Payout Limits** | Payouts above $500.00 are rejected unconditionally in RESTRICTED state. Payouts under $500.00 require server-verified step-up proof. | `test_restricted_payout_exceeding_limit_rejected`, `test_restricted_payout_within_limit_without_step_up_rejected` in [`test_hardening_readiness.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_hardening_readiness.py) |
| **Decoy Confinement** | DECOY sessions route exclusively to synthetic honey handlers. Real payment rails are never contacted. | `test_decoy_session_routed_to_synthetic_honey_never_paypal` in [`test_hardening_readiness.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_hardening_readiness.py) |
| **Session Ownership Enforcement** | Payouts and event ingestion enforce row-level session ownership matching the authenticated principal's user and merchant UUID. | `test_events_payouts_cross_merchant_rejected`, `test_session_user_ownership_mismatch` in [`test_security_audit.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_security_audit.py) |
| **Idempotency Execution Guard & Replay Prevention** | Duplicate idempotency requests return cached responses without re-executing provider. Parameter tampering fails closed. | `test_idempotency_same_key_different_amount_rejected`, `test_concurrent_duplicate_idempotency_keys_handled_safely` in [`test_security_audit.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_security_audit.py) |
| **Post-Provider Crash Safety** | Database failures after provider execution mark the record `provider_executed`. Subsequent retries are strictly blocked from re-invoking provider. | `test_post_provider_crash_safety_locks_idempotency` in [`test_hardening_readiness.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_hardening_readiness.py) |
| **Incident Approval Non-Bypass** | Analyst approval logs audit notes but NEVER re-enables an isolated session or triggers a payout. | `test_incident_approval_does_not_bypass_payout_policy` in [`test_security_audit.py`](file:///Users/khoria/IdentityTwin/apps/api/tests/test_security_audit.py) |

---

## 6. Handoff Note for Risk Intelligence & Twin Owner (Person 2)

> [!IMPORTANT]
> **Server-Side Behavioral Signal Derivation Requirement**
> 
> In the current hackathon foundation baseline, client telemetry requests (`POST /v1/events`) and payout requests (`POST /v1/payouts`) may accept contextual signals (e.g., `device_id`, `ip_address`, `metadata`) that are evaluated by `DeterministicRiskEngineService` in [`service.py`](file:///Users/khoria/IdentityTwin/apps/api/app/risk/service.py).
>
> **Action Required by Person 2**:
> 1. Implement `IRiskEngineService` in [`apps/api/app/risk/service.py`](file:///Users/khoria/IdentityTwin/apps/api/app/risk/service.py) with ML/heuristic behavioral models (evaluating keystroke biometrics, mouse flight dynamics, and IP/device velocity against stored baseline profiles).
> 2. **Never trust client-supplied risk flags**: Contextual flags (such as `is_new_device`, `is_new_location`, or `is_unusual_time`) must be derived **server-side** by comparing incoming telemetry against the user's historical profile and active sessions in the database, rather than trusting raw client payload flags.
> 3. Emit named risk signals (e.g., `MOUSE_VELOCITY_ANOMALY`, `KEYSTROKE_FLIGHT_DELTA`, `CANARY_INTERACTION`) and bounded risk scores (`0.0 - 100.0`). The Gateway Policy will continue to authoritatively govern routing and isolation.
