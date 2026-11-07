# Production Configuration Audit

**Generated:** 2026-11-07T22:30:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead
**Status:** AUDIT COMPLETE — FINDINGS DOCUMENTED

---

## 1. Executive Summary

The production configuration has been audited against the codebase's `Settings` class validation logic (`apps/api/app/core/config.py`). The audit verifies that all production guards are enforced at startup and that the configuration schema correctly prevents insecure defaults.

**Overall Assessment:** Configuration schema is **production-hardened**. All critical settings have explicit validation. No development fallback secrets exist in the code. The primary gap is **operational** — production secret values must be provisioned in the secret manager (not in code).

---

## 2. Payment Provider Configuration

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `PAYMENT_PROVIDER` | Must be explicitly set to `paypal_sandbox` | Enum validation: only `mock` or `paypal_sandbox` allowed. Unknown values fail startup. | ✅ **ENFORCED** |
| `PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE` | Must be `false` (default) unless explicitly authorized | If `PAYMENT_PROVIDER=mock` in production, this must be `true` or startup fails. | ✅ **ENFORCED** |
| Mock provider in production | Rejected by default | `validate_production_guards()` raises `ValueError` if mock selected without override. | ✅ **ENFORCED** |

**Finding:** The code **cannot** silently fall back to mock provider in production. An explicit override flag is required, which must be intentionally set by the deployment pipeline.

---

## 3. PayPal Credentials

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `PAYPAL_CLIENT_ID` | Required when `PAYMENT_PROVIDER=paypal_sandbox` | `validate_payment_provider()` checks non-empty at startup. | ✅ **ENFORCED** |
| `PAYPAL_CLIENT_SECRET` | Required when `PAYMENT_PROVIDER=paypal_sandbox` | Same as above. | ✅ **ENFORCED** |
| `PAYPAL_WEBHOOK_ID` | Required in production with `paypal_sandbox` | `validate_production_guards()` enforces this. | ✅ **ENFORCED** |
| `PAYPAL_BASE_URL` | Must be official Sandbox host | `validate_paypal_base_url()` allowlist: only `api-m.sandbox.paypal.com`. | ✅ **ENFORCED** |

**Finding:** Sandbox credentials **cannot** be accidentally used in production because:
1. Production requires `PAYMENT_PROVIDER=paypal_sandbox` (mock rejected)
2. Production requires `PAYPAL_WEBHOOK_ID` (not set in development)
3. `PAYPAL_BASE_URL` is validated against exact Sandbox host allowlist — production host `api-m.paypal.com` would be rejected

---

## 4. Cryptographic Secrets

| Secret | Production Requirement | Validation | Status |
|--------|------------------------|------------|--------|
| `CANARY_HMAC_SECRET` | ≥32 chars, high entropy (≠ dev default) | `has_valid_canary_secret_entropy()`: rejects `dev-canary-secret-change-me`, enforces ≥32 chars, entropy ≥3.5 | ✅ **ENFORCED** |
| `EVIDENCE_HMAC_KEY` | ≥32 chars, high entropy | `has_valid_secret_entropy()`: enforces ≥32 chars, entropy ≥3.5 | ✅ **ENFORCED** |
| `SECRET_KEY` (JWT) | Strong, production-specific | Not explicitly validated — **GAP** (see below) | ⚠️ **NOT EXPLICITLY VALIDATED** |

**Finding:** `CANARY_HMAC_SECRET` and `EVIDENCE_HMAC_KEY` have strong entropy validation. However, there is **no explicit `SECRET_KEY` field** in the Settings class — JWT signing uses `OIDC` configuration instead. This is acceptable since production uses OIDC/JWT with asymmetric keys (RS256), not a shared secret.

**Correction:** The codebase uses OIDC/JWT with `OIDC_ISSUER_URL`, `OIDC_JWKS_URL`, `OIDC_AUDIENCE` for production auth. No symmetric `SECRET_KEY` is used. This is correct for production.

---

## 5. Database Configuration

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `DATABASE_URL` | PostgreSQL (not SQLite) | `validate_production_guards()` rejects `sqlite` in URL | ✅ **ENFORCED** |
| `HONEY_DB_URL` | Can be separate or same as main | Defaults to `DATABASE_URL` if empty | ✅ **CONFIGURED** |

---

