# Production Risk Register

**Generated:** 2026-11-07T23:30:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead
**Release Candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`
**Status:** **CONSOLIDATED — FORMAL ACCEPTANCE REQUIRED**

---

## 1. Risk Register

| ID | Risk | Severity | Likelihood | Impact | Mitigation | Owner | Target Date | Evidence | Acceptance Authority | Status |
|----|------|----------|------------|--------|------------|-------|-------------|----------|---------------------|--------|
| **INT-005** | PayPal Sandbox verification blocked — no approved accounts | **HIGH** | **CERTAIN** | Production payouts fail with `PAYPAL_PAYOUT_NOT_AVAILABLE` until accounts approved | 1. Explicit error mapping (`PAYPAL_PAYOUT_NOT_AVAILABLE`)<br>2. Fail-fast startup validation<br>3. Reservations released on definitive failure<br>4. Monitoring alert on first failure | Payment Integration Owner | **Before production payouts** | `PAYPAL_SANDBOX_VERIFICATION_REPORT.md` | Payment Integration Owner + Release Approver | **BLOCKED — EXTERNAL DEPENDENCY** |
| **PAYPAL-001** | PayPal account/country restrictions persist after deployment | MEDIUM | MEDIUM | Ongoing payout failures, merchant impact | 1. Structured error with `restriction_type: "account_or_country"`<br>2. Alert on `PAYPAL_PAYOUT_NOT_AVAILABLE`<br>3. Runbook for credential rotation<br>4. Fallback to mock with explicit override (if authorized) | Payment Integration Owner | Week 1 post-deploy | PayPal Developer Dashboard status | Payment Integration Owner | **OPEN** |
| **METRICS-001** | No durable provider metrics endpoint (payout latency, success rate by provider) | LOW | CERTAIN | Limited observability of provider health | 1. Application logs contain provider execution details<br>2. Structured logging enables log-based metrics<br>3. Accept as design gap; implement in v0.2 | Platform Lead | v0.2 (Q1 2027) | `PRODUCTION_OPERATIONS_READINESS.md` §2.3 | Platform Lead | **ACCEPTED DESIGN GAP** |
| **FRONTEND-001** | Partial real-time frontend coverage (SSE only for containment, not all events) | LOW | CERTAIN | Some UI updates require manual refresh | 1. SSE implemented for containment stream<br>2. React Query polling for other data (configurable interval)<br>3. Accept as v0.1 scope; enhance in v0.2 | Frontend Lead | v0.2 (Q1 2027) | `frontend/src/lib/sse.ts`, React Query config | Frontend Lead | **ACCEPTED LIMITATION** |
| **LLM-001** | LLM availability — optional narrative may fail | LOW | MEDIUM | Deterministic fallback always used; no scoring impact | 1. `AI_LLM_ENABLED=false` by default<br>2. Deterministic narrative always runs<br>3. LLM failure → graceful degradation to deterministic<br>4. Egress host enforcement prevents SSRF | AI/ML Lead | Ongoing | `apps/api/app/core/config.py` LLM validation | AI/ML Lead | **ACCEPTED LIMITATION** |
| **FASTREFRESH-001** | Fast Refresh warning in `auth.tsx` (re-exports non-component) | **NONE** | CERTAIN | Dev-only warning; no production impact | 1. Documented as acceptable<br>2. File re-exports types for backward compatibility<br>3. No runtime behavior change<br>4. Can be fixed in v0.2 with proper barrel file | Frontend Lead | v0.2 (Q1 2027) | `PRODUCTION_REGRESSION_REPORT.md` §3.2 | Frontend Lead | **CONFIRMED HARMLESS** |
| **CORS-001** | CORS wildcard not explicitly rejected in production config | MEDIUM | LOW | Overly permissive CORS if misconfigured | 1. Deployment pipeline must set explicit origins<br>2. Default is restrictive (localhost only)<br>3. Add startup validation in v0.2 | Platform Lead | Pre-deployment | `PRODUCTION_CONFIGURATION_AUDIT.md` §6 | Platform Lead | **MITIGATED BY PROCESS** |
| **SECRETS-001** | Secret rotation procedures not formalized | MEDIUM | MEDIUM | Delayed rotation, potential exposure | 1. Documented in `PRODUCTION_OPERATIONS_READINESS.md` §5.4<br>2. Runbooks to be written pre-deployment<br>3. 90-day rotation calendar | Platform Lead + Security Lead | Pre-deployment | `PRODUCTION_OPERATIONS_READINESS.md` | Platform Lead + Security Lead | **OPEN — RUNBOOKS NEEDED** |
| **RUNBOOKS-001** | Operational runbooks not written | HIGH | CERTAIN | Incident response delayed, inconsistent | 1. 7 critical runbooks identified in `PRODUCTION_OPERATIONS_READINESS.md` §5.1<br>2. Assign owners, write before deployment | Platform Lead | Pre-deployment | `PRODUCTION_OPERATIONS_READINESS.md` | Platform Lead + VP Engineering | **OPEN — BLOCKING DEPLOYMENT** |
| **ALERTS-001** | Alert routing not configured | HIGH | CERTAIN | No pages fired for critical events | 1. Configure in PagerDuty/OpsGenie with owners from `PRODUCTION_OPERATIONS_READINESS.md` §6<br>2. Test alert firing pre-deployment | Platform Lead | Pre-deployment | `PRODUCTION_OPERATIONS_READINESS.md` | Platform Lead | **OPEN — BLOCKING DEPLOYMENT** |
| **PITR-001** | PITR restore not tested | HIGH | LOW | Cannot recover from data corruption | 1. Schedule restore drill pre-deployment<br>2. Document RTO/RPO | Platform Lead + DBA | Pre-deployment | `PRODUCTION_OPERATIONS_READINESS.md` §5.2 | Platform Lead + DBA | **OPEN — BLOCKING DEPLOYMENT** |
| **MIGRATION-001** | Migration 019 (durable_domain_events) new table — untested at production scale | LOW | LOW | Performance issues with outbox pattern | 1. Table is append-only, indexed on `merchant_id`, `status`, `created_at`<br>2. Worker uses `SELECT FOR UPDATE SKIP LOCKED`<br>3. Monitor `durable_domain_events` growth post-deploy | Platform Lead | Week 1 post-deploy | `apps/api/app/models/domain_events.py` | Platform Lead | **MONITOR** |
| **DEPLOY-001** | Staging rehearsal not yet executed | HIGH | CERTAIN | Unknown deployment issues in production | 1. Full staging rehearsal per `PRODUCTION_DEPLOYMENT_AND_ROLLBACK_PLAN.md` §17<br>2. Must pass before production authorization | Release Engineer | Pre-deployment | `PRODUCTION_DEPLOYMENT_AND_ROLLBACK_PLAN.md` | Release Approver | **OPEN — BLOCKING DEPLOYMENT** |

---

## 2. Risk Acceptance Matrix

| Risk ID | Acceptance Required From | Acceptance Criteria | Current Status |
|---------|-------------------------|---------------------|----------------|
| **INT-005** | Payment Integration Owner + Release Approver | Formal acknowledgment that PayPal Sandbox verification is blocked; acceptance of first-production-payout-as-verification OR mock override authorization | **PENDING** |
| **METRICS-001** | Platform Lead | Acknowledged as v0.1 design gap; tracked for v0.2 | **ACCEPTED** |
| **FRONTEND-001** | Frontend Lead | Acknowledged as v0.1 scope; tracked for v0.2 | **ACCEPTED** |
| **LLM-001** | AI/ML Lead | Deterministic fallback sufficient for v0.1 | **ACCEPTED** |
| **FASTREFRESH-001** | Frontend Lead | Confirmed harmless, documented | **ACCEPTED** |
| **CORS-001** | Platform Lead | Deployment process enforces restrictive origins | **MITIGATED** |
| **SECRETS-001** | Platform Lead + Security Lead | Runbooks written and tested pre-deployment | **PENDING** |
| **RUNBOOKS-001** | Platform Lead + VP Engineering | All 7 runbooks written, reviewed, accessible | **PENDING — BLOCKING** |
| **ALERTS-001** | Platform Lead | Alerts configured, tested, owners assigned | **PENDING — BLOCKING** |
| **PITR-001** | Platform Lead + DBA | Restore drill completed successfully | **PENDING — BLOCKING** |
| **MIGRATION-001** | Platform Lead | Monitoring in place, no action needed pre-deploy | **MONITOR** |
| **DEPLOY-001** | Release Approver | Staging rehearsal completed, all checklist items passed | **PENDING — BLOCKING** |

---

## 3. Blocker Summary for Production Deployment

### **Must Resolve Before Production Authorization**

| Blocker | Risk ID | Required Action |
|---------|---------|-----------------|
| Staging rehearsal not executed | DEPLOY-001 | Complete full staging rehearsal checklist |
| Runbooks not written | RUNBOOKS-001 | Write 7 critical runbooks |
| Alert routing not configured | ALERTS-001 | Configure PagerDuty/OpsGenie with owners |
| PITR restore not tested | PITR-001 | Execute restore drill |
| INT-005 disposition not formally accepted | INT-005 | Payment Integration Owner + Release Approver sign-off |

### **Can Deploy With Formal Acceptance**

| Risk | Acceptance Authority | Status |
|------|---------------------|--------|
| INT-005 (PayPal blocked) | Payment Integration Owner + Release Approver | **PENDING** |
| METRICS-001 (No provider metrics endpoint) | Platform Lead | **ACCEPTED** |
| FRONTEND-001 (Partial real-time) | Frontend Lead | **ACCEPTED** |
| LLM-001 (LLM availability) | AI/ML Lead | **ACCEPTED** |
| FASTREFRESH-001 (Dev warning) | Frontend Lead | **ACCEPTED** |
| CORS-001 (Wildcard not rejected) | Platform Lead | **MITIGATED BY PROCESS** |

---

## 4. Risk Trend

| Risk ID | Previous Status | Current Status | Trend |
|---------|-----------------|----------------|-------|
| INT-005 | BLOCKED (remediation sprint) | BLOCKED — EXTERNAL DEPENDENCY | ↔ Stable |
| PAYPAL-001 | Not identified | OPEN | ↑ New |
| METRICS-001 | Not identified | ACCEPTED DESIGN GAP | ↔ New |
| FRONTEND-001 | Not identified | ACCEPTED LIMITATION | ↔ New |
| LLM-001 | Not identified | ACCEPTED LIMITATION | ↔ New |
| FASTREFRESH-001 | Documented in remediation | CONFIRMED HARMLESS | ↔ Stable |
| CORS-001 | Not identified | MITIGATED BY PROCESS | ↔ New |
| SECRETS-001 | Not identified | OPEN | ↑ New |
| RUNBOOKS-001 | Not identified | OPEN — BLOCKING | ↑ New |
| ALERTS-001 | Not identified | OPEN — BLOCKING | ↑ New |
| PITR-001 | Not identified | OPEN — BLOCKING | ↑ New |
| MIGRATION-001 | Not identified | MONITOR | ↑ New |
| DEPLOY-001 | Not identified | OPEN — BLOCKING | ↑ New |

---

## 5. Formal Acceptance Records

*To be completed during approval phase*

### INT-005 Acceptance

```
Payment Integration Owner: _________________________ Date: __________
Release Approver: _________________________________ Date: __________

