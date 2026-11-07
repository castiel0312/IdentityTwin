# EXTERNAL INTEGRATION REPORT — IdentityTwin

**Audit Date:** 2026-11-07  
**Release Candidate:** 593b048f8da5bf77868aa9af2e1e4f12a0c7f155  

---

## Executive Summary

**External integrations are correctly configured but not fully verified.** PayPal Sandbox integration is configured and code paths tested with mock provider. However, **real PayPal Sandbox verification remains blocked (INT-005)** due to lack of approved Sandbox receiver account. All 54 PayPal-related tests pass using mock provider. AI/LLM integration is disabled by default.

---

## PayPal Integration

### Configuration
```python
# From settings (validated at startup)
PAYMENT_PROVIDER: "mock" | "paypal_sandbox"  # Default: "mock"
PAYPAL_CLIENT_ID: ""  # Required for paypal_sandbox
PAYPAL_CLIENT_SECRET: ""  # Required for paypal_sandbox
PAYPAL_WEBHOOK_ID: ""  # Required for production paypal_sandbox
PAYPAL_BASE_URL: "https://api-m.sandbox.paypal.com"  # Allowlisted
PAYPAL_REQUEST_TIMEOUT: 10.0  # seconds
```

### URL Allowlist (Security Critical)
```python
PAYPAL_SANDBOX_HOST = "api-m.sandbox.paypal.com"
PAYPAL_ALLOWED_SANDBOX_HOSTS = frozenset({PAYPAL_SANDBOX_HOST})

def validate_paypal_base_url(value: str) -> str:
    # Rejects: empty, non-https, credentials, non-standard ports, paths, production hosts
    # Only allows: https://api-m.sandbox.paypal.com (exact match)
    return PAYPAL_SANDBOX_BASE_URL
```

### Provider Adapters
| Adapter | Class | Mode | Status |
|---------|-------|------|--------|
| Mock Sandbox | `MockSandboxProvider` | `PAYMENT_PROVIDER=mock` | ✅ Active (default) |
| PayPal Sandbox | `PayPalSandboxProvider` | `PAYMENT_PROVIDER=paypal_sandbox` | ⚠️ Configured, not tested |

### Mock Provider Behavior (`MockSandboxProvider`)
- **`execute_payout`**: Returns synthetic `provider_batch_id`, `provider_transaction_id`, status `SUCCESS`/`DENIED`/`FAILED`
- **`get_payout_batch`**: Returns simulated batch status for reconciliation testing
- **No network calls** — fully in-memory
- **Deterministic** — same inputs produce same outputs

### PayPal Test Coverage (54 tests)
| Test Module | Tests | Coverage |
|-------------|-------|----------|
| `test_paypal_config.py` | 50 | Config validation, URL allowlist, credential requirements |
| `test_paypal_provider.py` | 50 | Provider adapter behavior, error mapping, retries |
| `test_payment_provider_config.py` | 44 | Provider selection, production guards |

**All 54 tests pass** — but only exercise **mock provider code paths**.

### Webhook Verification
- **Endpoint:** `POST /v1/webhooks/paypal`
- **Verification:** HMAC-SHA256 with `PAYPAL_WEBHOOK_ID`
- **Fail-Closed:** Invalid signature → 400, event discarded
- **Tests:** 36 tests in `test_webhook_verification.py` — all pass (mock signatures)

### Egress Proxy (Squid)
```yaml
# docker-compose.yml
paypal-egress:
  image: ubuntu/squid:latest
  entrypoint: ["/bin/sh", "/opt/identitytwin/squid-entrypoint.sh"]
  environment:
    AI_LLM_ENABLED: ${AI_LLM_ENABLED:-false}
    AI_LLM_EGRESS_HOST: ${AI_LLM_EGRESS_HOST:-}
  networks:
    - identitytwin_private
    - gateway_egress
  volumes:
    - ./scripts/docker/squid-entrypoint.sh:/opt/identitytwin/squid-entrypoint.sh:ro
```

- **Purpose:** Restrict outbound PayPal/LLM traffic to allowlisted hosts
- **Configuration:** `HTTP_PROXY=http://paypal-egress:3128`, `HTTPS_PROXY=http://paypal-egress:3128`
- **Allowlist:** `NO_PROXY=localhost,127.0.0.1,api,db,paypal-egress,gateway`

---

## INT-005: PayPal Sandbox Verification Status

### Blocking Issue
```
INT-005: BLOCKED — EXTERNAL DEPENDENCY
```

### Requirements for Unblocking
1. **Approved PayPal Sandbox Receiver Account** — Business account in Sandbox with receiver permissions
2. **Valid Credentials** — `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` for that account
3. **Webhook Configuration** — Sandbox webhook URL pointing to deployed `/v1/webhooks/paypal`
4. **Controlled Payout Test** — Execute real payout to Sandbox receiver, verify completion

### Current State
| Component | Status |
|-----------|--------|
| Sandbox URL Allowlist | ✅ Configured (`api-m.sandbox.paypal.com`) |
| Credential Validation | ✅ Startup validation requires both ID + Secret |
| Mock Provider | ✅ Fully functional, 54 tests pass |
| PayPal Adapter Code | ✅ Implemented, untested against real API |
| Webhook Verification | ✅ Implemented, tested with mock signatures |
| Egress Proxy | ✅ Running (Squid) |
| **Real Sandbox Test** | ❌ **BLOCKED — No receiver account** |

