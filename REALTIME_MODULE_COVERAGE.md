# REALTIME MODULE COVERAGE

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This report documents current coverage, target coverage, and the delivery path for every module. Measured latency is not available because no implementation changes were executed; targets are defined in REALTIME_PERFORMANCE_REPORT.md.

Coverage key:
- **Current delivery** = how the frontend receives updates today.
- **Target delivery** = the real-time delivery path after implementation.
- **Status** = Live / Partial / None.

---

## Module coverage table

| Module | Event producers (current → target) | Delivery path | Frontend consumers (current → target) | E2E test | Measured latency |
|---|---|---|---|---|---|
| Dashboard / Overview | `incident.changed`, `payout.changed`, `risk.decision`, `evidence.appended`, `session.changed` → same + `reconciliation.job.completed` | SSE `/v1/events/stream` → `useContainmentStream` → `LiveDomainEventStream` (events card only); metrics via 60s poll | Overview page: events card live; metrics/timeline/alerts NOT live | Risk alert appears on dashboard; summary metrics update live | Not measured |
| Sessions & Identities | `session.changed` (current); → `auth.security.event.ingested`, `identity.profile.updated`, `identity.state.changed` | SSE outbox (not consumed today) | Sessions page / Identities tab: manual refresh only | New session appears in sessions list live; trust state updates live | Not measured |
| Payouts / Payments | `payout.changed` (current via ORM listener); → `payout.requested`, `payout.provider.accepted/rejected`, `payout.completed`, `payout.failed`, `payout.outcome.ambiguous`, `payout.reconciled` | SSE outbox (not consumed) | Payouts list / detail: manual refresh only | Payout status changes after authoritative provider update | Not measured |
| Risk | `risk.decision` (current); → `risk.level.changed`, `risk.alert.generated` | SSE outbox (not consumed) | Risk page: manual refresh only | New risk alert appears on dashboard | Not measured |
| Gateway | `risk.decision` (current); → `gateway.decision.allow/block/decoy/isolated`, `gateway.policy.changed` | SSE outbox (not consumed) | None live today | New ALLOW/BLOCK/DECOY/ISOLATED decision appears | Not measured |
| Honey / Canary | None for honey interactions today; → `honey.interaction`, `honey.canary.triggered`, `honey.canary.reuse`, `honey.isolation` | SSE outbox (new producers required) | Honey page: manual refresh only | Honey interaction / canary trigger appears immediately | Not measured |
| Evidence | `evidence.appended`, `evidence.sealed` (current); → `evidence.verify.completed`, `evidence.tampering.detected` | SSE outbox (not consumed) | Evidence page: manual refresh; verify on demand | New evidence appears in timeline; tampering alert | Not measured |
| Incidents | `incident.changed` (current); → `incident.created/updated/assigned/escalated/resolved` | SSE outbox (not consumed) | Incidents page: manual refresh only | New incident appears immediately | Not measured |
| Agentic commerce | None today (`agents` not tracked); → `agentic.grant.created`, `agentic.reservation.created/consumed/released`, `agentic.limit.approached/reached` | SSE outbox (new producers required) | Agents page / detail: manual refresh only | Spending reservation updates correct UI | Not measured |
| Reconciliation | None today; → `reconciliation.job.created/claimed/processing/retried/completed/failed` | SSE outbox (new producers required) | Reconciliation via payout list flag only | Reconciliation completion appears immediately | Not measured |
| Vaccination / signatures | `vaccination.match`, `vaccination.signature` (current); not consumed | SSE outbox (not consumed) | Vaccination page: manual refresh only | New match appears live | Not measured |
| Investigations | `investigation.changed` (current); not consumed | SSE outbox (not consumed) | Incident detail: manual refresh only | Investigation update reflected live | Not measured |
| Authentication / session lifecycle | `session.changed` on create/update (current); → `auth.session.created/revoked`, `auth.session.trust_changed` | SSE outbox | Login/session pages: N/A (auth boundary) | Login/logout session state reflected across tabs | Not measured |

---

## Delivery path detail

**Backend (target):**
1. Business operation validated and executed.
2. Business state + `domain_events` outbox row persisted atomically in one transaction.
3. Transaction commits.
4. Dispatcher claims the pending outbox event atomically; `NOTIFY` wakes the SSE fan-out for the tenant.
5. SSE gateway replays missed events (Last-Event-ID) then streams live events, ordered by `event_id`, tenant-filtered.

**Frontend (target):**
1. Single shared SSE connection per authenticated tenant session (managed by subscription manager).
2. `useRealtimeEvent(eventType, handler)` registers typed handlers.
3. Incoming validated events update TanStack Query cache (targeted `setQueryData` / `invalidateQueries`) or append to timelines.
4. Cursor persisted in `sessionStorage`; reconnect replays from cursor with dedup.

---

## Current coverage verdict (no code changed)

- **Live (SSE consumed):** Dashboard events card only.
- **Partial (SSE available, not consumed):** Sessions, Identities, Payouts, Risk, Incidents, Evidence, Vaccination, Investigations — outbox events are produced by ORM listeners but no frontend consumer subscribes.
- **None (no producer, no consumer):** Honey canary trigger/reuse, gateway policy change, agentic commerce grants/reservations/limits, reconciliation jobs, authentication lifecycle events, evidence verify/tampering.

Manual refresh buttons remain on every page as a recovery action (to be preserved).
