# REALTIME TEST REPORT

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed and no tests were executed during this audit. This report inventories existing tests, specifies the test plan, and records results as "not executed" pending implementation.

---

## 1. Existing backend test inventory

File: `apps/api/tests/`

Relevant to real-time architecture:
- `test_events.py` — event ingestion, ownership mismatch, nonexistent session, future timestamp, unbounded metadata.
- `test_payouts.py`, `test_paypal_provider.py` — payout execution and provider behavior.
- `test_reconciliation_worker.py` — reconciliation worker cycles.
- `test_gateway.py`, `test_gateway_routing.py` — gateway decisions.
- `test_incidents_and_stubs.py`, `test_investigations.py` — incidents/investigations.
- `test_honey/` and `test_canary_secret_config.py` — honey/canary behavior.
- `test_sessions.py`, `test_authorization.py`, `test_oidc_auth.py` — auth/session security.
- `test_security_audit.py`, `test_no_bypass.py`, `test_integration_attack_replay.py` — security.
- `test_hardening_readiness.py`, `test_read_models.py` — readiness/read models.
- `conftest.py` — fixtures including `client`, `merchant_auth_headers`, `other_merchant_auth_headers`, `NORMAL_SESSION_ID`.

Existing tests confirm: outbox-backed event ingestion works, tenant ownership is enforced, and idempotency prevents double counting. No tests exist for SSE delivery, event dispatch, replay, multi-instance fan-out, or frontend real-time behavior.

---

## 2. Backend test plan (to be implemented)

| Area | Cases |
|---|---|
| Event producers | Every event in the catalog fires on the corresponding state transition; no event on no-op transitions |
| Transaction rollback | Outbox event rolled back when business transaction rolls back |
| Outbox atomicity | Business state and outbox row visible together after commit; never separately |
| Worker concurrency | Multiple dispatcher instances do not double-publish the same event (atomic claiming) |
| Retry | Failed publishes retry with backoff + jitter; respect max retry |
| Duplicate processing | Replay of the same event ID produces no duplicate UI state |
| Replay | `Last-Event-ID` / `after_event_id` returns all retained events after cursor |
| Event ordering | Events delivered in ascending `event_id` per tenant |
| SSE authentication | 401 without token; 403 for cross-tenant subscription attempts |
| Tenant filtering | Tenant A never receives Tenant B's events |
| Session filtering | Session-scoped payloads respect ownership |
| Multi-instance fan-out | Two API + two worker instances deliver all committed events |
| Disconnect cleanup | SSE resources released on client disconnect; reconnect resumes |

---

## 3. Frontend test plan (to be implemented)

| Area | Cases |
|---|---|
| SSE connection | Connects with bearer token; reconnects on stream end |
| Event parsing | SSE block parsing; invalid JSON skipped safely |
| Subscription lifecycle | `useRealtimeEvent` subscribes/unsubscribes; no duplicate listeners |
| React cleanup | No timers/listeners after unmount; no setState-in-effect warnings |
| Reconnection | Exponential backoff + jitter; cursor restored from sessionStorage |
| Cache update | Targeted TanStack Query update/invalidation on event |
| Duplicate events | Dedup by `event_id`; no duplicate timeline entries |
| Out-of-order events | Reject `sequence <= last_processed` |
| Stale event rejection | Older events do not overwrite newer state |
| UI update | Component re-renders with live data without refresh |
| Tenant switching | New tenant cursor; old connection torn down |
| Logout cleanup | Stream torn down; cursors cleared; `queryClient.clear()` |

---

## 4. End-to-end Playwright scenarios (to be implemented)

Use separate authenticated test accounts and tenants. No mock events to claim real provider integration.

1. User creates a gateway event; another authorized browser (same tenant) sees it without refreshing.
2. New risk alert appears on the dashboard without refresh.
3. Honey interaction appears immediately on the honey dashboard.
4. Canary trigger appears immediately.
5. New evidence appears in the evidence timeline.
6. New incident appears immediately.
7. Payout status changes after authoritative provider update (reconciliation), not on request submission.
8. Reconciliation completion appears immediately.
9. Spending reservation updates the correct agentic-commerce UI.
10. Backend restart is followed by successful client reconnection and replay.
11. Missed events are replayed after reconnection (Last-Event-ID).
12. Duplicate events do not create duplicate UI records.
13. Unauthorized tenants never receive each other's events (two tenants, separate browsers).
14. Multiple browser tabs receive consistent updates (single logical connection per tenant session; tab isolation respected).

---

## 5. Load test plan (staging only)

Evaluate before execution; establish limits:
- Concurrent SSE connections (target: hundreds per tenant instance).
- Event bursts (events/sec) and publication latency p95.
- Worker throughput (reconciliation jobs/sec).
- Database connection usage under connection load.
- Replay performance for large backlogs.
- Memory consumption over sustained connection time.

No load testing of production without authorization.

---

## 6. Test results

All test categories: **not executed** (no code changed during this audit). Results to be recorded here during implementation and verification.
