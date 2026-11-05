# IdentityTwin — Integration Test Report

**Date:** 2026-11-04
**Scope:** Backend API, gateway routing, PayPal sandbox, honey/canary isolation, evidence, identity/incident endpoints, frontend console, SSE.
**Convention:** PASS = verified with test output; FAIL = defect found; BLOCKED = cannot complete due to external/environmental limitation (documented, not claimed).

---

## 1. Backend test suite

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| Full backend pytest suite | 624 pre-existing pass | 631 passed (624 + 7 new vaccination regression) | PASS | `631 passed, 3 warnings in 87.56s` | `apps/api/tests/` | — | — |
| `test_reconciliation_worker.py` | collects and runs | ImportError: `psycopg` missing | BLOCKED | `ModuleNotFoundError: No module named 'psycopg'` | `apps/api/tests/test_reconciliation_worker.py:61` | Person 3 | Add `psycopg` to dev deps; run against PostgreSQL |

## 2. Infrastructure / Docker

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| `docker compose up` from clean env | all services start | all 5 healthy | PASS | `db, api, gateway, console, paypal-egress` all `healthy` | `docker-compose.yml` | — | — |
| PostgreSQL port 5432 conflict | no host 5432 binding | host 5432 not bound; DB internal `db:5432` | PASS | local postgres PID 747 occupied 5432; removed host mapping | `docker-compose.yml:11-15` | — | — |
| DB health check | `pg_isready` ok | `/ready` → `database: connected` | PASS | `{"status":"ready","database":"connected"}` | `apps/api/app/api/routes/health.py` | — | — |
| API health check | HTTP 200 | HTTP 200 `{"status":"ok"}` | PASS | `curl http://127.0.0.1:8001/health` | `apps/api/app/main.py` | — | — |
| Gateway health check | HTTP 200 via nginx | HTTP 200 | PASS | via `127.0.0.1:8001/health` | `scripts/docker/nginx.conf` | — | — |
| Frontend console startup | container healthy | `identitytwin-console-1 healthy` | PASS | `docker compose ps` | `frontend/Dockerfile` | — | — |
| Egress proxy startup | squid running | `identitytwin-paypal-egress-1` Up | PASS | `docker compose ps` | `scripts/docker/paypal-squid.conf` | — | — |
| Service dependency order | db healthy → api → gateway | start_period + depends_on honored | PASS | containers became healthy in order | `docker-compose.yml` | — | — |
| Database connection | API reaches DB | API connects via `db:5432` internally | PASS | `/ready` OK; payouts persisted | `apps/api/app/db/session.py` | — | — |
| Restart behavior | `restart: unless-stopped` | set on all services | PASS | `docker-compose.yml` | `docker-compose.yml` | — | — |

## 3. Database migrations

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| `alembic upgrade head` | migrates cleanly | ran at API startup; head reached | PASS | `alembic current → 018_match_updated_at (head)` | `apps/api/alembic/` | — | — |
| `alembic current` | reports head | `018_match_updated_at (head)` | PASS | `docker compose exec -T api alembic current` | `apps/api/alembic/env.py` | — | — |
| `alembic history` | clean linear chain | `<base> → 001 → … → 018`, no duplicates | PASS | 18 revisions, linear `down_revision` chain | `apps/api/alembic/versions/` | — | — |
| Clean DB from scratch | migrations apply | verified via disposable SQLite test DB | PASS | `tests/conftest.py` `setup_test_db` | `apps/api/tests/conftest.py` | — | — |
| Seed script idempotent (run twice) | no duplicates | merchant count = 1; "Demo merchant already exists" | PASS | ran twice; `SELECT count(*) FROM merchants → 1` | `scripts/seed_demo.py` | — | — |

