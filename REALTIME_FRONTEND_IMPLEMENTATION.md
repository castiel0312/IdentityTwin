# REALTIME FRONTEND IMPLEMENTATION

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This document is the implementation specification derived from the audit.

---

## 1. Shared real-time client architecture

Replace/standardize on a single authenticated SSE connection per application scope (tenant), managed by a shared subscription manager — not ad hoc connections per component.

Existing foundation: `frontend/src/lib/sse.ts` (`useContainmentStream`) and `frontend/src/lib/query.ts` (TanStack Query client). The new layer builds on these.

### Components to standardize

| Component | Responsibility |
|---|---|
| SSE client | One authenticated `EventSource`/`fetch` stream to `/v1/events/stream` per tenant session, with `Authorization` bearer header |
| Subscription manager | Routes incoming events to registered handlers by `event_type`; dedupes by `event_id`; orders by `sequence` |
| Typed event definitions | TypeScript interfaces matching the event catalog envelope |
| Runtime payload validation | Zod-like or manual type guards validating each event before dispatch |
| Event deduplication | `seen` set of `event_id`s per connection; ignores repeats |
| Event ordering | Apply events by ascending `sequence`; reject `sequence <= last_processed` |
| Last-event cursor | Persisted in `sessionStorage` keyed by tenant; restored on reconnect |
| Reconnection | Exponential backoff + jitter (initial 1 s, cap 15 s, matching existing client) |
| Token refresh | On 401, trigger auth refresh/sign-out flow; tear down stream |
| Connection cleanup | Abort controller on unmount, logout, tenant switch |
| React lifecycle integration | Hooks with proper cleanup; no orphaned timers |
| Error boundaries | Stream errors surfaced as connection status, not uncaught exceptions |
| Connection status indicator | `RealtimeStatus` UI |

---

## 2. Status type

```typescript
type RealtimeStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";
```

Do not display "LIVE"/"connected" when the socket is disconnected or data is stale.

---

## 3. Shared hook

```typescript
useRealtimeEvent(
  eventType: string,
  handler: (event: RealtimeEvent) => void
): void
```

- Subscribes `handler` to `eventType` on the shared SSE connection.
- Automatically unsubscribes on unmount.
- No duplicate listeners for the same `(eventType, handler)` pair.
- No stale closures: handler ref pattern or stable callback.
- No `setState` in effect lint regressions: state updates via functional updaters or event handlers outside effects.

---

## 4. Connection lifecycle guarantees

- **No duplicate connections after component remount:** single connection owned by the subscription manager, reference-counted by subscribers.
- **No duplicate event listeners:** handler registered once per event type.
- **No memory leaks:** timers cleared, event listeners removed, AbortController signalled on cleanup.
- **Correct cleanup on logout and tenant switching:** `signOut` clears session, `queryClient.clear()`, tears down SSE, discards cursors; new session establishes a new connection and cursor.
- **Reconnection restores missed changes:** cursor persisted; `Last-Event-ID` sent on reconnect; replay dedupes.

---

## 5. Integration with data-fetching (TanStack Query)

For each event, one of:

1. **Update the relevant cached record** (`queryClient.setQueryData`) — for single-record updates (payout status, incident status, session trust).
2. **Invalidate a specific query** — for list/page changes (new incident, new payout, new risk decision). Never invalidate the whole cache.
3. **Fetch an authoritative snapshot** — after payment reconciliation events, fetch the payout detail from the server.
4. **Append to a timeline** — for evidence, incidents, activity streams; dedupe by ID; order by `occurred_at`/`sequence`.

Never overwrite newer data with an older event: compare `sequence`/`occurred_at` against cached values.

---

## 6. Per-module frontend integration (summary)

| Module | Events consumed | Update strategy |
|---|---|---|
| Dashboard | `payout.changed`, `incident.changed`, `risk.decision`, `evidence.appended`, `session.changed` | Invalidate overview query; update metrics/timeline/alerts |
| Sessions / Identity | `session.changed`, `auth.security.event.ingested`, `identity.*` | Update session rows, trust badges, risk meters |
| Payouts | `payout.*` | Update payout row/status; fetch detail on authoritative outcomes |
| Risk | `risk.decision`, `risk.level.changed`, `risk.alert.generated` | Append decision row; update severity |
| Gateway | `gateway.decision.*`, `gateway.policy.changed` | Update decision stats; show security events |
| Honey / Canary | `honey.interaction`, `honey.canary.triggered`, `honey.canary.reuse`, `honey.isolation` | Update canary inventory, workspace cards, isolation state |
| Evidence | `evidence.appended`, `evidence.sealed`, `evidence.tampering.detected` | Append timeline; preserve ordering |
| Incidents | `incident.*` | Add/update incident; update status, assignment, resolution |
| Agentic commerce | `agentic.grant.*`, `agentic.reservation.*`, `agentic.limit.*` | Update totals, reservations, limit warnings |
| Reconciliation | `reconciliation.job.*` | Update job status, worker progress |

Manual refresh remains available as a recovery action on every page (existing Refresh buttons preserved).
