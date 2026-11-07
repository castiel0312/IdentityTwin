# Production Operations Readiness

**Generated:** 2026-11-07T23:10:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead
**Status:** **OPERATIONALLY READY — WITH DOCUMENTED GAPS**

---

## 1. Executive Summary

The application exposes comprehensive observability hooks for monitoring, alerting, and incident response. The codebase includes structured logging, health endpoints, and domain events for all critical paths. However, **operational runbooks and alert routing configuration are not codified** — these are infrastructure/team responsibilities.

**Verdict:** **OPERATIONS READY** — Application provides all required signals; operations team must configure alerts, dashboards, and runbooks.

---

## 2. Application Monitoring

### 2.1 Health Endpoints

| Endpoint | Purpose | Returns | SLA |
|----------|---------|---------|-----|
| `GET /health` | Liveness/readiness probe | `{ "status": "ok", "version": "0.1.0", "environment": "production" }` | < 100ms |
| `GET /v1/system/context` | Deep system context | Environment, feature flags, config (no secrets) | < 200ms |

**Implementation:** `apps/api/app/api/routes/health.py`, `apps/api/app/api/routes/system.py`

### 2.2 Structured Logging (JSON)

All logs use structured JSON with consistent fields:

```json
{
  "time": "2026-11-07T22:00:00.000Z",
  "level": "INFO",
  "logger": "identitytwin.api",
  "message": "HTTP GET /v1/payouts - status=200 duration=45.2ms ip=10.0.0.1",
  "trace_id": "abc123",
  "span_id": "def456"
}
```

**Log Levels:** `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`

**Key Loggers:**
- `identitytwin.api` — HTTP requests, gateway decisions
- `identitytwin.gateway` — Routing decisions, provider execution
- `identitytwin.honey` — Canary hits, containment events
- `identitytwin.evidence` — Seal creation, verification
- `identitytwin.reconciliation` — Worker job claiming, status updates
- `identitytwin.payouts` — Payout lifecycle events

### 2.3 Key Metrics (Application-Emitted)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `path`, `status` | HTTP request volume |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Request latency |
| `gateway_decisions_total` | Counter | `decision`, `trust_level` | ALLOW/REQUIRE_STEP_UP/DECOY_FORWARD/BLOCK |
| `provider_executions_total` | Counter | `provider`, `status` | mock_adapter/paypal_sandbox/honey_synthetic_decoy |
| `payout_status_transitions_total` | Counter | `from_status`, `to_status` | Payout lifecycle |
| `canary_hits_total` | Counter | `kind`, `merchant_id` | Honey canary detections |
| `incident_seals_created_total` | Counter | `merchant_id` | Evidence seal creation |
| `reconciliation_jobs_claimed_total` | Counter | `worker_id`, `outcome` | Worker job processing |
| `webhook_events_received_total` | Counter | `event_type`, `verified` | PayPal webhook volume |
| `agent_spending_limit_exhausted_total` | Counter | `grant_id`, `merchant_id` | Spending limit breaches |

---

## 3. Payment Monitoring

### 3.1 Payout Submission Failures

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| `provider_executions_total{provider="paypal_sandbox",status="error"}` | Gateway | > 5/min |
| `payout_status_transitions_total{to_status="provider_denied"}` | Gateway | > 0 (page immediately) |
| `payout_status_transitions_total{to_status="failed"}` | Gateway | > 0 (page immediately) |
| `gateway_decisions_total{decision="BLOCK"}` | Gateway | > 10/min (unexpected spike) |

### 3.2 PayPal API Errors

| Error Code | Meaning | Action |
|------------|---------|--------|
| `PAYPAL_PAYOUT_NOT_AVAILABLE` | Account/country restriction | **Page Payment Integration Owner** — production payouts will fail |
| `PAYPAL_AUTHENTICATION_FAILED` | Invalid credentials | Rotate credentials, check secret manager |
| `PAYPAL_RATE_LIMIT` | Sandbox rate limit | Back off, check for runaway loop |
| `PAYPAL_NETWORK_ERROR` | Network connectivity | Check egress/firewall |
| `PAYPAL_TEMPORARY_OUTAGE` | PayPal 5xx | Retry via reconciliation worker |

### 3.3 Pending & Ambiguous Payouts

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| Pending payouts | `payout_status = 'pending'` | > 100 (stuck queue) |
| Pending reconciliation | `payout_status = 'pending_reconciliation'` | > 10 (reconciliation lag) |
| Ambiguous timeouts | `ProviderTimeoutException` in logs | > 0 (page on-call) |

