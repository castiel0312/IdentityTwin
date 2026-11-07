# REALTIME SSE IMPLEMENTATION

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This document is the implementation specification derived from the audit.

---

## 1. Unified SSE gateway

Existing endpoint `GET /v1/events/stream` (files `apps/api/app/api/routes/events.py`, `apps/api/app/honey/events.py`) is the foundation. It is upgraded to a unified gateway:

- **Authenticated connection:** Bearer token / OIDC JWT validated by `get_current_principal`; dev tokens in development. Connection rejected 401/403 without a valid principal.
- **Tenant-scoped subscription:** Stream filtered to `principal.merchant_id` server-side. Client-supplied tenant/session identifiers are never trusted for authorization.
- **Session-scoped filtering where applicable:** `session_id` included in event payloads; clients filter client-side. Optional server-side session filter may be added via query parameter validated against ownership.
- **Server-side authorization:** Merchant scope resolved from authenticated identity and server-side ownership records only.
- **Event IDs:** Every SSE message carries `id: <event_id>` (per-merchant monotonic).
- **Last-Event-ID support:** Both `Last-Event-ID` header and `after_event_id` query param (existing behavior) enable durable replay after reconnect.
- **Durable replay:** Events replayed from the `domain_events` outbox (30-day retention), not from memory. `stream.reset` signals `cursor_ahead` or `retention_gap`.
- **Heartbeat:** `: keep-alive\n\n` every 15 s (existing); tunable.
- **Disconnect detection:** `request.is_disconnected()` loop exit; connection resources cleaned up.
- **Graceful cleanup:** DB session and cursors released on disconnect or shutdown.
- **Reconnection support:** Client resumes with `Last-Event-ID`; server replays from `after_event_id`.
- **Backpressure handling:** Starlette/FastAPI `StreamingResponse` generator; slow clients are handled by the async generator backpressure.
- **Connection limits:** Configurable max concurrent SSE connections per tenant and globally; 429 when exceeded.
- **Rate limiting:** Existing rate-limit middleware applies; SSE endpoints included with appropriate limits.
- **Safe serialization:** JSON `data:` payload with safe-field whitelist; no secrets, tokens, credentials.
- **Structured logging:** JSON logs with correlation IDs; no auth tokens or payment data logged.
- **Correlation IDs:** `correlation_id` in event data where available; request IDs logged per SSE session.

---

## 2. Connection lifecycle

1. **Authenticate the client:** Validate bearer token; resolve `AuthenticatedPrincipal`.
2. **Resolve authorized tenant and session scope:** `tenant_id = principal.merchant_id`; optional session filter validated by ownership.
3. **Establish the event cursor:** From `Last-Event-ID` header or `after_event_id` query param; default `0`.
4. **Replay missed events:** Stream retained `domain_events` with `event_id > cursor`, ordered ascending.
5. **Subscribe to new events:** After replay, switch to live feed via `LISTEN/NOTIFY` wake-up on new committed events for the tenant.
6. **Maintain event ordering:** Strict `event_id` ascending order within the tenant stream.
7. **Send heartbeats:** Periodic `: keep-alive` to keep idle connections open.
8. **Detect disconnects:** Exit generator on `request.is_disconnected()`.
9. **Clean up subscription resources:** Close DB session, unsubscribe listener, release cursors.
10. **Support reconnect and replay:** Client presents last received `event_id`; server replays from that cursor.

### Replay / live race condition

Prevent loss or duplication during connection establishment:

- **Deduplication by event ID:** Client maintains a `seen` set of `event_id`s received in this session; duplicates are ignored.
- **Cursor established before live subscription:** The replay cursor (`lastEventId`) is captured and persisted (sessionStorage) before switching to live delivery.
- **Overlap handling:** Events replayed that the client already has are deduped by ID; new live events continue from `max(replay_max_id, cursor)`.
- **No gap:** The dispatcher's `NOTIFY` wake-up and the outbox's immutable append-only nature ensure an event committed during reconnect is retained and delivered on replay.

---

## 3. Event serialization over SSE

Each message (existing `StreamMessage.as_sse` pattern, standardized to the event catalog envelope):

```
id: <sequence>
event: <event_type>
data: {"event_id":..., "event_type":..., "event_version":..., "tenant_id":..., "session_id":..., "aggregate_type":..., "aggregate_id":..., "sequence":..., "occurred_at":..., "correlation_id":..., "data":{...}, "schema_version":...}

```

Blank line terminates each message. Heartbeat: `: keep-alive\n\n`. Reset: `event: stream.reset` with `data` containing `reason` (`cursor_ahead` | `retention_gap`) and current/oldest event IDs.

---

## 4. Security

- Client cannot choose `tenant_id`: derived from `AuthenticatedPrincipal.merchant_id` after token validation.
- Cross-tenant subscription impossible: every read from `domain_events` includes `WHERE merchant_id = :merchant_id`.
- `Last-Event-ID` is validated as a numeric cursor within range; invalid → 400.
- No auth tokens, payment credentials, canary secrets, or internal evidence in payloads.
- Structured logs exclude `Authorization` headers and request bodies.

---

## 5. Observability (SSE layer)

Logged per connection: connection opened/closed, tenant (hashed/merchant-scoped, not raw sensitive values), events sent, replay count, disconnect reason, errors, reconnect attempts. Metrics: active SSE connections, connection failures, replay counts, replay lag (latest event_id − cursor delivered).
