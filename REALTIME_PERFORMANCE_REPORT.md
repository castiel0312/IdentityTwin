# REALTIME PERFORMANCE REPORT

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed and no load tests were executed during this audit. All targets below are **service objectives**, not claims of current performance. Actual measured results must be recorded after implementation under representative staging load.

---

## 1. Service level objectives (targets)

| Metric | Target | Measurement point |
|---|---|---|
| Business commit to outbox persistence | Same transaction | `domain_events` row visible in same DB transaction as business state |
| Outbox publication latency | p95 < 1 s | Commit → dispatcher publishes (NOTIFY) |
| SSE delivery after publication | p95 < 1 s | Dispatcher publish → client receives event |
| End-to-end UI update | p95 < 2 s | Business commit → UI reflects change |
| Reconnect after temporary disconnect | Within 5 s (normal conditions) | Disconnect → client re-connected and replayed |
| Event loss after committed transaction | Zero | Committed outbox event eventually delivered/replayed |
| Duplicate business processing | Zero | No duplicate UI state changes from duplicate events |
| Cross-tenant event exposure | Zero | No tenant receives another tenant's events |

---

## 2. Measurement methodology

- Instrument at each pipeline hop: business service, outbox insert, dispatcher publish, SSE write, client receive, React render.
- Record timestamps with correlation IDs end-to-end.
- Capture p50/p95/p99 latencies under: baseline, burst (N events/sec), multi-connection (M concurrent SSE clients), and multi-instance (K API + L worker instances).
- Record database connection pool usage and memory consumption during load tests.
- Test limits established before execution; no production load testing without authorization.

---

## 3. Actual measured results

| Metric | Target | Actual (staging) | Status |
|---|---|---|---|
| Business commit to outbox persistence | Same transaction | Not measured | Pending implementation |
| Outbox publication latency | p95 < 1 s | Not measured | Pending implementation |
| SSE delivery after publication | p95 < 1 s | Not measured | Pending implementation |
| End-to-end UI update | p95 < 2 s | Not measured | Pending implementation |
| Reconnect after disconnect | Within 5 s | Not measured | Pending implementation |
| Event loss after commit | Zero | Not measured | Pending implementation |
| Duplicate business processing | Zero | Not measured | Pending implementation |
| Cross-tenant exposure | Zero | Not measured | Pending implementation |

**Note:** No code changes and no load tests were performed as part of this audit (per instruction not to change code). This section is to be populated during the implementation and verification phases.

---

## 4. Correctness over latency

Latency targets must not be met by sacrificing durability: outbox persistence remains in the same transaction; replay from durable storage remains the recovery path; no in-memory-only delivery.