### Risk Assessment
- **Code Quality:** PayPal adapter implements proper error handling, retries, idempotency
- **Security:** URL allowlist prevents production redirect; egress proxy restricts outbound
- **Verification Gap:** No end-to-end test with real PayPal Sandbox
- **Mitigation:** Mock provider covers all gateway routing logic; PayPal adapter only differs in HTTP transport

---

## AI/LLM Integration (Person 6 — AI Investigator)

### Configuration
```python
AI_INVESTIGATION_ENABLED: true  # Deterministic analysis always runs
AI_LLM_ENABLED: false  # Optional narrative disabled by default
AI_LLM_BASE_URL: ""  # Required if LLM enabled
AI_LLM_EGRESS_HOST: ""  # Must match BASE_URL hostname
AI_LLM_API_KEY: ""  # Required if LLM enabled
AI_LLM_MODEL: ""  # Required if LLM enabled
AI_LLM_TIMEOUT: 10.0
AI_LLM_MAX_INPUT_CHARS: 12000
AI_LLM_MAX_RESPONSE_BYTES: 65536
AI_INVESTIGATION_MAX_EVENTS: 100
```

### Safety Controls
1. **Disabled by Default** — `AI_LLM_ENABLED=false`
2. **URL Validation** — `is_safe_llm_base_url()` rejects private/loopback/link-local hosts
3. **Egress Host Pinning** — `AI_LLM_EGRESS_HOST` must exactly match `BASE_URL` hostname
4. **Squid Proxy** — All LLM traffic routes through `paypal-egress` (same as PayPal)
5. **Input Redaction** — Only redacted evidence sent; never raw PII/secrets
6. **Output Limits** — Max 64KB response; structural truncation, not JSON cutting
7. **Advisory Only** — LLM narrative never influences risk scoring, trust levels, or payment routing

### Deterministic Fallback
- When `AI_LLM_ENABLED=false` or provider fails → deterministic narrative generated
- Uses same evidence bundle, same template
- **Zero external dependency** for core investigation functionality

### Test Coverage
- `test_llm_provider_http.py` — 8 tests (HTTP client, timeouts, validation)
- `test_investigations.py` — 18 tests (deterministic narrative, bundle creation)

---

## Database (PostgreSQL) — Internal Service

### Connection
- **Host:** `db` (Docker service name)
- **Port:** 5432 (internal)
- **Network:** `identitytwin_private` (internal=true)
- **Credentials:** `identitytwin_user` / `identitytwin_pass` (from docker-compose)
- **Pool:** SQLAlchemy with `pool_pre_ping=True`

### Security
- ❌ No host port mapping — completely isolated from host
- ✅ Only accessible from `api`, `paypal-egress` (via network), `gateway` containers
- ✅ Dedicated honey role: `honey_rw` with restricted permissions

---

## Redis — Not Configured

- **Status:** Not used in current architecture
- **Background Workers:** In-process (asyncio), no Celery/Redis
- **Rate Limiting:** In-memory (per-process), not distributed
- **Sessions:** Stateless (JWT/Dev tokens), no Redis session store

---

## Monitoring/Observability — Not Configured

| Component | Status |
|-----------|--------|
| Metrics (Prometheus) | ❌ Not implemented |
| Distributed Tracing | ❌ Not implemented |
| Log Aggregation | ❌ Docker stdout only |
| Health Check Endpoints | ✅ `/health`, `/ready` |
| Alerting | ❌ Not configured |

---

## Issues Found

### P0 - Critical: INT-005 PayPal Sandbox Verification Blocked
- **Impact:** Cannot verify real PayPal integration end-to-end
- **Blocker:** No approved Sandbox receiver account
- **Status:** **BLOCKED — EXTERNAL DEPENDENCY**
- **Remediation:** Provision Sandbox business account, configure webhook, execute controlled payout

### P2 - Medium: No Observability Stack
- **Impact:** No production visibility into latency, errors, saturation
- **Components Missing:** Prometheus metrics, structured log aggregation, distributed tracing
- **Remediation:** Add `prometheus-client`, OpenTelemetry, log shipper (Fluent Bit/Vector)

### P3 - Low: AI/LLM Egress Host Validation Only at Startup
- **Observation:** `AI_LLM_EGRESS_HOST` validated at settings load; DNS rebinding possible
- **Impact:** Theoretical SSRF if DNS changes after startup
- **Remediation:** Document residual risk; consider runtime DNS validation

### P3 - Low: Rate Limiting Not Distributed
- **Observation:** In-memory rate limiter per API process
- **Impact:** Multiple replicas would have independent limits
- **Remediation:** Add Redis-backed rate limiter for horizontal scaling

---

## Conclusion

**EXTERNAL INTEGRATION: DEGRADED** — Core integrations configured but not fully verified:
- ✅ PayPal Sandbox URL allowlist enforced
- ✅ PayPal adapter implemented with proper error handling
- ✅ 54 PayPal tests pass (mock provider)
- ✅ Webhook verification implemented (fail-closed)
- ✅ Egress proxy (Squid) running
- ✅ AI/LLM integration disabled by default with safety controls
- ✅ Database fully isolated
- ❌ **INT-005: Real PayPal Sandbox verification BLOCKED**
- ❌ No observability stack
- ⚠️ Rate limiting not distributed