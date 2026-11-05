# IdentityTwin Real-Time Implementation Report

**Updated:** 2026-11-04  
**Environment:** development Docker stack; controlled development merchant; mock payouts only.

## Status summary

| Status | Result |
|---|---|
| **PASS** | Durable, authenticated, tenant-scoped outbox events with per-merchant ordering, replay, reconnect recovery after API restart, and 30-day retention. |
| **PASS** | Live payout/risk events, overview metrics/activity, and payout-ledger refresh observed in the authenticated browser without manual reload. |
| **PASS** | API event tests cover authentication, merchant isolation, ordering, transactional rollback, and database replay. Frontend tests cover ID precision, duplicate handling, and cursor recovery. |
| **FAIL — fixed and reverified** | The overview query reused a frozen time-window end, so an SSE-triggered refetch omitted newer payouts. The range is now recalculated on every fetch; a live open dashboard advanced from 27 to 28 payouts without reload. |
| **BLOCKED** | Live UI updates for session detail, incidents, vaccination, evidence, and analyst workflow pages were not independently exercised. |
| **BLOCKED** | Genuine PayPal Sandbox payout requires a user-controlled Sandbox receiver. Live LLM narrative requires approved provider configuration. Neither was attempted without prerequisites. |
| **NOT IMPLEMENTED** | A durable per-payout provider-attempt counter/ledger is not available; provider call counts remain corroborated by mock/honey provenance and gateway outcomes rather than an independent durable metric. |
| **NOT IMPLEMENTED** | A full-product “fully real-time” acceptance claim is not supported until every advertised live update path is independently verified. |

## Implementation delivered

- Database-backed domain-event rows and per-merchant cursors are written atomically with allowlisted business changes.
- Events cover behavioral activity, risk decisions, sessions, payouts, incidents, vaccination signatures/matches, evidence entries/seals, investigations, analyst actions, and intent profiles.
- Authenticated SSE replay reads only the authorized merchant's records, preserves decimal event IDs, handles reconnect cursors and retention gaps, and survives API restarts.
- Events are retained for 30 days; frontend cursor storage is tenant-keyed and non-secret.
- The frontend deduplicates replayed IDs and invalidates matching React Query families. A stream reset invalidates active cached data.
- The overview recalculates its bounded analytics range each time the query runs, so live invalidation includes records created after the page mounted.
- LLM settings are passed from Compose only when configured; egress is limited to the exact configured HTTPS hostname. LLM use remains disabled unless explicitly configured.

## Live verification

Four controlled `$1.00 USD` requests to the existing NORMAL development session and synthetic recipient returned HTTP 200, `completed`, risk 27, `ALLOW`, `PROVIDER_MOCK`, and `is_duplicate=false`. Each invoked the mock adapter once and produced a persisted synthetic reference.

While the authenticated overview was open, the browser received `risk.decision`, `session.changed`, and `payout.changed` events. The payout ledger showed a new row without reload. After the analytics-range fix, a later payout changed the live overview count from 27 to 28 and refreshed recent activity. PostgreSQL event IDs 1–8 survived an API restart; after reconnecting with a test cursor at 4, the browser replayed events 5–8 and advanced to 8. The event cursor later advanced to 16 during the remaining live payout checks.

These observations verify the payout/risk subset and earlier synthetic containment display only. They do not prove every event type's corresponding page updates in the browser.

## Regression results

- Backend full suite: **645 passed**.
- Frontend unit suite: **20 passed**.
- Playwright E2E: **12 passed**.
- Frontend type-check/build: **passed**.
- Targeted ESLint on modified overview files: **0 errors, 0 warnings**.

## Required follow-up before claiming full real-time

1. Keep the appropriate session, incident, vaccination, evidence, and analyst views open while triggering each controlled supported change; verify the event, persisted record, and actual rendered update independently.
2. Verify retention-gap reset behavior and reconnect recovery in the browser under the documented 30-day policy.
3. Configure an approved Sandbox receiver before attempting a genuine PayPal Sandbox payout.
4. Configure an approved LLM endpoint, model, and secret through the supported environment settings before testing a generated narrative.
5. Add a durable provider-attempt ledger only if independent per-request provider-call counts are required for acceptance.

No real-money payout, production identity, authentication bypass, or policy-threshold change was used.
