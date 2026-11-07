# PayPal Sandbox Verification Report (INT-005)

**Generated:** 2026-11-07T22:20:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead
**Status:** BLOCKED — EXTERNAL DEPENDENCY

---

## 1. Executive Summary

**INT-005 (PayPal Sandbox payout verification) is BLOCKED due to missing approved PayPal Sandbox accounts.**

The IdentityTwin codebase implements a production-grade PayPal Sandbox adapter with full OAuth token acquisition, payout execution, idempotency, webhook verification, and reconciliation. However, **no authorized PayPal Sandbox sender/receiver accounts are configured or available** in the current environment. Without approved Sandbox accounts, real PayPal API calls cannot be executed, and the verification scenarios cannot be tested against the live PayPal Sandbox.

**Disposition:** BLOCKED — EXTERNAL DEPENDENCY (PayPal account approval/support action required)

---

## 2. PayPal Integration Inspection (B1)

### 2.1 Architecture Overview

The PayPal integration consists of:

| Component | File | Purpose |
|-----------|------|---------|
| **Configuration** | `app/core/config.py` | Settings validation, provider selection, Sandbox host allowlist |
| **Provider Adapter** | `app/gateway/provider.py` | `PayPalSandboxAdapter` — OAuth, payouts, batch retrieval, webhook verification |
| **Webhook Endpoint** | `app/api/routes/webhooks.py` | Signature verification, idempotency, reconciliation |
| **Gateway Routing** | `app/gateway/service.py` | Policy-driven routing to provider or decoy |
| **Idempotency** | `app/db/repositories/idempotency_repo.py` | Deduplication at gateway and provider level |

### 2.2 Key Security Invariants Verified in Code

| Invariant | Implementation | Status |
|-----------|----------------|--------|
| **Sandbox-only host allowlist** | `PAYPAL_ALLOWED_SANDBOX_HOSTS = {"api-m.sandbox.paypal.com"}` | ✅ Enforced at startup |
| **No production host fallback** | `validate_paypal_base_url()` rejects non-allowlist hosts | ✅ Enforced at startup |
| **OAuth token caching** | Cached with 60s pre-expiry refresh | ✅ Implemented |
| **Provider-level idempotency** | `PayPal-Request-Id` header mapped from gateway key | ✅ Implemented |
| **Fail-closed webhook verification** | `verify_webhook_signature()` returns `False` on any error | ✅ Implemented |
| **No credential logging** | Tokens/secrets never logged | ✅ Verified in code |
| **Ambiguous timeout handling** | `ProviderTimeoutException` raised, reservations retained | ✅ Implemented |
| **Duplicate detection** | `DUPLICATE_REQUEST` error mapping | ✅ Implemented |
| **PAYOUT_NOT_AVAILABLE detection** | Explicit error code for account/country restrictions | ✅ Implemented |

### 2.3 Payout Lifecycle (Code Verification)

```
1. Gateway receives payout request
2. Risk scoring → routing decision (NORMAL/RESTRICTED/DECOY/ISOLATED)
3. If NORMAL/RESTRICTED: PayPalSandboxAdapter.execute_payout()
   a. OAuth token acquisition (POST /v1/oauth2/token)
   b. Payout execution (POST /v1/payments/payouts) with PayPal-Request-Id
   c. Response parsing → ProviderPayoutResult
   d. Terminal success only if batch_status == "SUCCESS" AND payout_batch_id present
4. Webhook received (POST /webhooks/paypal)
   a. Signature verification via PayPal API
   b. Idempotency deduplication
   c. Payout status reconciliation
5. Reconciliation worker polls pending payouts via get_payout_batch()
```

**No synthetic provider references or fabricated success responses** — Verified:
- `MockPaymentProviderAdapter` returns `environment: "synthetic_mock"` and `provider_name: "mock_adapter"`
- `PayPalSandboxAdapter` returns `environment: "paypal_sandbox"` and `provider_name: "paypal_sandbox"`
- Provider identity persisted from adapter result, never hardcoded
- `get_payout_batch()` returns `None` if batch not found — no fabrication

---

## 3. Account & Environment Readiness (B2)

### 3.1 Current Configuration State