## 6. CORS Configuration

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `CORS_ORIGINS` | Restrictive, explicit origins | Accepts comma-separated list or array. No wildcard validation in code. | ⚠️ **NO WILDCARD BLOCK** |

**Finding:** The code does **not** explicitly reject `*` or overly broad origins. However, the default is restrictive (`localhost` only). Production deployment must explicitly set restrictive origins. **Recommendation:** Add validation to reject `*` in production.

---

## 7. Debug & Development Flags

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `ALLOW_DEV_AUTH` | Must be `false` | `validate_production_guards()` raises if `true` in production | ✅ **ENFORCED** |
| `DEV_AUTH_TOKEN` | Must not be used | Only used when `ALLOW_DEV_AUTH=true` | ✅ **ENFORCED** |
| `ENVIRONMENT` | Must be `production` | Triggers all production guards | ✅ **ENFORCED** |

**Finding:** No development fallback authentication possible in production. The dev auth path is completely gated by `ALLOW_DEV_AUTH=false`.

---

## 8. AI/LLM Configuration

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `AI_LLM_ENABLED` | `false` by default; if `true`, all fields required | `validate_production_guards()` enforces all 4 fields + safe URL | ✅ **ENFORCED** |
| `AI_LLM_BASE_URL` | Public HTTPS, no private hosts | `is_safe_llm_base_url()` rejects localhost, private IPs, metadata endpoints | ✅ **ENFORCED** |
| `AI_LLM_EGRESS_HOST` | Must exactly match BASE_URL host | Exact hostname match enforced | ✅ **ENFORCED** |

**Finding:** LLM narrative is disabled by default (`AI_LLM_ENABLED=false`). If enabled, strict egress controls apply. Deterministic fallback always available.

---

## 9. OIDC/JWT Production Configuration

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| `OIDC_ISSUER_URL` | Required, HTTPS, no credentials | Required in production; URL validation | ✅ **ENFORCED** |
| `OIDC_JWKS_URL` | HTTPS, no credentials | If set, validated | ✅ **ENFORCED** |
| `OIDC_AUDIENCE` | Required | Required in production | ✅ **ENFORCED** |
| `OIDC_ALGORITHMS` | Asymmetric only (RS256, ES256, etc.) | Rejects HS256, none, invalid algos | ✅ **ENFORCED** |
| `OIDC_REQUIRED_CLAIMS` | Must include `sub`, `email`, `roles` | Default includes these; not validated at runtime | ✅ **CONFIGURED** |
| `OIDC_ROLE_CLAIM` | Maps to roles | Default `roles` | ✅ **CONFIGURED** |
| `OIDC_MERCHANT_CLAIM` | Maps to merchant_id | Default `merchant_id` | ✅ **CONFIGURED** |

**Finding:** OIDC configuration is production-ready with asymmetric algorithm enforcement. No symmetric HS256 fallback.

---

## 10. Risk & Risk Intelligence Settings

| Setting | Production Requirement | Validation | Status |
|---------|------------------------|------------|--------|
| Risk weights (8 weights) | Contract-stable values | No runtime validation; tested by calibration suite | ✅ **TEST-COVERED** |
| Risk thresholds (RESTRICTED/DECOY/ISOLATED) | PRD-defined | Defaults match PRD; configurable | ✅ **CONFIGURED** |
| `RISK_SYNTHETIC_SEED` | Deterministic calibration | Fixed default `20260921` | ✅ **FIXED** |

---

## 11. Health Endpoint Information Exposure

| Endpoint | Exposes Config? | Details |
|----------|-----------------|---------|
| `/health` | **No** | Returns basic status only |
| `/v1/system/context` | **Partial** | Returns environment, version, feature flags — **no secrets** |

**Verified:** `Settings.model_config.hide_input_in_errors=True` prevents secret leakage in validation errors. Health endpoints do not dump configuration.

---

## 12. Secret Rotation & Rollback Procedures

| Procedure | Documented | Implementation |
|-----------|------------|----------------|
| `CANARY_HMAC_SECRET` rotation | ❌ Not documented | Requires re-issuing all canaries; existing armed canaries become invalid |
| `EVIDENCE_HMAC_KEY` rotation | ❌ Not documented | Breaks hash-chain verification for existing seals; requires re-sealing |
| `PAYPAL_CLIENT_SECRET` rotation | ❌ Not documented | Standard PayPal rotation; update in secret manager, restart pods |
| `OIDC` key rotation | ❌ Not documented | JWKS cache TTL (default 1hr); automatic via `OIDC_CACHE_JWKS_SECONDS` |
| Application rollback | ❌ Not documented | Requires infrastructure-level procedure (K8s rollout undo, etc.) |
| Database migration rollback | ⚠️ Partial | Alembic `downgrade` supported for all migrations; 018 is idempotent |

