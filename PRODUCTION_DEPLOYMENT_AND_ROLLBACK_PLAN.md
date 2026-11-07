# Production Deployment and Rollback Plan

**Generated:** 2026-11-07T23:20:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead
**Release Candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff` (tag: `rc-20261107-63a3a9d`)
**Status:** **PLAN COMPLETE — STAGING REHEARSAL REQUIRED**

---

## 1. Release Candidate

| Attribute | Value |
|-----------|-------|
| **Git SHA** | `63a3a9d935f0c4b36469d68f40e10bb9496284ff` |
| **Tag** | `rc-20261107-63a3a9d` (to be created) |
| **API Version** | `0.1.0` |
| **Frontend Version** | `1.0.0` |
| **Migration Head** | `019_durable_domain_events` |

---

## 2. Deployment Artifacts

| Artifact | Build Command | Output | Verification |
|----------|---------------|--------|--------------|
| **API Docker Image** | `docker build -t identitytwin-api:rc-20261107-63a3a9d -f apps/api/Dockerfile apps/api` | `identitytwin-api:rc-20261107-63a3a9d` | `docker run --rm identitytwin-api:rc-20261107-63a3a9d python -c "import app; print('OK')"` |
| **Frontend Static Assets** | `cd frontend && npm run build` | `frontend/dist/` | `ls -la frontend/dist/` |
| **Frontend Docker Image** | `docker build -t identitytwin-console:rc-20261107-63a3a9d -f frontend/Dockerfile frontend` | `identitytwin-console:rc-20261107-63a3a9d` | `docker run --rm identitytwin-console:rc-20261107-63a3a9d ls /usr/share/nginx/html` |

---

## 3. Infrastructure Prerequisites

| Component | Specification | Status |
|-----------|---------------|--------|
| **Kubernetes Cluster** | 1.28+, 3+ worker nodes | ⚠️ Provision |
| **PostgreSQL** | 15+, 4 vCPU, 16GB RAM, multi-AZ | ⚠️ Provision |
| **Redis** | 7+, 2 vCPU, 8GB RAM (for rate limiting) | ⚠️ Provision |
| **Ingress Controller** | NGINX or ALB | ⚠️ Configure |
| **Secret Manager** | HashiCorp Vault / AWS Secrets Manager / GCP Secret Manager | ⚠️ Configure |
| **Certificate Manager** | cert-manager / ACM | ⚠️ Configure |
| **Monitoring Stack** | Prometheus + Grafana / Datadog | ⚠️ Configure |
| **Log Aggregation** | Loki / CloudWatch / Elasticsearch | ⚠️ Configure |

---

## 4. Required Secrets (Provision in Secret Manager)

| Secret Key | Description | Rotation |
|------------|-------------|----------|
| `DATABASE_URL` | `postgresql://user:pass@host:5432/identitytwin` | 90 days |
| `HONEY_DB_URL` | `postgresql://user:pass@host:5432/identitytwin_honey` (or same) | 90 days |
| `PAYPAL_CLIENT_ID` | PayPal Sandbox App Client ID | Per PayPal |
| `PAYPAL_CLIENT_SECRET` | PayPal Sandbox App Client Secret | Per PayPal |
| `PAYPAL_WEBHOOK_ID` | PayPal Webhook ID for signature verification | Per PayPal |
| `CANARY_HMAC_SECRET` | 64-char high-entropy string | 90 days |
| `EVIDENCE_HMAC_KEY` | 64-char high-entropy string | 90 days |
| `OIDC_ISSUER_URL` | `https://tenant.auth0.com` | N/A |
| `OIDC_JWKS_URL` | `https://tenant.auth0.com/.well-known/jwks.json` | N/A |
| `OIDC_AUDIENCE` | `identitytwin-api` | N/A |
| `DEV_AUTH_TOKEN` | **Empty in production** | N/A |

---

## 5. Environment Variables (ConfigMap / Deployment)

```yaml
env:
  - name: ENVIRONMENT
    value: "production"
  - name: ALLOW_DEV_AUTH
    value: "false"
  - name: PAYMENT_PROVIDER
    value: "paypal_sandbox"  # or "mock" with PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE=true
  - name: PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE
    value: "false"
  - name: PAYPAL_BASE_URL
    value: "https://api-m.sandbox.paypal.com"
  - name: CORS_ORIGINS
    value: "https://console.identitytwin.com,https://admin.identitytwin.com"
  - name: AI_LLM_ENABLED
    value: "false"
  - name: INTENT_PROFILER_ENABLED
    value: "true"
  - name: LOG_LEVEL
    value: "INFO"
  - name: LOG_FORMAT
    value: "json"
  - name: RISK_THRESHOLD_RESTRICTED
    value: "30.0"
  - name: RISK_THRESHOLD_DECOY
    value: "60.0"
  - name: RISK_THRESHOLD_ISOLATED
    value: "90.0"
  - name: RESTRICTED_PAYOUT_LIMIT
    value: "500.0"
```