| Credential | Configured | Value |
|------------|------------|-------|
| `PAYMENT_PROVIDER` | Yes | `mock` (development default) |
| `PAYPAL_CLIENT_ID` | **No** | Empty |
| `PAYPAL_CLIENT_SECRET` | **No** | Empty |
| `PAYPAL_WEBHOOK_ID` | **No** | Empty |
| `PAYPAL_BASE_URL` | Yes | `https://api-m.sandbox.paypal.com` (validated) |

### 3.2 Readiness Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Sandbox sender account | ❌ **NOT AVAILABLE** | No `PAYPAL_CLIENT_ID`/`SECRET` configured |
| Approved Sandbox receiver account | ❌ **NOT AVAILABLE** | No approved receiver documented |
| OAuth token acquisition | ❌ **CANNOT TEST** | Requires valid credentials |
| Payout API access | ❌ **CANNOT TEST** | Requires approved sender account |
| Webhook registration | ❌ **CANNOT TEST** | Requires `PAYPAL_WEBHOOK_ID` |
| Correct Sandbox endpoint | ✅ **CONFIGURED** | `PAYPAL_BASE_URL` validated to `api-m.sandbox.paypal.com` |
| Currency configuration | ⚠️ **NOT TESTED** | Default USD in code, not validated live |

### 3.3 Blocker Details

**Primary Blocker:** PayPal Sandbox accounts with payout permissions are not available.

- PayPal requires **approved business accounts** for Sandbox payouts
- Personal Sandbox accounts or unverified accounts receive `PAYOUT_NOT_AVAILABLE` (403)
- The code explicitly detects this error and reports `restriction_type: "account_or_country"`
- No PayPal Developer Dashboard access has been provisioned for this environment
- No PayPal support ticket or account approval process has been initiated