Acceptance: ☐ Authorize production with mock override (PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE=true)
           ☐ Authorize production with paypal_sandbox; accept first payout as live verification
           ☐ Defer production until PayPal accounts approved
```

### METRICS-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
Acceptance: ☐ Acknowledged as v0.1 design gap; will implement in v0.2
```

### FRONTEND-001 Acceptance

```
Frontend Lead: ____________________________________ Date: __________
Acceptance: ☐ Acknowledged as v0.1 scope; will enhance in v0.2
```

### LLM-001 Acceptance

```
AI/ML Lead: _______________________________________ Date: __________
Acceptance: ☐ Deterministic fallback sufficient for v0.1
```

### FASTREFRESH-001 Acceptance

```
Frontend Lead: ____________________________________ Date: __________
Acceptance: ☐ Confirmed harmless, documented, will fix in v0.2
```

### CORS-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
Acceptance: ☐ Deployment pipeline enforces restrictive origins
```

### SECRETS-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
Security Lead: ____________________________________ Date: __________
Acceptance: ☐ Runbooks written, reviewed, tested pre-deployment
```

### RUNBOOKS-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
VP Engineering: ___________________________________ Date: __________
Acceptance: ☐ All 7 runbooks written, reviewed, accessible in runbook system
```

### ALERTS-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
Acceptance: ☐ Alerts configured, tested, owners assigned in PagerDuty/OpsGenie
```

### PITR-001 Acceptance

```
Platform Lead: ____________________________________ Date: __________
DBA: _____________________________________________ Date: __________
Acceptance: ☐ Restore drill completed successfully, RTO/RPO validated
```

### DEPLOY-001 Acceptance

```
Release Engineer: _________________________________ Date: __________
Release Approver: _________________________________ Date: __________
Acceptance: ☐ Staging rehearsal completed, all checklist items passed
```

---

## 6. Summary

| Category | Count | Blocking | Accepted | Open |
|----------|-------|----------|----------|------|
| **Critical (Blocking Deployment)** | 5 | 5 | 0 | 0 |
| **High (Must Resolve)** | 2 | 0 | 0 | 2 |
| **Medium (Mitigated/Process)** | 3 | 0 | 1 | 2 |
| **Low (Accepted/Monitor)** | 4 | 0 | 4 | 0 |
| **Total** | **14** | **5** | **5** | **4** |

**Production Deployment Authorization Requires:**
1. All 5 **Critical** blockers resolved
2. **INT-005** formally accepted by Payment Integration Owner + Release Approver
3. **RUNBOOKS-001**, **ALERTS-001**, **PITR-001**, **DEPLOY-001** completed
4. Remaining risks formally accepted per matrix above

---