# Release Candidate Baseline

**Generated:** 2026-11-07T22:15:00Z
**Release Engineer:** Senior Release Engineer / Technical Lead

---

## 1. Git Identity

| Attribute | Value |
|-----------|-------|
| **Commit SHA** | `63a3a9d935f0c4b36469d68f40e10bb9496284ff` |
| **Branch** | `main` |
| **Remote Tracking** | `origin/main` (up to date) |
| **Working Tree** | **Not clean** — 13 modified files, 7 untracked files |

---

## 2. Working Tree Status

### Modified Files (13)

| File | Status | Description |
|------|--------|-------------|
| `apps/api/alembic/versions/018_vaccination_matches_updated_at.py` | Modified | Made migration idempotent for fresh and existing databases |
| `apps/api/app/honey/api.py` | Modified | Canary inspection size limit, body caching, cross-session reuse logging, secret redaction |
| `apps/api/app/honey/canary.py` | Modified | Cross-session canary reuse detection and evidence logging |
| `apps/api/app/services/evidence_query_service.py` | Modified | Full hash-chain verification across all entries, tenant-scoped response filtering |
| `apps/api/tests/honey/test_honey_api.py` | Modified | Tests updated for secret redaction and cross-session reuse behavior |
| `frontend/e2e/console.spec.ts` | Modified | E2E test uses known seeded canary secret |
| `frontend/package-lock.json` | Modified | Dependency lockfile updates (ajv, fast-uri removed) |
| `frontend/src/components/ui/alert-dialog.tsx` | Modified | Import path fix for button-variants |
| `frontend/src/components/ui/badge.tsx` | Modified | Export cleanup (removed badgeVariants export) |
| `frontend/src/components/ui/button.tsx` | Modified | Button variants extracted to separate file |
| `frontend/src/lib/auth.tsx` | Modified | Types extracted to auth-types.ts, re-exports added |
| `frontend/src/lib/sse.ts` | Modified | Session change detection to avoid redundant setState in effect |
| `scripts/seed_demo.py` | Modified | Seeds known canary secret for NORMAL_SESSION E2E testing |

### Untracked Files (7)

| File | Status | Description |
|------|--------|-------------|
| `FINAL_RELEASE_REPORT.md` | Untracked | Previous release report |
| `INTEGRATION_AUDIT_FINAL_REPORT.md` | Untracked | Integration audit report |
| `P4_COMPLETION_REPORT.md` | Untracked | Person 4 completion report |
| `REMEDIATION_COMPLETION_REPORT.md` | Untracked | Remediation completion report |
| `STAGING_VERIFICATION_REPORT.md` | Untracked | Staging verification report |
| `frontend/src/components/ui/button-variants.ts` | Untracked | Extracted button variants (new file) |
| `frontend/src/lib/auth-types.ts` | Untracked | Extracted auth types (new file) |

**Note:** The 5 report files are documentation artifacts from previous phases and do not belong in the release candidate. The 2 new frontend files (`button-variants.ts`, `auth-types.ts`) are part of the remediation refactoring and **must be included** in the release candidate.

---

## 3. Database Migration Revision

| Attribute | Value |
|-----------|-------|
| **Current Head** | `019_durable_domain_events` |
| **Applied Revision (Dev DB)** | `019_durable_domain_events` |
| **Migration 018** | Verified idempotent — applies cleanly on fresh and existing databases |
| **Migration 019** | Durable domain events table — applied and verified |

---

## 4. Dependency Versions

### Backend (Python 3.11+)

| Package | Version | Source |
|---------|---------|--------|
| fastapi | >=0.100.0 | `pyproject.toml` |
| uvicorn[standard] | >=0.23.0 | `pyproject.toml` |
| pydantic | >=2.0.0 | `pyproject.toml` |
| pydantic-settings | >=2.0.0 | `pyproject.toml` |
| sqlalchemy | >=2.0.0 | `pyproject.toml` |
| alembic | >=1.12.0 | `pyproject.toml` |
| psycopg[binary] | >=3.1.0 | `pyproject.toml` |
| httpx | >=0.24.0 | `pyproject.toml` |
| python-multipart | >=0.0.6 | `pyproject.toml` |
| pyjwt | >=2.8.0 | `pyproject.toml` |
| jwcrypto | >=1.5.0 | `pyproject.toml` |

### Frontend (Node.js 22+)