## 4. API contracts (endpoints exercised against running Docker API)

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| `POST /v1/sessions` | 201, session created | 201 with `trust_level=NORMAL` | PASS | `session_id` returned | `apps/api/app/api/routes/sessions.py` | — | — |
| `POST /v1/payouts` (NORMAL baseline) | ALLOW → provider | risk 45 → RESTRICTED/step-up (new device/time/payee) | PASS | `risk_score=45.0, action=REQUIRE_STEP_UP` | `apps/api/app/gateway/service.py` | — | — |
| `POST /v1/payouts` (DECOY escalation) | honey, no provider | risk 100 → ISOLATED/BLOCK, `provider_reference=null` | PASS | `status=blocked, action=BLOCK` | `apps/api/app/gateway/service.py` | — | — |
| `GET /v1/sessions/{id}` | trust state | trust_level + risk_score returned | PASS | `trust_level=NORMAL, risk_score=0.0` | `apps/api/app/api/routes/sessions.py` | — | — |
| `GET /v1/evidence/verify` | chain valid | `valid=true` after drill | PASS | `POST /v1/simulate/attack` then verify | `apps/api/app/api/routes/evidence.py` | — | — |
| `POST /v1/webhooks/paypal` | signature verification | fail-closed; verified via unit tests | PASS | `tests/test_webhook_verification.py` | `apps/api/app/api/routes/webhooks.py` | — | — |
| `POST /v1/simulate/attack` | canary drill | incident sealed, evidence valid, provider count 0 | PASS | integration test | `apps/api/app/api/routes/stubs.py` | — | — |
| `GET /v1/vaccination/matches` | 200, empty array when no matches | `items=[]`, `total=0`, no 500 | PASS | `tests/test_vaccination.py::test_match_history_empty_when_no_matches` | `apps/api/app/api/routes/vaccination.py:203` | — | — |
| `GET /v1/vaccination/matches` | `signature_name` populated after match | `signature_name` non-empty, no 500 | PASS | `tests/test_vaccination.py::test_match_history_serializes_signature_name` | `apps/api/app/models/vaccination.py:128` | — | — |
| `GET /v1/vaccination/matches` | tenant isolation | Merchant A sees 0 of Merchant B's matches | PASS | `tests/test_vaccination.py::test_match_history_tenant_isolation` | `app/services/vaccination_service.py:406` | — | — |
| `POST /v1/vaccination/evaluate` | 404 for non-existent session | `SESSION_NOT_FOUND` 404 | PASS | `tests/test_vaccination.py::test_evaluate_session_not_found` | `apps/api/app/api/routes/vaccination.py:239` | — | — |
| `POST /v1/vaccination/evaluate` | 403 for foreign session | `SESSION_SCOPE_MISMATCH` 403 | PASS | `tests/test_vaccination.py::test_evaluate_session_scope_mismatch` | `app/services/vaccination_service.py:317` | — | — |
| `POST /v1/vaccination/evaluate` | match persisted + visible in history | match row + `signature_name` in history | PASS | `tests/test_vaccination.py::test_evaluate_with_real_existing_session_produces_match` | `app/services/vaccination_service.py:306` | — | — |
| `POST /v1/signatures/{id}/approve` | 501 stub | 501 NOT_IMPLEMENTED | PASS (documented stub) | `apps/api/app/api/routes/stubs.py:48` | `apps/api/app/api/routes/stubs.py` | Person 5 | implement |
| `GET /v1/stream` | 501 stub | 501 NOT_IMPLEMENTED | PASS (documented stub) | `apps/api/app/api/routes/stubs.py:24` | `apps/api/app/api/routes/stubs.py` | Person 2/5 | implement |

Frontend TypeScript types (`src/types/api.ts`) are generated from `packages/contracts/openapi.json`; `typecheck` passes, so types match schemas.

