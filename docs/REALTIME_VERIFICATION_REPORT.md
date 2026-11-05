# IdentityTwin Real-Time Verification Report

**Run date:** 2026-11-04 (UTC)  
**Environment:** running IdentityTwin development Docker stack; authenticated development merchant; mock payout adapter.

## Result

Authenticated, tenant-scoped domain events are durably persisted and replayed in order. The browser reconnected after an API restart, replayed stored events, and automatically refreshed payout/risk stream cards, the payout ledger, and overview metrics/activity while those views were open.

**Full real-time behavior is not claimed.** Live browser updates for session detail, incidents, vaccination, evidence, and analyst workflow pages were not independently exercised in this run. PayPal Sandbox payout and live LLM narrative also remain blocked by external configuration; neither is represented as successful.

## Live verification

1. Kept the authenticated merchant overview open and submitted four distinct `$1.00 USD` payouts through `POST /v1/payouts` for the established NORMAL session `22222222-2222-2222-2222-222222222222`, using the controlled synthetic `.example` recipient `payroll@lumen.example`. All four returned HTTP 200, `completed`, risk 27, `ALLOW`, `PROVIDER_MOCK`, and `is_duplicate=false`.
2. PostgreSQL persisted each business change with ordered tenant event IDs. The first two payouts produced events 1–8: `risk.decision`, `payout.changed` (pending), `session.changed`, and `payout.changed` (completed) per payout. The browser rendered the risk and payout events and advanced its displayed cursor.
3. While the payout ledger was open, a new mock payout appeared in the ledger without a page reload.
4. While the overview was open, the payout count initially remained stale because the query's date-range end was frozen at mount. The range is now recalculated on each query execution. After deploying the fix, the live count advanced from 27 to 28 after a further payout; recent activity, the risk histogram, and stream cards also updated without reload.
5. Restarted only the API and confirmed it returned healthy. The browser reconnected automatically. To verify missed-event recovery, moved the test cursor back to 4, reopened the overview, and observed persisted events 5–8 replayed from PostgreSQL; the frontend cursor advanced to 8. This cursor adjustment was a test of recovery from a stale client cursor, not an auth or tenant-isolation bypass.
6. Earlier in the acceptance run, two synthetic containment drills were also displayed on the already-open dashboard. No real attacker, production account, or real-money provider was involved.

The four distinct payout requests each invoked only the mock adapter once; their synthetic provider references and decisions were persisted. The event outbox contains no recipient address, credentials, idempotency key, or provider reference.

## Status ledger

| Check | Status | Evidence |
|---|---|---|
| Authenticated connection and tenant isolation | **PASS** | Live merchant browser connected; backend regression tests require authentication and assert events for another merchant are not returned. |
| Durable event persistence and ordered replay | **PASS** | PostgreSQL event IDs 1–8 survived an API restart; backend tests verify replay from `Last-Event-ID` and ordered events. |
| Reconnect and recovery from a stale cursor | **PASS** | After API health recovery, the browser replayed IDs 5–8 from cursor 4 and advanced to 8. |
| Payout/risk event delivery | **PASS (live verified)** | Browser displayed `risk.decision`, `session.changed`, and `payout.changed`; cursor advanced to 16 by the final live payout. |
| Overview metrics and activity synchronization | **PASS (live verified after fix)** | An open dashboard's payout count advanced 27→28 and recent activity changed without reload. |
| Payout ledger synchronization | **PASS (live verified)** | New payout row appeared in the already-open ledger without reload. |
| Other event classes and detail-page rendering | **BLOCKED (not independently live-verified)** | Source emits incident, vaccination, evidence, investigation, analyst workflow, behavioral, and session events with corresponding frontend invalidations. This run did not independently verify every page's rendered update. |
| All advertised behavior is fully real-time | **NOT IMPLEMENTED / NOT CLAIMED** | The requested per-surface independent live acceptance is incomplete; the evidence supports only the verified subsets above. |
| PayPal Sandbox payout / LLM narrative | **BLOCKED** | No controlled Sandbox receiver or enabled live LLM configuration was present. |

## Automated validation

- Backend full suite: **645 passed** (including event authentication, merchant isolation, ordering, rollback, and database replay tests).
- Frontend unit suite: **20 passed** across 7 files, including large-ID precision, duplicate handling, reconnect cursor recovery, and moving analytics-window tests.
- Playwright E2E suite: **12 passed**.
- Frontend type-check/build: **passed**. Targeted ESLint on modified overview files: **0 errors, 0 warnings**.

The API and console were healthy after deployment. No PayPal payout or live LLM request was made.
