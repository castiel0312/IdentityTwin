# IdentityTwin — Security Test Report

**Date:** 2026-11-04
**Focus:** Trust Gateway authorization boundary, PayPal routing isolation, honey/decoy confinement, canary containment, evidence integrity, idempotency, idempotency/replay, session ownership.
**Verdict:** No security bypass found. All routing invariants verified. One honest limitation: the PayPal sandbox account is country-restricted, so a *completed* sandbox payout could not be demonstrated (PayPal-side, not an IdentityTwin bypass).

---

## 1. Trust Gateway — authorization boundary

Every protected payout flows through `POST /v1/payouts` → `TrustGatewayService.execute_payout`. No route handler invokes a provider adapter directly.

| Invariant | Test | Result | Evidence | Location |
|-----------|------|--------|--------|----------|
| Session ownership enforced | foreign merchant session | `SESSION_OWNERSHIP_MISMATCH` 403, provider count 0 | unit + integration | `app/gateway/service.py:127` |
| Active session required | revoked/expired session | `INACTIVE_SESSION`, provider count 0 | unit | `app/gateway/service.py:133` |
| Unknown session | not found | `SESSION_NOT_FOUND`, provider count 0 | unit | `app/gateway/service.py:120` |
| Direct provider call from frontend | frontend never calls provider | frontend routes `/v1/payouts` through gateway; no provider SDK in frontend | PASS (design + E2E) | `frontend/` |
| Gateway is authorization boundary | protected action bypass | all payout paths go through `execute_payout` | PASS | `app/gateway/service.py:44` |

## 2. Trust-level routing isolation (provider invocation count asserted)

| Level | Expected routing | Provider invoked? | Honey invoked? | Result | Evidence |
|-------|-----------------|-------------------|----------------|--------|----------|
| NORMAL (0–29) | configured provider | Yes (mock) | No | PASS | `tests/test_gateway_routing.py::test_normal_request_may_call_the_configured_provider` |
| RESTRICTED (30–59) | step-up required / $500 cap | No | No | PASS | `test_restricted_request_cannot_call_paypal` (stub PayPalTransport: `stub.requests == []`) |
| DECOY (60–89) | honey only | No | Yes | PASS | `test_decoy_request_uses_only_the_honey_adapter` + integration test (mock count 0, honey count 1) |
| ISOLATED (90–100 or canary) | blocked | No | No | PASS | `test_isolated_request_is_blocked_without_provider_execution` |

End-to-end against the running Docker API:
- Fresh session payout → risk 45 → RESTRICTED → `REQUIRE_STEP_UP`, `provider_reference=null`.
- DECOY-seeded session + new payee + large payout → risk 100 → ISOLATED → `BLOCK`, `provider_reference=null`, session revoked, incident opened.
- Canary hit (via `POST /v1/simulate/attack`) → containment, session revoked, incident sealed, evidence valid, provider count 0.

## 3. PayPal sandbox routing safety

| Invariant | Result | Evidence |
|-----------|--------|----------|
| No real provider call at Level 2 (DECOY) | PASS | `stub.requests == []`; `provider.invocations == []` |
| No real provider call at Level 3 (ISOLATED) | PASS | `stub.requests == []` |
| Provider failure never fabricated as success | PASS | PayPal genuine `403 PAYOUT_NOT_AVAILABLE` propagated; `provider_reference=null`; payout not completed |
| Sandbox-only base URL | PASS | allowlist `api-m.sandbox.paypal.com`; production/lookalike abort startup |
| Unknown provider value | PASS | aborts startup, no silent mock fallback |
| Egress restricted to sandbox | PASS | squid proxy permits only `api-m.sandbox.paypal.com:443` |

## 4. Canary isolation

| Invariant | Result | Evidence |
|-----------|--------|----------|
| Canary hit forces Level 3 | PASS | `detect_canary` → `TrustLevel.ISOLATED` regardless of score |
| Canary is session-scoped | PASS | canary issued for session A cannot trigger on session B (`test_canary_cannot_be_used_across_sessions`) |
| Canary disarmed after hit | PASS | second `reg.check` returns None |
| Canary → containment + incident | PASS | `contain_canary_hit` revokes session, opens CRITICAL/OPEN incident |
| E2E: cross-session canary reveal → 403; owning session → revoked | PASS | Playwright `contains a canary hit only in its owning session` |

## 5. Replay / idempotency / concurrency

| Invariant | Result | Evidence |
|-----------|--------|----------|
| Replayed idempotency key not re-executed | PASS | duplicate key → `is_duplicate=true`, provider invoked once |
| Conflicting payload on key reuse | PASS | `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`, provider count stays 1 |
| In-flight key refused | PASS | `IDEMPOTENCY_IN_PROGRESS` 409 |
| Definitive provider failure → safe retry | PASS | key marked `failed`, retry allowed |
| Ambiguous provider timeout → reconciliation, no blind retry | PASS | key marked `provider_executed`, retry rejected |
| Concurrent requests vs stale trust state | covered by row-level lock (`for_update=True`) on session | `app/gateway/service.py:120` |