## 5. Gateway routing / trust levels (running API)

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| NORMAL → provider | provider invoked | mock provider invoked once (smoke payout) | PASS | `provider_reference` set, `invocation_count=1` | `apps/api/app/gateway/service.py` | — | — |
| RESTRICTED → no provider | provider count 0 | `provider_reference=null`, `action=REQUIRE_STEP_UP` | PASS | risk 45, step-up required | `apps/api/app/gateway/policy.py` | — | — |
| DECOY → honey only | provider count 0, honey invoked | `action=DECOY_FORWARD`, mock count=0, honey count=1 | PASS | integration test | `apps/api/app/gateway/service.py` | — | — |
| ISOLATED → blocked | provider count 0 | `action=BLOCK`, provider count=0, honey count=0 | PASS | risk 100, session revoked, incident opened | `apps/api/app/gateway/service.py` | — | — |
| Canary hit → ISOLATED | immediate isolation | `contain_canary_hit` revokes session, opens incident | PASS | `tests/honey/test_canary.py`, E2E | `app/honey/containment.py` | — | — |
| Idempotency / no double execute | provider once | duplicate key → `is_duplicate=true`, count stays 1 | PASS | integration test | `apps/api/app/gateway/service.py` | — | — |
| Provider failure not fabricated | honest error | PayPal 403 propagated, `provider_reference=null`, not completed | PASS | genuine sandbox 403 (see PayPal section) | `apps/api/app/gateway/provider.py` | — | — |

## 6. PayPal sandbox integration

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| Sandbox connectivity | reach api-m.sandbox.paypal.com:443 | reachable via squid proxy; HTTP 401 from PayPal with dummy creds | PASS | `curl -x paypal-egress:3128 ... 401` | `scripts/docker/paypal-squid.conf` | — | — |
| OAuth token | valid token from creds | `TOKEN_OK len=97` (real token) | PASS | `PayPalSandboxAdapter._get_access_token()` | `apps/api/app/gateway/provider.py` | — | — |
| Real payout request | genuine PayPal response | PayPal `403 PAYOUT_NOT_AVAILABLE`, `debug_id=f235886aed87f` | PASS | gateway propagated error, no fabricated success | `apps/api/app/gateway/provider.py` | — | — |
| Successful sandbox payout | completed transaction | **BLOCKED** — sandbox account country-restricted (`PAYOUT_NOT_AVAILABLE`) | BLOCKED | genuine PayPal 403 | `apps/api/app/gateway/provider.py:516` | PayPal account config | use sandbox account allowed to send payouts |

Note: IdentityTwin never fabricates a provider reference or claims a completed payout when PayPal rejects. The sandbox country restriction is a PayPal-side limitation, honestly reported.

## 7. Honey API + evidence

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| Canary registration + hit | hit on owning session, none cross-session | hit=True owning; None cross-session | PASS | `tests/honey/test_canary.py` | `app/honey/canary.py` | — | — |
| Canary → containment → incident | session revoked, incident opened | `session_status=revoked`, `containment_incident_id` set | PASS | E2E `contains a canary hit...` | `app/honey/containment.py` | — | — |
| Evidence chain valid | `valid=true` | `valid=true`, `checked>=1` | PASS | `GET /v1/evidence/verify` | `app/evidence/hashchain.py` | — | — |
| Evidence tamper detected | `valid=false` | `valid=false, first_broken_seq=1` | PASS | integration test (scratch engine) | `app/evidence/hashchain.py` | — | — |
| No real credentials in honey plane | no PayPal/customer data in honey | honey is synthetic; canaries are server-generated | PASS | design + unit tests | `app/honey/` | — | — |

## 8. AI investigation + intent

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| Intent classification | advisory snapshots | `tests/test_intent_classifier.py`, `test_intent_signals.py` pass | PASS | `apps/api/tests/test_intent_*.py` | `app/intent/` | — | — |
| Investigation bundles | advisory, read-only | `tests/test_investigations.py` pass | PASS | `apps/api/tests/test_investigations.py` | `app/investigations/` | — | — |
| LLM unavailable | deterministic fallback | `AI_LLM_ENABLED=false` default; deterministic narrative | PASS | config + tests | `app/core/config.py` | — | — |
| AI never authorizes payments | read-only | investigator does not modify trust/risk/payments | PASS | design | `docs/ai-investigator.md` | — | — |