---

## 6. Database Backup (Pre-Deployment)

```bash
# 1. Create pre-deployment backup
pg_dump -h <prod-host> -U <user> -d identitytwin \
  --format=custom --compress=9 --no-owner --no-privileges \
  > /backups/pre-deploy-$(date +%Y%m%d-%H%M%S).dump

# 2. Verify backup integrity
pg_restore --list /backups/pre-deploy-*.dump | head -20

# 3. Enable WAL archiving (if not already)
# postgresql.conf: archive_mode=on, archive_command='cp %p /wal_archive/%f'
```

---

## 7. Migration Sequence

### 7.1 Pre-Deployment Migration Check

```bash
# Dry-run to verify migration SQL
alembic upgrade head --sql > /tmp/migration-$(date +%Y%m%d).sql
# Review SQL for: DROP COLUMN, RENAME, type changes, lock-heavy operations
```

### 7.2 Migration Execution

```bash
# Run migrations (idempotent, safe to re-run)
kubectl exec -it deploy/identitytwin-api -- alembic upgrade head

# Verify migration state
kubectl exec -it deploy/identitytwin-api -- alembic current
# Expected: 019_durable_domain_events (head)
```

### 7.3 Migration Validation

```bash
# Verify critical tables exist
kubectl exec -it deploy/identitytwin-api -- python -c "
from app.db.session import SessionLocal
from sqlalchemy import inspect
db = SessionLocal()
inspector = inspect(db.bind)
tables = inspector.get_table_names()
critical = ['merchants', 'sessions', 'payout_requests', 'evidence_log_entries', 'incident_seals', 'canary_records', 'durable_domain_events']
for t in critical:
    assert t in tables, f'Missing table: {t}'
print('All critical tables present')
"

# Verify migration 018 idempotency (vaccination_matches.updated_at)
kubectl exec -it deploy/identitytwin-api -- python -c "
from app.db.session import SessionLocal
from sqlalchemy import inspect
db = SessionLocal()
inspector = inspect(db.bind)
cols = [c['name'] for c in inspector.get_columns('vaccination_matches')]
assert 'updated_at' in cols, 'Migration 018 not applied'
print('Migration 018 verified')
"
```

---

## 8. Application Deployment Sequence

### 8.1 API Deployment

```yaml
# k8s/api-deployment.yaml (key settings)
replicas: 3
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 20
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "2000m"
    memory: "2Gi"
```

```bash
# Deploy API
kubectl set image deployment/identitytwin-api api=identitytwin-api:rc-20261107-63a3a9d
kubectl rollout status deployment/identitytwin-api --timeout=5m
```

### 8.2 Frontend Deployment

```bash
# Deploy frontend (static assets via nginx)
kubectl set image deployment/identitytwin-console console=identitytwin-console:rc-20261107-63a3a9d
kubectl rollout status deployment/identitytwin-console --timeout=3m
```

### 8.3 Worker Deployment (Reconciliation)

```yaml
# k8s/reconciliation-worker-deployment.yaml
replicas: 2  # Minimum 2 for HA
strategy:
  type: Recreate  # Workers hold job locks; rolling update causes contention
```

```bash
kubectl set image deployment/identitytwin-reconciliation worker=identitytwin-api:rc-20261107-63a3a9d
kubectl rollout status deployment/identitytwin-reconciliation --timeout=3m
```

---

## 9. Health Checks (Post-Deployment)

| Check | Command | Expected |
|-------|---------|----------|
| **API Health** | `curl -sf https://api.identitytwin.com/health` | `{"status":"ok",...}` |
| **API Deep Health** | `curl -sf -H "Authorization: Bearer <token>" https://api.identitytwin.com/v1/system/context` | 200 OK, JSON |
| **Frontend Load** | `curl -sf https://console.identitytwin.com/` | 200 OK, HTML |
| **Database Connectivity** | `kubectl exec deploy/identitytwin-api -- python -c "from app.db.session import SessionLocal; SessionLocal().execute('SELECT 1')"` | Success |
| **Migration State** | `kubectl exec deploy/identitytwin-api -- alembic current` | `019_durable_domain_events (head)` |
| **PayPal Config** | `curl -sf -H "Authorization: Bearer <token>" https://api.identitytwin.com/v1/system/context \| jq .payment_provider` | `"paypal_sandbox"` |

