# REALTIME DEPLOYMENT GUIDE

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This guide describes how the implementation should be deployed safely.

---

## 1. Migration assessment

**Preferred approach:** Reuse the existing durable event/outbox schema from migration `019_durable_domain_events` (`domain_events`, `domain_event_cursors`). No schema change is strictly required to begin event production because the existing SQLAlchemy listeners already write outbox rows atomically.

**New migration only if required:** Adding `delivery_status`, `delivery_attempts`, `last_attempt_at`, `last_error` to `domain_events` (or a separate `domain_event_delivery` table) for dispatcher delivery tracking. This must be:

- Backward-compatible (additive columns with defaults).
- Tested: upgrade, downgrade (where supported), fresh install, existing-database upgrade.
- Migration history preserved (Alembic linear chain after `019`).

---

## 2. Feature flags

Use feature flags to roll out incrementally:

| Flag | Default | Purpose |
|---|---|---|
| `realtime.event.dispatcher` | off | Enables the outbox dispatcher and delivery tracking |
| `realtime.sse.gateway` | off | Enables the unified SSE gateway (replaces/augments existing stream) |
| `realtime.frontend.modules` | off | Enables per-module `useRealtimeEvent` subscriptions |
| `realtime.honey.producers` | off | Enables honey canary trigger/reuse producers |
| `realtime.agentic.producers` | off | Enables agentic commerce grant/reservation/limit producers |

Flags allow each phase to be enabled/disabled without redeploy.

---

## 3. Incremental rollout order

1. **Backend event production** — add explicit producers for uncovered operations (agentic commerce, reconciliation jobs, honey canary events, gateway policy change, auth lifecycle). Verify outbox atomicity.
2. **Reliable dispatch** — add dispatcher with atomic claiming, retry + backoff + jitter, dead-letter, stale-claim recovery, graceful shutdown. Verify multi-instance safety.
3. **SSE delivery** — upgrade `/v1/events/stream` to the unified gateway (LISTEN/NOTIFY wake-up, Last-Event-ID replay, heartbeat, disconnect cleanup, connection limits, rate limiting).
4. **Frontend event infrastructure** — shared SSE client, subscription manager, `useRealtimeEvent`, `RealtimeStatus`, typed events, runtime validation, dedup, ordering, cursor persistence, reconnection.
5. **Individual module integration** — connect Dashboard, Identity, Trust, Risk, Gateway, Honey, Evidence, Incidents, Payments, Agentic commerce, Reconciliation per the module coverage matrix.
6. **Observability** — metrics and logs for events created/published/pending/latency/failures/retries/dead-letter, SSE connections/failures/reconnects/replay lag, authorization rejections.
7. **End-to-end verification** — run the 14 Playwright scenarios and load tests in staging.

---

## 4. Backward compatibility and rollback

- Existing API contracts unchanged (`GET /v1/events/stream`, `POST /v1/events`, all REST routes).
- Existing SSE clients continue to work; `Last-Event-ID` and `after_event_id` semantics preserved.
- Event envelope is additive: new fields can be added without breaking consumers.
- Rollback: disable feature flags; the existing outbox and stream remain operational. Downgrade migration only if new columns were added and downgrade is supported.

---

## 5. Multi-instance deployment

- Multiple API instances: each runs its own SSE endpoint; outbox is shared PostgreSQL (single source of truth).
- Multiple worker/dispatcher instances: atomic claiming with `SKIP LOCKED` semantics prevents double processing; stale-claim recovery handles crashes.
- PostgreSQL `LISTEN/NOTIFY` is per-database; with multiple instances, ensure each instance listens to its tenant channels and the dispatcher notifies after commit.
- No Redis unless PostgreSQL-based wake-up cannot meet p95 targets under load.