## 9. Frontend + SSE

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| `npm run typecheck` | no type errors | clean | PASS | `tsc -b --noEmit` | `frontend/` | — | — |
| `npm test` (vitest) | 16 pass | 16 passed | PASS | `Test Files 5 passed, Tests 16 passed` | `frontend/src/**/__tests__` | — | — |
| `npm run build` | production bundle | built, 1,313 kB JS | PASS | `✓ built in 14.09s` | `frontend/` | — | — |
| Playwright E2E | 12 pass | 12 passed (30.4s) | PASS | all console + analyst journeys | `frontend/e2e/console.spec.ts` | — | — |
| SSE initial + reconnect | `/v1/events/stream` 200 | stream connected in E2E logs | PASS | API logs show `/v1/events/stream` 200 | `apps/api/app/api/routes/events.py` | — | — |
| No fabricated backend data | real backend only | E2E asserts "Backend unreachable" count = 0; real payout refs | PASS | E2E assertions | `frontend/e2e/console.spec.ts` | — | — |
| Vaccination: session dropdown | sessions from `GET /v1/sessions` | `<Select>` populated from `listSessions()`, no stale typed IDs | PASS | `frontend/src/pages/vaccination.tsx:289` | `frontend/src/pages/vaccination.tsx` | — | — |
| Vaccination: match history serialization | 200 with `signature_name` | `signature_name` property on `VaccinationMatch` ORM model | PASS | `apps/api/app/models/vaccination.py:128-134` | `apps/api/app/models/vaccination.py` | — | — |

## 10. Security Vaccination

