# REALTIME BACKEND IMPLEMENTATION

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This document is the implementation specification derived from the audit.

---

## 1. Design principles (mandatory rules preserved)

1. **Durable outbox is the source of truth.** `domain_events` (PostgreSQL) remains the only durable copy of every event. A notification or broker message is a wake-up/fan-out hint only.
2. **No in-memory-only delivery.** No process-local event bus for cross-instance delivery.
3. **No polling as primary architecture.** Outbox polling by the SSE stream is replaced/supplemented by PostgreSQL `LISTEN/NOTIFY` wake-up (or an admitted broker if required after infrastructure review). Redis is not introduced unless the existing PostgreSQL cannot meet latency targets.
4. **Atomic persistence.** Business state and outbox event are persisted in the same transaction; nothing is published before commit.
5. **No duplicate events.** Idempotency at producer + dedup by `event_id` at consumer.
6. **No silent drops.** Delivery status tracked; dead-letter queue for undeliverable events; retries with backoff + jitter.
7. **Tenant scope server-derived.** `tenant_id`/`merchant_id` always from `AuthenticatedPrincipal`, never from the client.
8. **No secrets in payloads.** Safe-field whitelist preserved.
9. **No WebSocket infrastructure.** SSE remains the transport.
10. **No API contract changes.** Existing routes unchanged.

---

## 2. Schema (reuse migration `019`; new migration only if required)

Existing tables (preserved, backward compatible):

- `domain_events(merchant_id, event_id PK, event_type, entity_type, entity_id, operation, payload JSON, created_at)`
- `domain_event_cursors(merchant_id PK, last_event_id)`

**New migration (only if required):** add a `delivery_status`/`delivery_attempts`/`dead_letter` mechanism to `domain_events`, or a separate `domain_event_delivery` table:

```sql
ALTER TABLE domain_events ADD COLUMN delivery_status VARCHAR(16) DEFAULT 'pending';  -- pending | sent | dead_letter
ALTER TABLE domain_events ADD COLUMN delivery_attempts INTEGER DEFAULT 0;
ALTER TABLE domain_events ADD COLUMN last_attempt_at TIMESTAMPTZ;
ALTER TABLE domain_events ADD COLUMN last_error TEXT;
CREATE INDEX ix_domain_events_delivery_pending ON domain_events(merchant_id, delivery_status, event_id)
  WHERE delivery_status = 'pending';
```

If per-subscriber delivery tracking is needed instead, create `domain_event_delivery(merchant_id, event_id, subscriber, status, attempts, updated_at)` with a unique constraint on `(merchant_id, event_id, subscriber)`. Backward compatible; does not alter existing columns.

---

## 3. Phase C — Event production (every state-changing operation)

### Pattern for every operation

1. Validate the business operation (ownership, policy, idempotency).
2. Perform the state change in a SQLAlchemy session.
3. Persist business state + outbox event atomically in the same transaction (existing `after_flush_postexec` listener, or explicit `DomainEvent` insert within the unit of work).
4. Commit.
5. Dispatcher publishes the committed event (wake-up via `LISTEN/NOTIFY`).
6. Update delivery status (`pending` → `sent` or `dead_letter`).
7. Retry failures safely with backoff + jitter.

**Never** publish an event representing an uncommitted change. **Never** emit an event for a transition that did not occur (compare previous vs new state; skip no-op updates).

### 3.1 Authentication and sessions

| Operation | Event type | Producer location | Notes |
|---|---|---|---|
| User login | `auth.session.created` | Session creation path / explicit emit | tenant_id from principal |
| Logout | `auth.session.revoked` | Explicit emit on server-side revocation (client logout clears local session; server emits on revoke) | No token in payload |
| Session creation | `auth.session.created` | `sessions` ORM listener | Already tracked; refine type |
| Session revocation | `auth.session.revoked` | `isolate_session_and_open_incident` / session status update | Already tracked via `session.changed` |
| Account security change | `auth.session.trust_changed` | `sessions` ORM listener | Trust/risk updates |