## 6. Evidence hash-chain integrity

| Invariant | Result | Evidence |
|-----------|--------|----------|
| Valid sequence verifies | PASS | `EvidenceChain.verify()` → `valid=true` |
| Tampered payload detected | PASS | `valid=false, first_broken_seq=1` |
| Tampered prev_hash detected | PASS | `reason=prev_hash_mismatch` |
| Deleted middle entry detected | PASS | `reason=sequence_gap` |
| Deleted tail vs checkpoint | PASS | `reason=head_checkpoint_mismatch` |
| Append-only guards (SQLite) | PASS | `evidence records are append-only` trigger |
| No claim of external immutability | documented | E2E asserts "not proof of immutability or independent custody" |

## 7. AI Investigator boundaries

| Invariant | Result | Evidence |
|-----------|--------|----------|
| AI does not authorize payments | PASS | read-only advisory; never modifies routing/risk/trust/payments |
| AI does not modify trust levels | PASS | design |
| AI does not create fake evidence refs | PASS | every evidence ID validated against persisted evidence |
| AI does not claim honey payout = real PayPal payout | PASS | synthetic-only |
| AI does not independently revoke credentials | PASS | no such capability |
| LLM unavailable → deterministic fallback | PASS | `AI_LLM_ENABLED=false` default |

## 8. Security Vaccination — authorization and routing safety

| Invariant | Result | Evidence | Location |
|-----------|--------|----------|----------|
| Analyst-only approval | PASS | merchant (non-analyst) → 403 `ANALYST_ROLE_REQUIRED` | `app/services/vaccination_service.py::_require_analyst` |
| PROPOSED not applied before approval | PASS | evaluate returns `matched=false` for PROPOSED signature | `app/services/vaccination_service.py::evaluate` |
| Only ACTIVE signatures match | PASS | ACTIVE → match recorded; PROPOSED/REVOKED → no match | `app/services/vaccination_service.py::evaluate` |
| Revoked signature no longer matches | PASS | `matched=false` after revoke | `tests/test_vaccination.py::test_revoked_signature_no_longer_matches` |
| Duplicate approval rejected | PASS | 403 `VACCINATION_NOT_PROPOSED` | `tests/test_vaccination.py::test_duplicate_approval_rejected` |
| Tenant isolation (signature mgmt) | PASS | foreign merchant → 403 `VACCINATION_SCOPE_MISMATCH` | `app/services/vaccination_service.py::_get_signature` |
| Match does not bypass Trust Gateway | PASS | match adds `VACCINATION_MATCH` risk signal; gateway enforces final trust level | `app/gateway/service.py::execute_payout` |
| Match never independently authorizes payment | PASS | provider invocation still gated by trust level; vaccination only raises score | `app/gateway/service.py` |
| Signature definition sanitized (no secrets/PII) | PASS | no password/token/paypal/customer PII in definition | `app/services/vaccination_service.py::_build_definition` |
| Evidence chain valid after lifecycle | PASS | `valid=true` after create/approve/revoke | `tests/test_vaccination.py::test_evidence_chain_valid_after_full_lifecycle` |
| Match history serializes `signature_name` without 500 | PASS | `signature_name` @property on `VaccinationMatch` ORM model; `from_attributes=True` works | `apps/api/app/models/vaccination.py:128-134` |
| Match history tenant isolation | PASS | `target_merchant_id` filter; Merchant A sees 0 of Merchant B's matches | `app/services/vaccination_service.py:406` |
| Session evaluation validates tenant scope | PASS | `SESSION_SCOPE_MISMATCH` 403 for foreign session; `SESSION_NOT_FOUND` 404 for unknown | `app/services/vaccination_service.py:317` |
| Frontend session selection uses backend sessions | PASS | `<Select>` populated by `GET /v1/sessions`; no stale typed IDs | `frontend/src/pages/vaccination.tsx:289` |

## 9. Honest limitations (not bypasses)

- **Successful PayPal sandbox payout not demonstrated:** the sandbox account is country-restricted (`PAYOUT_NOT_AVAILABLE`, genuine PayPal 403, `debug_id=f235886aed87f`). IdentityTwin correctly reports the rejection honestly; this is a PayPal account-configuration limitation, not a routing bypass. A sandbox account permitted to send payouts is required to complete this criterion.
- Host DB port not published (internal network by design); DB accessed via `db:5432`.

## 10. Security verdict

**PASS** — the Trust Gateway enforces its authorization boundary; DECOY and ISOLATED requests never reach the payment provider; canary hits force isolation; idempotency prevents double execution; provider failures are honestly reported; evidence integrity is hash-chain verified; match history serializes correctly without 500; session evaluation validates tenant scope with clear errors. The only unmet criterion (a *completed* sandbox payout) is blocked by the PayPal sandbox account's country restriction and is documented, not concealed.
