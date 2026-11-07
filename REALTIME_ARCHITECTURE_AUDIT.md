# REALTIME ARCHITECTURE AUDIT

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Migration head:** `019_durable_domain_events`  
**Audit scope:** Full backend event architecture and all frontend modules  
**Constraint honored:** No code was changed during this audit.

---

## 1. Executive summary

IdentityTwin already has a durable, tenant-scoped domain-event outbox (`domain_events` table, migration `019_durable_domain_events`) and an authenticated SSE endpoint (`GET /v1/events/stream`) backed by that outbox. A React SSE client (`useContainmentStream` in `frontend/src/lib/sse.ts`) exists and is mounted globally in `AppShell`.

The gap is **coverage, not absence**:

- The SSE client is only **consumed by the Overview/Dashboard page** (`LiveDomainEventStream`).
- Every other page (Payouts, Incidents, Risk, Honey, Evidence, Sessions, Identities, Agents, Vaccination, and their detail pages) loads data once on entry via TanStack Query and relies on **manual Refresh buttons** or **initial page-load fetching only**.
- The Overview page additionally uses a **60-second fixed-interval poll** (`refetchInterval: 60_000`) for analytics.
- There is **no event dispatcher, no event claiming, no retry, and no dead-letter queue** for event delivery; the SSE stream polls the outbox table directly every 500 ms.
- There is **no shared `useRealtimeEvent` hook**, no per-module event subscription manager, and no connection-status surface beyond the Overview live-stream badge.

Verdict for the current codebase: **PARTIALLY REAL-TIME**. The durable event backbone exists; live delivery reaches only one surface.

---

## 2. Backend event architecture audit

### 2.1 Domain event definitions

File: `apps/api/app/services/domain_events.py`  
File: `apps/api/app/models/domain_event.py`  
Migration: `apps/api/alembic/versions/019_durable_domain_events.py`

The outbox is populated **automatically by SQLAlchemy ORM session listeners** (`before_flush` captures changes; `after_flush_postexec` writes outbox rows). There are no explicit producer calls in service code.

| Tracked table | Domain event type | Aggregate | Notes |
|---|---|---|---|
| `security_events` | `behavioral.event` | behavioral_event | New behavioral/security signal ingested |
| `risk_decisions` | `risk.decision` | risk_decision | Gateway risk decision persisted |
| `payout_requests` | `payout.changed` | payout_request | Payout created or status changed |
| `sessions` | `session.changed` | session | Session created, trust/risk state changed, revoked |
| `incidents` | `incident.changed` | incident | Incident created or status changed |
| `vaccination_matches` | `vaccination.match` | vaccination_match | Canary/vaccination signature match |
| `vaccination_signatures` | `vaccination.signature` | vaccination_signature | Signature created/actioned |
| `evidence_log` | `evidence.appended` | evidence_log | Evidence appended to chain |
| `incident_seals` | `evidence.sealed` | incident_seal | Evidence seal written |
| `investigations` | `investigation.changed` | investigation | Investigation created/updated |
| `analyst_actions` | `analyst.workflow` | analyst_action | Analyst incident action |
| `intent_profiles` | `analyst.workflow` | intent_profile | Intent profile created/updated |

Event payload includes: `schema_version` (1), `entity_type`, `entity_id`, `session_id`, `operation` (created/updated/deleted), `incident_id` when present, and a whitelist of "safe fields" per table (e.g. payout status/provider_name, risk score/trust_level/action/routing_destination, session status/risk_score/trust_level, incident status/severity). No secrets, payment credentials, canary secrets, or tokens are included.

### 2.2 Event persistence (outbox)

Table: `domain_events` (`merchant_id`, `event_id` PK, `event_type`, `entity_type`, `entity_id`, `operation`, `payload` JSON, `created_at`).  
Cursor table: `domain_event_cursors` (`merchant_id` PK, `last_event_id`).