| Package | Version | Source |
|---------|---------|--------|
| react | ^19.2.0 | `package.json` |
| react-dom | ^19.2.0 | `package.json` |
| react-router-dom | ^6.30.1 | `package.json` |
| @tanstack/react-query | ^5.90.2 | `package.json` |
| vite | ^7.1.9 | `package.json` |
| typescript | ~5.9.3 | `package.json` |
| @radix-ui/* | Various (^1.1.x, ^2.1.x, ^2.2.x) | `package.json` |
| class-variance-authority | ^0.7.1 | `package.json` |
| tailwindcss | ^3.4.18 | `package.json` |
| zod | ^4.1.12 | `package.json` |
| playwright | ^1.56.0 | `package.json` (dev) |
| vitest | ^3.2.4 | `package.json` (dev) |
| eslint | ^9.37.0 | `package.json` (dev) |

---

## 5. Build Versions

| Component | Version | Source |
|-----------|---------|--------|
| **API** | `0.1.0` | `pyproject.toml` |
| **Frontend** | `1.0.0` | `package.json` |
| **API Project Name** | `identitytwin-api` | `pyproject.toml` |
| **Frontend Project Name** | `identitytwin-console` | `package.json` |

---

## 6. Environment Configuration

### Current `.env.example` (Development Defaults)

```ini
ENVIRONMENT=development
ALLOW_DEV_AUTH=true
DEV_AUTH_TOKEN=

DATABASE_URL=sqlite:///./identitytwin_dev.db
HONEY_DB_URL=

PAYMENT_PROVIDER=mock
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com

CANARY_HMAC_SECRET=
EVIDENCE_HMAC_KEY=

AI_INVESTIGATION_ENABLED=true
AI_LLM_ENABLED=false
...
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### Production Requirements (from `Settings.validate_production_guards`)

| Setting | Production Requirement |
|---------|------------------------|
| `ENVIRONMENT` | `production` |
| `ALLOW_DEV_AUTH` | `false` (enforced) |
| `DATABASE_URL` | PostgreSQL (SQLite rejected) |
| `OIDC_ISSUER_URL` | Required, HTTPS |
| `OIDC_AUDIENCE` | Required |
| `CANARY_HMAC_SECRET` | ≥32 chars, high entropy (enforced) |
| `EVIDENCE_HMAC_KEY` | ≥32 chars, high entropy (enforced) |
| `PAYMENT_PROVIDER` | `paypal_sandbox` (mock rejected unless `PAYMENT_PROVIDER_PRODUCTION_MOCK_OVERRIDE=true`) |
| `PAYPAL_WEBHOOK_ID` | Required when `PAYMENT_PROVIDER=paypal_sandbox` |
| `CORS_ORIGINS` | Restrictive, explicit origins only |

---

## 7. Staging Deployment Version

| Attribute | Value |
|-----------|-------|
| **Staging Deployed SHA** | Not deployed in this session |
| **Staging Environment** | Not verified in this session |
| **Previous Staging Verdict** | `STAGING VERIFIED — PRODUCTION SIGN-OFF PENDING` (from `STAGING_VERIFICATION_REPORT.md`) |

---

## 8. Outstanding Changes Analysis

### Changes That Belong in Release Candidate ✅

1. **Migration 018 idempotency** — Required for production database deployment
2. **Honey API security fixes** — Canary inspection limits, secret redaction, cross-session reuse logging
3. **Canary cross-session reuse protection** — Prevents attacker from isolating victim session
4. **Evidence query service** — Full hash-chain verification + tenant isolation
5. **Frontend refactoring** — Button variants extraction, auth types extraction, SSE session change fix
6. **E2E test update** — Uses seeded known canary secret
7. **Demo seed script** — Seeds known canary for E2E

### Changes That Do NOT Belong in Release Candidate ❌

1. **Report files** (`FINAL_RELEASE_REPORT.md`, `INTEGRATION_AUDIT_FINAL_REPORT.md`, `P4_COMPLETION_REPORT.md`, `REMEDIATION_COMPLETION_REPORT.md`, `STAGING_VERIFICATION_REPORT.md`) — Documentation artifacts
2. **Any uncommitted local configuration** — None detected

---

## 9. Reproducibility Assessment

| Criterion | Status | Notes |
|-----------|--------|-------|
| **Git commit pinned** | ✅ | SHA `63a3a9d935f0c4b36469d68f40e10bb9496284ff` |
| **Dependency lockfiles** | ✅ | `pyproject.toml` (backend), `package-lock.json` (frontend) |
| **Database migrations** | ✅ | Alembic versions 001-019, head at 019 |
| **Build scripts** | ✅ | `npm run build` (frontend), `pip install -e .` (backend) |
| **Test commands** | ✅ | `pytest`, `npm run typecheck`, `npm run lint`, `npm run test`, `npm run test:e2e` |
| **Environment config** | ⚠️ | Production requires secret manager values; `.env.example` documents schema only |
| **Uncommitted changes** | ⚠️ | 13 modified files must be committed; 2 new files must be added |

**Verdict:** Release candidate is **reproducible** once the 13 modified + 2 new files are committed. The 5 report files should be excluded (added to `.gitignore` or left untracked).

---

## 10. Required Actions Before Freeze

1. **Commit all 13 modified files + 2 new files** to establish the exact release candidate
2. **Tag the commit** (e.g., `rc-20261107-63a3a9d`)
3. **Verify clean working tree** after commit
4. **Run full regression** against the tagged commit

---

*This baseline establishes the exact code, configuration, and dependency state that will be verified through all subsequent phases.*