**Finding:** Secret rotation procedures are **not formally documented** in the codebase. This is an operational gap that should be addressed in runbooks.

---

## 13. Configuration Audit Summary

| Category | Status | Critical Findings |
|----------|--------|-------------------|
| Payment Provider | ✅ **SECURE** | Mock rejected in production; Sandbox host allowlist enforced |
| PayPal Credentials | ✅ **SECURE** | Required at startup; Sandbox-only URL validation |
| Cryptographic Secrets | ✅ **SECURE** | Entropy validation; no dev defaults in production |
| Database | ✅ **SECURE** | SQLite rejected in production |
| CORS | ⚠️ **NEEDS REVIEW** | No wildcard rejection; deployment must set restrictive origins |
| Debug Flags | ✅ **SECURE** | Dev auth completely disabled in production |
| AI/LLM | ✅ **SECURE** | Disabled by default; strict egress if enabled |
| OIDC/JWT | ✅ **SECURE** | Asymmetric only; required fields enforced |
| Health Endpoints | ✅ **SECURE** | No secret exposure |
| Secret Rotation | ❌ **UNDOCUMENTED** | Operational runbooks needed |

---

## 14. Required Production Configuration Values (Checklist)

| Variable | Required | Example Value | Source |
|----------|----------|---------------|--------|
| `ENVIRONMENT` | ✅ | `production` | Deployment |
| `ALLOW_DEV_AUTH` | ✅ | `false` | Deployment |
| `DATABASE_URL` | ✅ | `postgresql://user:pass@host:5432/db` | Secret Manager |
| `HONEY_DB_URL` | Optional | (same as above or separate) | Secret Manager |
| `PAYMENT_PROVIDER` | ✅ | `paypal_sandbox` | Deployment |
| `PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE` | ✅ | `false` | Deployment |
| `PAYPAL_CLIENT_ID` | ✅ | `Axxxxxxxxxxxx` | Secret Manager |
| `PAYPAL_CLIENT_SECRET` | ✅ | `Exxxxxxxxxxxx` | Secret Manager |
| `PAYPAL_WEBHOOK_ID` | ✅ | `WH-xxxxxxxxxx` | Secret Manager |
| `PAYPAL_BASE_URL` | ✅ | `https://api-m.sandbox.paypal.com` | Deployment (fixed) |
| `CANARY_HMAC_SECRET` | ✅ | 64-char high-entropy string | Secret Manager |
| `EVIDENCE_HMAC_KEY` | ✅ | 64-char high-entropy string | Secret Manager |
| `OIDC_ISSUER_URL` | ✅ | `https://tenant.auth0.com` | Secret Manager |
| `OIDC_JWKS_URL` | ✅ | `https://tenant.auth0.com/.well-known/jwks.json` | Secret Manager |
| `OIDC_AUDIENCE` | ✅ | `identitytwin-api` | Deployment |
| `CORS_ORIGINS` | ✅ | `https://console.identitytwin.com` | Deployment |
| `AI_LLM_ENABLED` | Optional | `false` | Deployment |
| `RISK_THRESHOLD_RESTRICTED` | Optional | `30.0` | Deployment |
| `RISK_THRESHOLD_DECOY` | Optional | `60.0` | Deployment |
| `RISK_THRESHOLD_ISOLATED` | Optional | `90.0` | Deployment |

---

## 15. Verdict

**PRODUCTION CONFIGURATION AUDIT: PASS WITH OPERATIONAL NOTES**

The configuration schema enforces all critical security properties at startup. No insecure defaults can reach production. The two operational gaps are:

1. **CORS wildcard not explicitly rejected** — Mitigation: Deployment pipeline must set explicit origins.
2. **Secret rotation procedures undocumented** — Mitigation: Create runbooks before production deployment.

**Recommendation:** Approve configuration for production deployment contingent on:
- Deployment pipeline setting restrictive `CORS_ORIGINS`
- Operations team creating secret rotation runbooks
- Payment Integration Owner confirming PayPal credentials are provisioned in secret manager

---