- Per-merchant **monotonic `event_id`** cursor, incremented inside the same transaction as the business change (`_increment_cursor`).
- Outbox rows are written in `after_flush_postexec`, i.e. within the **same database transaction** as the business state change. No event is persisted for an uncommitted change.
- 30-day retention via `prune_expired_domain_events` (runs every 6 hours and at startup).

### 2.3 Event producer

There is **no explicit producer service**. Production is implicit: any ORM insert/update/delete on a tracked table emits a domain event at flush/commit time. This means:

- Operations that mutate tracked tables through SQLAlchemy sessions produce events automatically (payout creation/status change, session trust updates, incident status changes, risk decision persistence, evidence appends/seals, investigation updates, session revocation).
- Operations that bypass the ORM or write only to the **honey database** (`honey_events`, canary records, honey workspace state) do **not** produce domain events. Canary trigger, decoy interaction, honey isolation, and cross-session canary reuse are written to evidence/incident tables (which ARE tracked), but the honey-specific interaction itself is not a domain event.

### 2.4 Event dispatcher

**None exists.** The SSE stream reads the outbox table directly (`stream_domain_events` in `apps/api/app/honey/events.py`). There is:
- No claiming mechanism for events.
- No dedicated dispatcher process/worker.
- No retry logic for delivery failures.
- No dead-letter queue.
- No delivery-status tracking per subscriber.

### 2.5 Event worker

The only background worker is `ReconciliationWorker` (`apps/api/app/gateway/reconciliation_worker.py`), which reconciles payouts against the provider. It is **not an event-dispatch worker**. It does use:
- `SELECT ... FOR UPDATE SKIP LOCKED` claiming (multi-instance safe).
- Exponential backoff retry (`30s * 2^(attempt-1)`, capped 1 hour), max 10 attempts, then escalation.
- Stale-claim recovery (`RECONCILIATION_CLAIM_TIMEOUT_SECONDS = 300`).
- Graceful shutdown (15s stop timeout).

### 2.6 Event claiming / retry / dead-letter / stale claim

Not implemented for the domain-event outbox. Delivery reliability currently relies on the SSE client polling the outbox and reconnecting; committed events are never "lost" from the outbox, but there is no acknowledgment, retry, or dead-letter handling for SSE delivery.

### 2.7 Event status transitions

Outbox rows are immutable inserts; there is no `delivery_status` column. Status transitions exist only on business aggregates (payout status, incident status, session status).

### 2.8 Replay API

`GET /v1/events/stream` supports:
- `after_event_id` query parameter and `Last-Event-ID` header.
- Server-side `stream.reset` events for `cursor_ahead` and `retention_gap` (30-day retention).
- Replay from any retained cursor.

### 2.9 SSE endpoint

File: `apps/api/app/api/routes/events.py` + `apps/api/app/honey/events.py`.

- Authenticated via `get_current_principal` (Bearer token / OIDC JWT in prod; dev tokens in dev).
- Tenant scope derived from `principal.merchant_id` — **never trusted from the client**.
- Poll interval 500 ms; heartbeat every 15 s (`: keep-alive`).
- Detects disconnect via `request.is_disconnected()`.
- Media type `text/event-stream`, headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- Each SSE message: `id: <event_id>\nevent: <event_type>\ndata: <json>\n\n`.

### 2.10 Authentication

`apps/api/app/core/security.py`:
- `AuthenticatedPrincipal` (user_id, merchant_id, role, username, auth_method) resolved server-side from Bearer token.
- Production: OIDC/JWT via JWKS. Development: fixed dev tokens; `X-Dev-*` header overrides allowed only after a valid dev token.
- `validate_merchant_scope` enforces tenant ownership.

### 2.11 Tenant filtering

All outbox reads are filtered by `merchant_id == principal.merchant_id`. A client cannot subscribe to another tenant's stream because the merchant ID is resolved server-side from the authenticated principal.

### 2.12 Session filtering