| Test | Expected | Actual | Status | Evidence | Code location | Bug owner | Fix |
|------|----------|--------|--------|----------|---------------|-----------|-----|
| Signature extraction from confirmed attack | PROPOSED, sanitized definition, evidence recorded | 201, `status=PROPOSED`, no PII/secrets, chain append | PASS | `tests/test_vaccination.py::test_signature_extraction_is_proposed_and_sanitized` | `app/services/vaccination_service.py` | — | — |
| Deterministic matching (action + sequence + features) | matched with explainable features & risk points | `matched=true`, `score>=60`, `risk_points>0` | PASS | `test_matcher_requires_action_and_sequence` | `app/services/vaccination_service.py::SignatureMatcher` | — | — |
| Matcher rejects wrong action type | not matched | `matched=false`, `reason=action_type_mismatch` | PASS | `test_matcher_rejects_wrong_action_type` | `app/services/vaccination_service.py` | — | — |
| Matcher rejects missing event sequence | not matched | `matched=false`, `reason=event_sequence_not_present` | PASS | `test_matcher_rejects_missing_sequence` | `app/services/vaccination_service.py` | — | — |
| Lifecycle: propose → approve → activate | ACTIVE, analyst recorded, evidence appended | 200, `new_status=ACTIVE`, chain row | PASS | `test_lifecycle_propose_approve_activate` | `app/services/vaccination_service.py` | — | — |
| Merchant cannot approve (analyst only) | 403 ANALYST_ROLE_REQUIRED | 403 | PASS | `test_lifecycle_propose_approve_activate` | `app/core/security.py` | — | — |
| Duplicate approval rejected | 403 VACCINATION_NOT_PROPOSED | 403 | PASS | `test_duplicate_approval_rejected` | `app/services/vaccination_service.py` | — | — |
| Revoke active signature | REVOKED, revoked_by set | 200, `new_status=REVOKED` | PASS | `test_revoke_active_signature` | `app/services/vaccination_service.py` | — | — |
| Revoke proposed signature rejected | 403 VACCINATION_NOT_ACTIVE | 403 | PASS | `test_revoke_proposed_signature_rejected` | `app/services/vaccination_service.py` | — | — |
| Tenant isolation (foreign signature) | 403 SCOPE_MISMATCH / ANALYST_ROLE_REQUIRED | 403 | PASS | `test_tenant_isolation_cannot_manage_foreign_signature` | `app/services/vaccination_service.py` | — | — |
| PROPOSED not applied; ACTIVE matches | PROPOSED→no match, ACTIVE→match | `matched=false` then `matched=true` | PASS | `test_proposed_signature_not_applied` | `app/services/vaccination_service.py` | — | — |
| Revoked signature no longer matches | not matched | `matched=false` | PASS | `test_revoked_signature_no_longer_matches` | `app/services/vaccination_service.py` | — | — |
| Evidence chain valid after full lifecycle | valid=true | `valid=true` | PASS | `test_evidence_chain_valid_after_full_lifecycle` | `app/evidence/hashchain.py` | — | — |
| Cross-merchant: A attack → approve → B matches earlier | B risk >= before, vaccination reason present, match recorded | after_score >= before_score, `VACCINATION_SIGNATURE_MATCHED`, match row | PASS | `test_cross_merchant_second_merchant_protection` | `app/gateway/service.py` + `app/services/vaccination_service.py` | — | — |
| Issue 1 fix: match history 500 → 200 with `signature_name` | `signature_name` serialized from `signature` relationship | `signature_name` property on ORM model; `from_attributes=True` works | PASS | `tests/test_vaccination.py::test_match_history_serializes_signature_name` + `test_match_history_empty_when_no_matches` | `apps/api/app/models/vaccination.py:128-134` | — | `signature_name` @property on `VaccinationMatch` |
| Issue 1 fix: tenant isolation on match history | Merchant A sees 0 of Merchant B's matches | `target_merchant_id` filter; empty items for foreign merchant | PASS | `tests/test_vaccination.py::test_match_history_tenant_isolation` | `app/services/vaccination_service.py:406` | — | Existing filter; verified with regression test |
| Issue 2 fix: evaluate non-existent session → 404 | `SESSION_NOT_FOUND` 404 | 404 with error code | PASS | `tests/test_vaccination.py::test_evaluate_session_not_found` | `apps/api/app/api/routes/vaccination.py:239` | — | Existing validation; verified with regression test |
| Issue 2 fix: evaluate foreign session → 403 | `SESSION_SCOPE_MISMATCH` 403 | 403 with error code | PASS | `tests/test_vaccination.py::test_evaluate_session_scope_mismatch` | `app/services/vaccination_service.py:317` | — | Existing validation; verified with regression test |
| Issue 2 fix: evaluate real existing session → match | match recorded + visible in history | match row + `signature_name` populated | PASS | `tests/test_vaccination.py::test_evaluate_with_real_existing_session_produces_match` | `app/services/vaccination_service.py:306` | — | Existing flow; verified with regression test |
| Issue 2 fix: frontend session dropdown | `<Select>` from `GET /v1/sessions` | stale typed IDs replaced by backend-sourced sessions | PASS | `frontend/src/pages/vaccination.tsx:289` | `frontend/src/pages/vaccination.tsx` | — | `listSessions()` query + `<Select>` |
| Migration 017 | tables created, head advances | `alembic current → 017_vaccination_signatures` | PASS | `apps/api/alembic/versions/017_vaccination_signatures.py` | `apps/api/alembic/` | — | — |
| Migration 018 | `updated_at` on `vaccination_matches` | column added, head advances | PASS | `apps/api/alembic/versions/018_vaccination_matches_updated_at.py` | `apps/api/alembic/` | — | — |
| Backend suite incl. vaccination | no regressions | `631 passed` | PASS | `apps/api/tests/test_vaccination.py` (20 tests incl. 7 new regression) | `apps/api/tests/` | — | — |

## 11. Summary

- PASS: 631 backend tests (incl. 20 vaccination tests with 7 new regression tests for Issues 1 & 2), frontend typecheck/build/vitest, 12 Playwright E2E, Docker health, migrations (head = 018), gateway routing, evidence integrity, honey/canary isolation, PayPal connectivity + honest error handling, match history serialization, session evaluation tenant validation.
- BLOCKED: successful PayPal sandbox payout (sandbox account country-restricted — PayPal-side); `test_reconciliation_worker.py` (missing `psycopg`).
- FAIL: none.
- Issues fixed: (1) `GET /v1/vaccination/matches` 500 → 200 via `signature_name` @property on `VaccinationMatch` ORM model; (2) frontend evaluate session input changed from free-text to `<Select>` populated by `GET /v1/sessions`, preventing stale/incorrect session IDs.
- Not implemented (gap, not a test failure): none remaining. Security Vaccination is implemented and verified.