---

## 10. Smoke Tests

```bash
# 1. Authentication flow
TOKEN=$(curl -sf -X POST https://api.identitytwin.com/v1/auth/token -d "client_id=..." | jq -r .access_token)

# 2. Session creation
SESSION=$(curl -sf -H "Authorization: Bearer $TOKEN" -X POST https://api.identitytwin.com/v1/sessions -d '{"merchant_id":"..."}' | jq -r .session_id)

# 3. Risk scoring (should return NORMAL for new session)
curl -sf -H "Authorization: Bearer $TOKEN" https://api.identitytwin.com/v1/sessions/$SESSION/risk

# 4. Payout submission (mock or sandbox)
curl -sf -H "Authorization: Bearer $TOKEN" -X POST https://api.identitytwin.com/v1/payouts \
  -H "Idempotency-Key: smoke-test-$(date +%s)" \
  -d '{"session_id":"'$SESSION'","amount":10.00,"currency":"USD","recipient_email":"test@example.com"}'

# 5. Evidence seal verification
curl -sf -H "Authorization: Bearer $TOKEN" https://api.identitytwin.com/v1/incidents/<incident_id>/seal
```

---

## 11. Payment Provider Verification

| Check | Command | Expected |
|-------|---------|----------|
| **Provider Config** | `GET /v1/system/context` | `payment_provider: "paypal_sandbox"` |
| **OAuth Token** | Internal (check logs) | `PayPal OAuth token acquired` |
| **Webhook Endpoint** | `POST /webhooks/paypal` (test payload) | 200 OK, verified |
| **Reconciliation Worker** | Check logs | `Worker claimed job`, `PayPal batch retrieved` |

---

## 12. Monitoring Checks

| Check | Dashboard/Alert | Verification |
|-------|-----------------|--------------|
| **API Request Rate** | Grafana: `rate(http_requests_total[5m])` | > 0 |
| **Error Rate** | Grafana: `rate(http_requests_total{status=~"5.."}[5m])` | < 1% |
| **P50/P95 Latency** | Grafana: `histogram_quantile(0.5, ...)`, `histogram_quantile(0.95, ...)` | < 200ms / < 500ms |
| **Gateway Decisions** | Grafana: `rate(gateway_decisions_total[5m])` | Distribution matches expectations |
| **Canary Hits** | Alert: `canary_hits_total > 0` | 0 (page if > 0) |
| **Reconciliation Queue** | Grafana: `payout_status = 'pending_reconciliation'` | < 10 |

---

## 13. Rollback Triggers

| Trigger | Detection | Action |
|---------|-----------|--------|
| **Health check failures** | `/health` returns non-200 for > 2 min | Immediate rollback |
| **Error rate spike** | 5xx rate > 5% for 5 min | Immediate rollback |
| **Payout failures** | `PAYPAL_PAYOUT_NOT_AVAILABLE` on first production payouts | Rollback to mock (if authorized) or pause payouts |
| **Evidence integrity failure** | Seal verification `valid=false` | **FULL ROLLBACK + DATABASE RESTORE** |
| **Canary hit** | `canary_hits_total > 0` | Investigate, do NOT rollback (attack evidence) |
| **Migration failure** | `alembic upgrade head` fails | Rollback app, restore DB from backup |

---

## 14. Rollback Steps

### 14.1 Application Rollback (Code Only)

```bash
# 1. Rollback API
kubectl rollout undo deployment/identitytwin-api
kubectl rollout status deployment/identitytwin-api --timeout=3m

# 2. Rollback Frontend
kubectl rollout undo deployment/identitytwin-console
kubectl rollout status deployment/identitytwin-console --timeout=2m

# 3. Rollback Workers
kubectl rollout undo deployment/identitytwin-reconciliation
kubectl rollout status deployment/identitytwin-reconciliation --timeout=2m

# 4. Verify previous version
kubectl exec deploy/identitytwin-api -- python -c "import app; print(app.__version__)"
```

### 14.2 Database Rollback (Schema + Data)

**Only if migration caused data corruption or evidence integrity failure.**

```bash
# 1. STOP ALL APPLICATION TRAFFIC
kubectl scale deployment/identitytwin-api --replicas=0
kubectl scale deployment/identitytwin-reconciliation --replicas=0

# 2. Restore from pre-deployment backup
pg_restore -h <prod-host> -U <user> -d identitytwin \
  --clean --if-exists --no-owner --no-privileges \
  /backups/pre-deploy-<timestamp>.dump

# 3. Verify schema version
kubectl exec -it deploy/identitytwin-api -- alembic current
# Should show previous revision (e.g., 018)

# 4. Deploy previous application version
kubectl set image deployment/identitytwin-api api=identitytwin-api:<previous-tag>
kubectl rollout status deployment/identitytwin-api --timeout=5m

# 5. Restore traffic
kubectl scale deployment/identitytwin-api --replicas=3
kubectl scale deployment/identitytwin-reconciliation --replicas=2
```