SSE stream is tenant-scoped, not session-scoped. Event payloads include `session_id` where applicable, allowing clients to filter client-side. No server-side session-scoped SSE subscription exists.

### 2.13 Event serialization

JSON payload in `domain_events.payload`; serialized to SSE `data:` field with `sort_keys=True`, compact separators. Event ID is the numeric `event_id`.

### 2.14 Event versioning

`schema_version: 1` is hardcoded in payloads. `event_version` envelope field does not exist as a separate top-level concept. No version migration path documented.

---

## 3. Frontend event architecture audit

### 3.1 SSE client

File: `frontend/src/lib/sse.ts` (`useContainmentStream`).

- Authenticated: sends `Authorization: Bearer <session.token>` plus `X-Dev-*` headers.
- Connection: `fetch` to `${API_BASE}/v1/events/stream` with `Accept: text/event-stream`, `cache: no-store`.
- Cursor: `after_event_id` query param + `Last-Event-ID` header; last cursor persisted in `sessionStorage` keyed `identitytwin.domain-events.<merchantId>`.
- Parsing: SSE block parser (`event:`, `id:`, `data:` lines); `stream.reset` handled specially.
- Deduplication: `seenRef` Set of event IDs; cursor only advances on strictly greater IDs (`BigInt` comparison).
- Reconnection: exponential backoff `min(15000, 1000 * 2^retryCount)`, initial 1 s, max 15 s.
- Status states: `idle | connecting | open | reconnecting | unauthorized | error`.
- Query invalidation: `QUERY_KEYS_BY_EVENT` maps event types to Tanstack Query keys to invalidate on receipt.
- Events stored in local state (max 50), newest first.

### 3.2 Connection lifecycle

Mounted once in `AppShell` (`frontend/src/components/layout/app-shell.tsx`) via `useContainmentStream(Boolean(session), session)` and passed to every route through `<Outlet context={stream}>`. Connection starts when a session exists; torn down when session becomes null (effect cleanup aborts the controller). Reconnect on stream end with backoff.

### 3.3 Event listeners / consumers

Only `OverviewPage` (`frontend/src/pages/overview.tsx`) consumes the stream, through `LiveDomainEventStream` (`frontend/src/features/overview/live-stream.tsx`), which renders the last 6 events and a status badge. No other page subscribes to SSE events.

### 3.4 Data-fetching / cache layer

TanStack Query (`frontend/src/lib/query.ts`): `retry: false`, `refetchOnWindowFocus: false`, `staleTime: 10_000`. Every page owns its own `useQuery` calls with manual `query.refetch()` Refresh buttons. No global invalidation on SSE events outside the overview's event-type→query-key map (and even that map is only wired to the overview stream).

### 3.5 Component subscriptions

None beyond the single global `useContainmentStream` in AppShell + `LiveDomainEventStream` in Overview. No `useRealtimeEvent` hook exists.

### 3.6 Dashboard refresh mechanisms

Overview uses:
- TanStack Query for analytics (`refetchInterval: 60_000` — fixed-interval polling).
- Live SSE stream for recent domain events.
- Manual Refresh button.

### 3.7 Manual refresh buttons

Present on every page (Payouts, Incidents, Risk, Honey, Evidence, Sessions, Identities, Agents, detail pages). All rely on `query.refetch()` or `queryClient.invalidateQueries()`.

### 3.8 Polling intervals

- Overview analytics: 60,000 ms fixed interval (rule 5 violation if used as primary real-time mechanism).
- SSE stream: 500 ms outbox poll (server-side durable polling, not application polling, but still polling rather than push/wake-up).

### 3.9 Query invalidation

Manual only. `QUERY_KEYS_BY_EVENT` exists in sse.ts but is only active where the stream is consumed (Overview).

### 3.10 Notification handling

No dedicated notification center. Recent activity shown on Overview from the analytics snapshot (not live). SSE event list on Overview is the only live notification surface.