**Required PayPal Action:**
1. Create/approve PayPal Developer Sandbox **business sender account** with payout permissions
2. Create/approve PayPal Sandbox **receiver account** (can be personal)
3. Configure webhook endpoint in PayPal Developer Dashboard
4. Provide: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`

---

## 4. Controlled Sandbox Payout Scenarios (B3) — NOT EXECUTED

| Scenario | Description | Status | Evidence |
|----------|-------------|--------|----------|
| **1. Successful payout** | Submit controlled Sandbox payout, verify API response, batch/item refs, status retrieval, webhook, reconciliation | **NOT EXECUTED** | Blocker: No approved accounts |
| **2. Definitive failure** | Use supported Sandbox failure condition, verify failure recording, reservation release, audit | **NOT EXECUTED** | Blocker: No approved accounts |
| **3. Duplicate submission** | Same idempotency key twice, verify no duplicate payout, payload mismatch rejection | **NOT EXECUTED** | Blocker: No approved accounts |
| **4. Ambiguous timeout** | Simulate timeout at integration boundary, verify ambiguous classification, reservation retention, reconciliation resolution | **NOT EXECUTED** | Blocker: No approved accounts |
| **5. Webhook & reconciliation** | Verify signature validation, event idempotency, duplicate handling, out-of-order, reconciliation accuracy, no cross-tenant leakage | **NOT EXECUTED** | Blocker: No approved accounts |

**Note:** All PayPal provider unit tests (54 tests) pass using `httpx.MockTransport` — these test **code logic only**, not real PayPal API behavior. They do not constitute INT-005 verification.

---

## 5. INT-005 Disposition (B4)

### Outcome: BLOCKED — EXTERNAL DEPENDENCY

| Criterion | Result |
|-----------|--------|
| Approved Sandbox accounts available | ❌ No |
| Actual Sandbox payout executed | ❌ No |
| Provider references & status retrieval verified | ❌ No |
| Webhook & reconciliation verified | ❌ No |
| Required scenarios passed | ❌ No |

### Technical Integration Tests: PASSING

| Test Suite | Tests | Result |
|------------|-------|--------|
| `test_paypal_provider.py` | 54 | ✅ All Pass (mocked transport) |
| `test_webhook_verification.py` | 12 | ✅ All Pass (mocked transport) |
| `test_provider_provenance.py` | 16 | ✅ All Pass |
| `test_payment_provider_config.py` | 24 | ✅ All Pass |
| `test_reconciliation_worker.py` | 13 | ✅ All Pass |

**Critical Distinction:** Mocked provider tests **do not** verify real PayPal Sandbox behavior. They verify the adapter logic against controlled mock responses only.

---

## 6. Risk Acceptance Package (For Payment Integration Owner)

Since INT-005 is externally blocked, the following risk acceptance is required for production release:

### 6.1 Risk Statement

> **Risk:** Production payouts will execute against PayPal Sandbox without prior end-to-end verification of the live PayPal API integration.
>
> **Impact:** If PayPal account/country restrictions exist (PAYOUT_NOT_AVAILABLE), production payouts will fail with 403 errors. The system correctly classifies this as a definitive failure and releases reservations, but merchants will experience payout failures until accounts are approved.
>
> **Likelihood:** Medium — PayPal Sandbox payout restrictions are common for new/unverified accounts.
>
> **Detection:** Immediate — First production payout attempt will surface the restriction via structured error (`PAYPAL_PAYOUT_NOT_AVAILABLE`).

### 6.2 Mitigations in Place

| Mitigation | Implementation |
|------------|----------------|
| **Explicit error mapping** | `PAYPAL_PAYOUT_NOT_AVAILABLE` error code with `restriction_type: "account_or_country"` |
| **Fail-fast startup validation** | Missing credentials abort startup when `PAYMENT_PROVIDER=paypal_sandbox` |
| **No silent fallback to mock** | Unknown provider values fail closed; mock never selected accidentally |
| **Reservation safety** | On definitive failure (including PAYOUT_NOT_AVAILABLE), reservations released per design |
| **Audit trail** | Full evidence chain records payout attempt, error, and resolution |
| **Monitoring alert** | Payout submission failures generate structured events for ops |

### 6.3 Required Approvals for Production with This Exception

| Role | Approval Required |
|------|-------------------|
| **Payment Integration Owner** | Accept INT-005 BLOCKED disposition; authorize production with known PayPal account risk |
| **Release Approver** | Authorize production deployment with formally accepted exception |
| **Operations Team** | Confirm monitoring/alerting for `PAYPAL_PAYOUT_NOT_AVAILABLE` is configured |

### 6.4 Recommended Path Forward

1. **Immediate:** Provision PayPal Sandbox business accounts via PayPal Developer Dashboard
2. **Short-term:** Execute INT-005 scenarios once accounts approved (estimated 1-2 days)
3. **If accounts unavailable:** Formal risk acceptance per above, with staged rollout:
   - Deploy to production with `PAYMENT_PROVIDER=mock` (requires `PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE=true`)
   - Enable `paypal_sandbox` only after INT-005 verified
   - Or: Accept first production payout as "live verification" with enhanced monitoring

---

## 7. Evidence Summary

| Artifact | Location | Status |
|----------|----------|--------|
| PayPal adapter implementation | `apps/api/app/gateway/provider.py` | ✅ Reviewed |
| Configuration validation | `apps/api/app/core/config.py` | ✅ Reviewed |
| Webhook endpoint | `apps/api/app/api/routes/webhooks.py` | ✅ Reviewed |
| Reconciliation worker tests | `apps/api/tests/test_reconciliation_worker.py` | ✅ 13/13 Pass |
| PayPal provider tests | `apps/api/tests/test_paypal_provider.py` | ✅ 54/54 Pass (mocked) |
| Webhook verification tests | `apps/api/tests/test_webhook_verification.py` | ✅ 12/12 Pass (mocked) |
| Current credentials | Environment | ❌ Not configured |

---

## 8. Final INT-005 Verdict

| Field | Value |
|-------|-------|
| **INT-005 Status** | **BLOCKED — EXTERNAL DEPENDENCY** |
| **Blocker** | No approved PayPal Sandbox sender/receiver accounts |
| **Required Action** | PayPal account provisioning & approval |
| **Technical Readiness** | Code complete, tests passing, integration logic verified |
| **Can Proceed to Production** | Only with formal risk acceptance from Payment Integration Owner + Release Approver |

---

*This report documents the actual state of PayPal Sandbox verification. No mocked test results are represented as real PayPal verification. The code is production-ready; the external dependency is not.*