### 14.3 Database Rollback (Schema Only — No Data Loss)

```bash
# If only schema migration needs revert (no data corruption)
kubectl exec -it deploy/identitytwin-api -- alembic downgrade -1
# Repeat until desired revision

# Verify
kubectl exec -it deploy/identitytwin-api -- alembic current

# Restart app to pick up schema
kubectl rollout restart deployment/identitytwin-api
```

---

## 15. Database Recovery Considerations

| Scenario | Recovery Approach |
|----------|-------------------|
| **Migration 018 failed** | Idempotent — re-run `alembic upgrade head` |
| **Migration 019 failed** | Downgrade to 018, investigate, re-run |
| **Data corruption in payout_requests** | PITR to pre-deployment backup |
| **Evidence log corruption** | **FULL PITR RESTORE** — evidence is immutable |
| **Canary/incident seal corruption** | **FULL PITR RESTORE** — seals are immutable |
| **Partial data loss (single table)** | `pg_restore --table=table_name` from backup |

---

## 16. Post-Deployment Validation

| Validation | Command | Pass Criteria |
|------------|---------|---------------|
| **API version** | `GET /health` | `version: "0.1.0"` |
| **Migration head** | `alembic current` | `019_durable_domain_events (head)` |
| **Payment provider** | `GET /v1/system/context` | `paypal_sandbox` (or authorized mock) |
| **CORS** | `curl -H "Origin: https://console.identitytwin.com" -v` | `Access-Control-Allow-Origin: https://console.identitytwin.com` |
| **OIDC auth** | Login flow | Redirects to IdP, returns JWT |
| **Honey workspace** | `GET /v1/honey/operator/workspaces` (analyst token) | 200 OK, redacted secrets |
| **Canary issuance** | `GET /v1/honey/developer/apps?session_id=...` | 200 OK, secrets hidden |
| **Payout flow** | Submit test payout | Status `completed` or `pending_reconciliation` |
| **Webhook** | Send test webhook | 200 OK, verified |
| **Reconciliation** | Check worker logs | Jobs claimed, status updated |

---

## 17. Staging Rehearsal Checklist

**Before production deployment, execute full rehearsal in staging:**

| Step | Staging Command | Verified |
|------|-----------------|----------|
| 1. Provision staging infra | `terraform apply -var env=staging` | ☐ |
| 2. Load secrets to staging | `vault kv put secret/staging/identitytwin ...` | ☐ |
| 3. Backup staging DB | `pg_dump ... > staging-pre-deploy.dump` | ☐ |
| 4. Run migrations | `alembic upgrade head` | ☐ |
| 5. Deploy API + Frontend + Workers | `kubectl set image ...` | ☐ |
| 6. Health checks | All endpoints 200 | ☐ |
| 7. Smoke tests | Full smoke test suite | ☐ |
| 8. Payment provider test | Submit test payout (mock or sandbox) | ☐ |
| 9. Webhook test | Send test webhook | ☐ |
| 10. Reconciliation test | Verify worker processes jobs | ☐ |
| 11. Security tests | Canary hit, evidence seal, authZ | ☐ |
| 12. Rollback drill | `kubectl rollout undo` + verify | ☐ |
| 13. DB rollback drill | Restore from backup + verify | ☐ |
| 14. Monitoring validation | Alerts fire, dashboards update | ☐ |

---

## 18. Deployment Authorization

**This plan requires explicit authorization before production deployment.**

| Role | Name | Signature | Date |
|------|------|-----------|------|
| **Release Approver** | | | |
| **Payment Integration Owner** | | | |
| **Security Owner** | | | |
| **Database/Infrastructure Owner** | | | |
| **QA/Release Owner** | | | |

---

## 19. Next Actions

1. [ ] Tag release candidate: `git tag rc-20261107-63a3a9d 63a3a9d935f0c4b36469d68f40e10bb9496284ff`
2. [ ] Build and push Docker images to registry
3. [ ] Provision production infrastructure
4. [ ] Load secrets to production secret manager
5. [ ] Execute staging rehearsal (full checklist above)
6. [ ] Obtain deployment authorization (signatures above)
7. [ ] Schedule production deployment window
8. [ ] Execute production deployment per this plan
9. [ ] Post-deployment validation (Section 16)
10. [ ] Monitor for 30 minutes, then declare success

---