---

## 4. Per-module audit

For each module: Current data source | Current update mechanism | Event producer | Event type | Event delivery mechanism | Frontend consumer | Missing functionality | Required implementation.

### 4.1 Dashboard / Overview

- **Current data source:** `GET /v1/analytics/overview` (TanStack Query, `refetchInterval: 60s`) + SSE outbox stream.
- **Current update mechanism:** Periodic refetch + live stream events shown in a side card; metrics do not update live from events.
- **Event producer:** SQLAlchemy listeners on tracked tables (incidents, payouts, sessions, risk_decisions, evidence, investigations).
- **Event types:** `incident.changed`, `payout.changed`, `session.changed`, `risk.decision`, `evidence.appended`, `investigation.changed`, `analyst.workflow`.
- **Event delivery:** SSE `GET /v1/events/stream`, consumed by `LiveDomainEventStream`.
- **Frontend consumer:** `OverviewPage` / `LiveDomainEventStream`.
- **Missing:** Summary metrics, activity timeline, trust/risk summaries, and alerts do not update live; 60s polling used instead of event-driven invalidation.
- **Required:** Invalidate overview query keys on relevant live events; update metrics/timeline/alerts from events; remove fixed-interval polling as the primary mechanism.

### 4.2 Identity / Sessions / Behavioural identity

- **Current data source:** `GET /v1/sessions`, `GET /v1/identities`, `GET /v1/sessions/{id}/activity` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial page-load fetch only; Refresh button.
- **Event producer:** SQLAlchemy listeners on `sessions` and `security_events` tables.
- **Event types:** `session.changed`, `behavioral.event`.
- **Event delivery:** SSE available but not consumed by these pages.
- **Frontend consumer:** None (SSE not wired).
- **Missing:** New signals, profile status, session revocation/trust changes do not appear live.
- **Required:** Subscribe to `session.changed` and `behavioral.event`; update session rows, trust badges, risk meters live.

### 4.3 Payouts / Payments

- **Current data source:** `GET /v1/payouts`, `GET /v1/payouts/{id}` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial load; Refresh. Payout status changes occur via `POST /v1/payouts` and the reconciliation worker.
- **Event producer:** SQLAlchemy listener on `payout_requests` (`payout.changed`) on insert/status update.
- **Event types:** `payout.changed`.
- **Event delivery:** SSE available but not consumed by payout pages.
- **Frontend consumer:** None.
- **Missing:** Payout status transitions (pending → completed/failed/denied/reconciled) not reflected live; no distinction between provider-confirmed and ambiguous outcomes.
- **Required:** Subscribe to `payout.changed`; update payout ledger rows and detail view; never mark complete from request submission alone — only from authoritative provider state via reconciliation.

### 4.4 Risk

- **Current data source:** `GET /v1/risk/config`, `GET /v1/risk/decisions` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial load; Refresh.
- **Event producer:** SQLAlchemy listener on `risk_decisions` (`risk.decision`).
- **Event types:** `risk.decision`.
- **Event delivery:** SSE available but not consumed.
- **Frontend consumer:** None.
- **Missing:** New risk decisions and risk-level changes not live.
- **Required:** Subscribe to `risk.decision`; append new decision rows; update severity bands live.

### 4.5 Gateway (ALLOW / BLOCK / DECOY / ISOLATED)

- **Current data source:** Risk decisions + payouts (TanStack Query).
- **Current update mechanism:** Initial load; Refresh.
- **Event producer:** `risk_decisions` listener (`risk.decision`) covers decisions; gateway policy changes produce no explicit event.
- **Event types:** `risk.decision` (decision); no `gateway.policy.change` event exists.
- **Event delivery:** SSE available but not consumed.
- **Frontend consumer:** None.
- **Missing:** New ALLOW/BLOCK/DECOY/ISOLATED decisions not live; no gateway policy change event.
- **Required:** Subscribe to `risk.decision`; add `gateway.policy.change` producer for policy changes; update decision statistics.