### 3.2 Behavioral identity

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| New behavioral signal | `auth.security.event.ingested` | `security_events` ORM listener (`behavioral.event`) | Already tracked |
| Profile update | `identity.profile.updated` | Required new producer on identity projection write | |
| Identity verification result | `identity.verification.result` | Required new producer on step-up verify | |
| Identity state change | `identity.state.changed` | Required new producer on twin status change | |

### 3.3 Trust engine

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Trust score updated | `trust.score.updated` | `sessions` ORM listener | Already tracked |
| Trust decision created | `trust.decision.created` | `risk_decisions` ORM listener (`risk.decision`) | Already tracked |
| Trust threshold crossed | `trust.threshold.crossed` | Required new producer on band transition | Compare previous/new level |
| Identity confidence changed | `trust.confidence.changed` | Required new producer | |

### 3.4 Risk engine

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Risk assessment created | `risk.assessment.created` | `risk_decisions` ORM listener | Already tracked |
| Risk level changed | `risk.level.changed` | Required new producer | |
| Risk alert generated | `risk.alert.generated` | Required new producer on HIGH/CRITICAL | |
| Risk decision updated | `risk.decision.updated` | `risk_decisions` ORM listener | Already tracked |

### 3.5 Gateway

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| ALLOW decision | `gateway.decision.allow` | `risk_decisions` listener + action routing | Already tracked via `risk.decision` |
| BLOCK decision | `gateway.decision.block` | Same | Already tracked |
| DECOY routing | `gateway.decision.decoy` | Same + honey isolation path | Already tracked |
| ISOLATED routing | `gateway.decision.isolated` | Same + `isolate_session_and_open_incident` | Already tracked |
| Gateway policy change | `gateway.policy.changed` | Required new producer on policy/threshold write | |

### 3.6 Honey Workspace / Canary

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Decoy interaction | `honey.interaction` | Required new producer on honey endpoint access | No canary secrets in payload |
| Canary trigger | `honey.canary.triggered` | Required new producer in `CanaryRegistryService.check` hit path | |
| Canary reuse detection | `honey.canary.reuse` | Required new producer in `_log_cross_session_reuse` | |
| Honey alert | `honey.alert` | `incidents` ORM listener | Already tracked |
| Isolation event | `honey.isolation` | `sessions` ORM listener | Already tracked |

### 3.7 Evidence chain

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Evidence appended | `evidence.appended` | `evidence_log` ORM listener | Already tracked |
| Evidence sealed | `evidence.sealed` | `incident_seals` ORM listener | Already tracked |
| Verification completed | `evidence.verify.completed` | Required new producer on `/v1/evidence/verify` | |
| Tampering detected | `evidence.tampering.detected` | Required new producer on chain break | |

### 3.8 Incidents

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Incident created | `incident.created` | `incidents` ORM listener | Already tracked |
| Incident updated | `incident.updated` | `incidents` ORM listener | Already tracked |
| Incident assigned | `incident.assigned` | `analyst_actions` ORM listener (`analyst.workflow`) | Already tracked |
| Incident escalated | `incident.escalated` | `analyst_actions` ORM listener | Already tracked |
| Incident resolved | `incident.resolved` | `incidents` ORM listener | Already tracked |

### 3.9 Payments

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Payout requested | `payout.requested` | `payout_requests` ORM listener | Already tracked |
| Payout submitted | `payout.submitted` | Required new emit after provider call | |
| Provider accepted | `payout.provider.accepted` | Reconciliation / provider SUCCESS path | Authoritative state only |
| Provider rejected | `payout.provider.rejected` | Reconciliation / DENIED path | |
| Payout pending | `payout.pending` | Payout record / reconciliation ambiguous path | |
| Payout completed | `payout.completed` | `payout_requests` listener on completed status | Never from request submission alone |
| Payout failed | `payout.failed` | Same | |
| Payout outcome ambiguous | `payout.outcome.ambiguous` | Required new emit on timeout/unknown | |
| Reconciliation updated payout | `payout.reconciled` | `payout_requests` listener via worker | Already tracked on status change |