### 3.4 Reconciliation Failures

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| `reconciliation_jobs_claimed_total{outcome="failed"}` | Worker | > 0 |
| `reconciliation_jobs_claimed_total{outcome="timeout"}` | Worker | > 5/min |
| Worker lag | `MAX(created_at) - NOW()` for pending jobs | > 5 minutes |

### 3.5 Webhook Processing Failures

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| `webhook_events_received_total{verified="false"}` | Webhook endpoint | > 10/min (potential attack) |
| `webhook_events_received_total{event_type="PAYMENT.PAYOUTSBATCH.DENIED"}` | Webhook | > 0 (correlate with payout) |
| Duplicate webhook rate | Idempotency rejection logs | > 100/min (misconfiguration) |

---

## 4. Security Monitoring

### 4.1 Canary Events

| Signal | Severity | Action |
|--------|----------|--------|
| `canary_hits_total` | **CRITICAL** | **Page Security Team immediately** — Active attack |
| `canary_cross_session_reuse` | **HIGH** | Page Security Team — Reconnaissance attempt |
| `canary_inspection_oversized` | MEDIUM | Log for capacity planning |

### 4.2 Cross-Session Reuse Attempts

Logged as `canary_cross_session_reuse` evidence event with:
- `canary_session_id` vs `observed_session_id`
- `requesting_merchant_id`, `requesting_user_id`
- `matched_in` path

### 4.3 Tenant Authorization Failures

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| 403 responses on honey endpoints | Gateway logs | > 20/min |
| 403 on evidence queries | Evidence service | > 10/min |
| Foreign merchant access attempts | Authorization middleware | > 0 (page) |

### 4.4 Evidence Verification Failures

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| Seal verification `valid=false` | Evidence API | > 0 (page immediately — data integrity) |
| Hash chain broken | Evidence service | > 0 (page immediately) |

### 4.5 Gateway BLOCK Events

| Signal | Source | Alert Threshold |
|--------|--------|-----------------|
| `gateway_decisions_total{decision="BLOCK"}` | Gateway | > 5/min (unexpected spike) |
| ISOLATED session creation | Session service | Correlate with canary hits |

### 4.6 Suspicious Access Patterns

| Pattern | Detection | Action |
|---------|-----------|--------|
| Rapid session creation | `sessions_created_total` rate | Rate limit / investigate |
| Repeated step-up failures | `step_up_challenges_failed_total` | Account takeover signal |
| Unusual payout recipients | New payee + large payout | Risk engine already scores |

---

## 5. Operational Procedures

### 5.1 Incident Response

| Scenario | Runbook | Owner |
|----------|---------|-------|
| **Canary hit (active attack)** | `runbooks/canary_hit.md` | Security Team |
| **Payout provider down (PayPal outage)** | `runbooks/paypal_outage.md` | Payment Integration Owner |
| **Reconciliation worker stuck** | `runbooks/reconciliation_stuck.md` | Platform Team |
| **Evidence seal verification failure** | `runbooks/evidence_integrity.md` | Security + Platform |
| **Database connection exhaustion** | `runbooks/db_connections.md` | Platform Team |
| **Secret rotation required** | `runbooks/secret_rotation.md` | Platform + Security |
| **PayPal credential compromise** | `runbooks/paypal_credential_rotation.md` | Payment Integration Owner |

**Status:** Runbooks **not yet written** — must be created before production deployment.

### 5.2 Database Restore

| Procedure | RTO | RPO | Tested |
|-----------|-----|-----|--------|
| Point-in-time recovery (PITR) | < 15 min | < 1 min | ❌ Not tested |
| Full backup restore | < 30 min | < 24 hr | ❌ Not tested |
| Migration rollback (schema only) | < 5 min | N/A | ✅ Verified in `PRODUCTION_DATABASE_READINESS.md` |

### 5.3 Application Rollback

| Procedure | Trigger | Steps |
|-----------|---------|-------|
| Kubernetes rollout undo | Failed health checks, error spike | `kubectl rollout undo deployment/identitytwin-api` |
| Blue/green switch | Canary deployment failure | Switch traffic to previous version |
| Database + app rollback | Migration data corruption | 1. Stop app 2. PITR restore 3. Deploy previous app version |

### 5.4 Secret Rotation