### 4.6 Honey Workspace / Canary detection

- **Current data source:** `GET /v1/honey/operator/workspaces`, `GET /v1/honey/operator/canaries` (TanStack Query, manual refresh). Honey state lives in a separate honey DB and honey tables — NOT in `domain_events`.
- **Current update mechanism:** Initial load; Refresh.
- **Event producer:** No domain-event producer for honey interactions. Canary trigger writes to `evidence_log` + `incidents` (tracked → `evidence.appended` / `incident.changed` fire), and isolation writes to `sessions` (`session.changed`), but there is no dedicated `honey.interaction` / `canary.triggered` / `canary.reuse` domain event.
- **Event types:** Indirect `evidence.appended`, `incident.changed`, `session.changed` only.
- **Event delivery:** SSE available but not consumed by honey pages.
- **Frontend consumer:** None.
- **Missing:** New decoy interactions, canary triggers, cross-session reuse alerts, isolation state not live.
- **Required:** Add domain-event producers for canary trigger and cross-session reuse; subscribe on honey pages; update canary inventory and workspace cards live.

### 4.7 Evidence chain

- **Current data source:** `GET /v1/evidence/seals`, `POST /v1/evidence/verify` (TanStack Query, manual refresh; verify is on-demand).
- **Current update mechanism:** Initial load; manual verify; Refresh.
- **Event producer:** SQLAlchemy listeners on `evidence_log` (`evidence.appended`) and `incident_seals` (`evidence.sealed`).
- **Event types:** `evidence.appended`, `evidence.sealed`.
- **Event delivery:** SSE available but not consumed.
- **Frontend consumer:** None.
- **Missing:** New evidence entries, seal status, tampering alerts not live; ordering not maintained live.
- **Required:** Subscribe to `evidence.appended` / `evidence.sealed`; append to timeline; maintain ordering by event sequence.

### 4.8 Incidents

- **Current data source:** `GET /v1/incidents`, `GET /v1/incidents/{id}` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial load; Refresh; analyst actions via POST.
- **Event producer:** SQLAlchemy listener on `incidents` (`incident.changed`) for create/status change.
- **Event types:** `incident.changed`.
- **Event delivery:** SSE available but not consumed.
- **Frontend consumer:** None.
- **Missing:** New incidents, status changes, assignments, escalation, resolution not live.
- **Required:** Subscribe to `incident.changed`; add new incidents immediately; update status/assignment/severity; reflect resolution.

### 4.9 Agentic commerce (spending grants/reservations)

- **Current data source:** `GET /v1/agents`, `GET /v1/agents/{id}`, `POST /v1/agentic/payouts` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial load; Refresh.
- **Event producer:** `agents` table is **not** in the `_EVENT_TYPES` map — no domain events for grant creation, reservation, consumption, release, or limit events.
- **Event types:** None exist.
- **Event delivery:** N/A.
- **Frontend consumer:** None.
- **Missing:** Spending totals, reservations, consumed/released spending, limit warnings not live.
- **Required:** Add producers for grant/reservation/consume/release/limit events; subscribe on agent pages; update totals and reservations live.

### 4.10 Reconciliation / workers

- **Current data source:** Payout list with `reconciliation_required` flag (TanStack Query).
- **Current update mechanism:** Initial load; Refresh; worker runs every 300 s internally.
- **Event producer:** No job/event table for reconciliation jobs; no domain events for job claimed/processing/completed/failed.
- **Event types:** None exist.
- **Frontend consumer:** None.
- **Missing:** Job status, worker progress, failures/retries, completed jobs not live.
- **Required:** Add reconciliation job event producers; subscribe; show worker progress live.

### 4.11 Vaccination / signatures / matches