Payment lifecycle semantics unchanged. `completed` only on provider-confirmed SUCCESS.

### 3.10 Agentic commerce

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Spending grant created | `agentic.grant.created` | Required new producer on grant issuance | `agents` table not currently tracked |
| Spending reservation created | `agentic.reservation.created` | Required new producer in `reserve_spending_capacity` | |
| Reservation consumed | `agentic.reservation.consumed` | Required new producer on consume | |
| Reservation released | `agentic.reservation.released` | Required new producer on release | |
| Limit approached | `agentic.limit.approached` | Required new producer | |
| Limit reached | `agentic.limit.reached` | Required new producer | |

### 3.11 Reconciliation and workers

| Operation | Event type | Producer | Notes |
|---|---|---|---|
| Job created | `reconciliation.job.created` | Required new producer on queue | |
| Job claimed | `reconciliation.job.claimed` | Required new producer on `FOR UPDATE SKIP LOCKED` claim | |
| Job processing | `reconciliation.job.processing` | Required new producer | |
| Job retried | `reconciliation.job.retried` | Required new producer on backoff retry | |
| Job completed | `reconciliation.job.completed` | Required new producer on resolution | |
| Job failed | `reconciliation.job.failed` | Required new producer on escalation/failure | |

---

## 4. Phase D — Durable event delivery

### 4.1 Dispatcher (new component)

- Reads `domain_events` where `delivery_status = 'pending'` ordered by `merchant_id, event_id`.
- Claims events atomically (`UPDATE ... SET delivery_status = 'sending', delivery_attempts = delivery_attempts + 1 WHERE event_id = X AND delivery_status = 'pending' RETURNING ...`) so multiple dispatcher instances never double-publish.
- Publishes to SSE fan-out channel (PostgreSQL `LISTEN/NOTIFY` per tenant, or broker).
- On successful fan-out: `delivery_status = 'sent'`.
- On failure: increment attempts, schedule retry with exponential backoff + jitter; after `MAX_RETRY_ATTEMPTS` (configurable, default 10): `delivery_status = 'dead_letter'`.
- Dead-letter events are retained and queryable via an admin endpoint; never silently dropped.

### 4.2 Worker concurrency

- Multiple dispatcher instances supported via atomic claiming (`SKIP LOCKED` equivalent on `delivery_status = 'pending'`).
- Worker crash recovery: events claimed but not resolved remain `sending`; a stale-claim reaper resets `sending` → `pending` after `STALE_CLAIM_TIMEOUT` (default 5 min).
- Graceful shutdown: finish in-flight publishes, stop claiming new events, exit within timeout.

### 4.3 Fan-out wake-up

- PostgreSQL `LISTEN` on a per-tenant channel (`identitytwin.events.<merchant_id>`) or a global channel with tenant-filtered payloads.
- Dispatcher `NOTIFY`s after committing a batch of sent events.
- SSE gateway `LISTEN`s to its tenant's channel and pushes to connected clients.
- Fallback: if `LISTEN/NOTIFY` proves insufficient under load, reevaluate introducing a broker; Redis is not the default.

### 4.4 Delivery status tracking

- `pending` → `sending` → `sent` or `dead_letter`.
- `delivery_attempts`, `last_attempt_at`, `last_error` columns for observability.
- Reconciliation script can resurrect `dead_letter` events manually.

---

## 5. Transactional outbox enforcement (existing behavior preserved)

The existing SQLAlchemy listeners in `apps/api/app/services/domain_events.py` already:

- Capture changes in `before_flush`.
- Write `DomainEvent` rows in `after_flush_postexec` within the same transaction.
- Assign monotonic per-merchant `event_id` via `_increment_cursor` inside the transaction.
- Skip no-op updates (`session.is_modified` check).
- Derive `merchant_id` server-side from the object (never client-supplied).
- Use a safe-field whitelist for `payload`.

New explicit producers (agentic commerce, reconciliation jobs, honey canary events, etc.) must follow the same unit-of-work pattern: business insert/update + `DomainEvent` insert + single `db.commit()`.