| Secret | Rotation Frequency | Procedure |
|--------|-------------------|-----------|
| `CANARY_HMAC_SECRET` | 90 days | 1. Generate new secret 2. Update secret manager 3. Rolling restart 4. Re-issue canaries |
| `EVIDENCE_HMAC_KEY` | 90 days | 1. Generate new key 2. Update secret manager 3. Rolling restart 4. Re-seal incidents |
| `PAYPAL_CLIENT_SECRET` | Per PayPal policy | 1. Rotate in PayPal Dashboard 2. Update secret manager 3. Rolling restart |
| `OIDC` keys | Automatic (JWKS) | JWKS cache TTL handles rotation |

**Status:** Procedures **documented in this report only** — formal runbooks needed.

### 5.5 Worker Restart

| Worker | Restart Command | Graceful Shutdown |
|--------|-----------------|-------------------|
| API (uvicorn) | `kubectl rollout restart deployment/identitytwin-api` | SIGTERM → finish request → exit |
| Reconciliation | `kubectl rollout restart deployment/identitytwin-reconciliation` | SIGTERM → release job lock → exit |

### 5.6 Reconciliation Recovery

| Scenario | Recovery |
|----------|----------|
| Worker crashed mid-job | Job lock expires (TTL), another worker claims |
| PayPal timeout during reconciliation | Job re-queued with exponential backoff |
| Duplicate webhook processed | Idempotency key prevents duplicate reconciliation |
| Status transition invalid | Logged, payout status unchanged, manual review |

### 5.7 Evidence Preservation

- Evidence log entries are **immutable** (insert-only)
- Incident seals are **immutable** (insert-only)
- Hash-chain checkpoints provide **tamper evidence**
- No automated deletion — retention policy required

---

## 6. Alert Ownership Matrix

| Alert Category | Primary Owner | Secondary Owner | Escalation |
|----------------|---------------|-----------------|------------|
| Canary hit | Security Lead | Platform Lead | CISO |
| Payout failure (provider) | Payment Integration Owner | Platform Lead | VP Engineering |
| Reconciliation lag | Platform Lead | Payment Integration Owner | VP Engineering |
| Evidence integrity failure | Security Lead | Platform Lead | CISO |
| Database issues | Platform Lead | DBA | VP Engineering |
| Secret rotation overdue | Platform Lead | Security Lead | VP Engineering |
| High error rate (5xx) | Platform Lead | API Team Lead | VP Engineering |

**Status:** Owners **not formally assigned** — must be configured in alerting system (PagerDuty, OpsGenie, etc.)

---

## 7. Dashboard Requirements

| Dashboard | Key Panels | Tool |
|-----------|------------|------|
| **System Overview** | Request rate, error rate, latency (p50/p95/p99), active sessions | Grafana/Datadog |
| **Payment Health** | Payout throughput, success rate, pending count, provider latency | Grafana/Datadog |
| **Security** | Canary hits, cross-session reuse, auth failures, BLOCK decisions | Grafana/Datadog |
| **Reconciliation** | Queue depth, processing rate, worker count, job duration | Grafana/Datadog |
| **Database** | Connections, query latency, replication lag, cache hit ratio | Grafana/Datadog |

---

## 8. Gaps & Remediation

| Gap | Severity | Remediation | Target |
|-----|----------|-------------|--------|
| Runbooks not written | HIGH | Create 7 runbooks listed in §5.1 | Pre-deployment |
| Alert routing not configured | HIGH | Configure in PagerDuty/OpsGenie with owners | Pre-deployment |
| Dashboards not built | MEDIUM | Build 5 dashboards in Grafana | Week 1 post-deploy |
| PITR restore not tested | HIGH | Schedule restore drill | Pre-deployment |
| Secret rotation procedures not formalized | MEDIUM | Write runbooks for each secret | Pre-deployment |
| Log retention policy not set | MEDIUM | Configure 90-day hot, 1-year cold | Pre-deployment |
| No synthetic canary monitoring | LOW | Deploy canary health check endpoint | Week 1 post-deploy |

---

## 9. Verdict

**PRODUCTION OPERATIONS READINESS: READY — WITH DOCUMENTED OPERATIONAL GAPS**

The application emits all required observability signals for production monitoring. The codebase is instrumented for:
- Health checks
- Structured logging
- Domain metrics (gateway, payouts, honey, evidence, reconciliation, webhooks)
- Security event emission

**Blocking for Production:** None (application-level)

**Required Before Go-Live (Operations Team):**
1. Alert routing configured with named owners
2. Runbooks written for 7 critical scenarios
3. PITR restore tested
4. Dashboards deployed

**Post-Deploy (Week 1):**
1. Synthetic monitoring
2. Log retention policy
3. Canary health check endpoint

---