- **Current data source:** `GET /v1/vaccination/...` (TanStack Query, manual refresh).
- **Current update mechanism:** Initial load; Refresh.
- **Event producer:** SQLAlchemy listeners on `vaccination_signatures` / `vaccination_matches` (`vaccination.signature` / `vaccination.match`).
- **Event delivery:** SSE available but not consumed.
- **Frontend consumer:** None.
- **Missing:** New matches/signatures not live.
- **Required:** Subscribe to `vaccination.*` events.

### 4.12 Investigations

- **Current data source:** `GET /v1/incidents/{id}/investigations` (TanStack Query).
- **Event producer:** `investigations` listener (`investigation.changed`).
- **Frontend consumer:** None.
- **Missing:** Investigation updates not live.
- **Required:** Subscribe to `investigation.changed`.

### 4.13 Sessions detail / Identity detail / Payout detail / Risk decision detail / Honey detail / Evidence detail

All detail pages load once via TanStack Query and refresh manually. None subscribes to SSE. Each is missing live updates for its aggregate.

### 4.14 Authentication (login / logout / session)

- Login/session creation writes to `sessions` → `session.changed` fires (via ORM listener). Logout is client-side session clearing (`signOut` in `auth.tsx`) with no server-side revocation event and no SSE cleanup coordination beyond AppShell unmount.
- **Missing:** Login/logout/session-revocation events not exposed as actionable real-time events to other tabs; no logout coordination to tear down SSE across tabs.

---

## 5. Gap analysis (mapped to mandatory rules)

| Rule | Current state | Gap |
|---|---|---|
| 1. Inspect before changing | Done (this audit) | — |
| 2. Preserve security/tenant isolation | SSE scoped to `principal.merchant_id` server-side | Must be preserved in any new delivery path |
| 3. Preserve durable outbox/replay | `domain_events` + cursors + Last-Event-ID exist | Must remain the source of truth |
| 4. No in-memory-only delivery | Outbox is durable PostgreSQL | Preserve |
| 5. No polling as primary architecture | SSE stream polls outbox every 500 ms; Overview polls analytics every 60 s | Replace polling with event-driven/push or PG NOTIFY wake-up |
| 6. No global tenant broadcast | Merchant-scoped reads enforced | Preserve |
| 7. No secrets in payloads | Safe-field whitelist enforced | Preserve |
| 8. No pre-commit events | `after_flush_postexec` runs inside transaction | Preserve |
| 9. No duplicate events | Idempotency keys on payouts/event ingest; dedup by event ID client-side | Extend to all producers |
| 10. No silent drops | Outbox is immutable; SSE client dedups | Add delivery-status tracking/dead-letter |
| 11. No unnecessary WebSocket | SSE only; no WebSocket | Preserve |
| 12. No API contract changes | Existing routes unchanged | Preserve |
| 13. No payment lifecycle change | Gateway semantics unchanged | Preserve |
| 14. Mock vs real provider | Code never treats mock as real | Preserve |
| 15. Frozen RC until authorized | No changes made | N/A (documents only) |
| 16. Migrations only when required | Reuse `019` schema | Avoid new migrations unless unavoidable |
| 17. Test every change | Existing test suite present | Extend tests for new paths |

---

## 6. Conclusion

The durable backbone (outbox, cursors, SSE endpoint, authenticated client, replay) is present and correctly tenant-scoped. What is missing is **coverage and operationalization**:

1. **Backend event production gaps:** agentic commerce (grants/reservations), reconciliation jobs, honey canary triggers/reuse, gateway policy changes, login/logout events — no producers.
2. **No dispatcher/claiming/retry/dead-letter** for outbox delivery.
3. **SSE consumed by only one page** (Overview); every other module relies on manual refresh or initial-load-only fetching.
4. **Fixed-interval polling** on Overview (60 s) contradicts the event-driven objective.
5. **No shared `useRealtimeEvent` hook, subscription manager, or connection-status surface.**

These documents describe the implementation required to close these gaps without changing payment correctness, tenant isolation, or the durable outbox semantics.
