# REALTIME EVENT CATALOG

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Schema basis:** Existing `domain_events` outbox (migration `019_durable_domain_events`)  
**Constraint honored:** No code was changed during this audit. This document specifies the event contract to be implemented.

---

## 1. Versioned event envelope

The envelope below adapts the suggested structure to the existing implementation. The existing outbox already carries `merchant_id` (tenant scope), a monotonic `event_id` (per-merchant sequence), `event_type`, `entity_type`/`entity_id` (aggregate identity), `operation`, `payload` (JSON with `schema_version: 1`), and `created_at` (occurred-at). The envelope standardizes these into a single shape published over SSE.

```json
{
  "event_id": "evt_0000000000000012345",
  "event_type": "gateway.decision.created",
  "event_version": 1,
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "session_id": "11111111-1111-1111-1111-111111111111",
  "aggregate_type": "risk_decision",
  "aggregate_id": "a1b2c3d4-...",
  "sequence": 12345,
  "occurred_at": "2026-11-08T12:00:00.000Z",
  "correlation_id": "req-...",
  "data": {},
  "schema_version": 1
}
```

### Field semantics

| Field | Type | Requirement | Source / derivation |
|---|---|---|---|
| `event_id` | string (numeric) | Required, unique | `domain_events.event_id` (per-merchant monotonic) |
| `event_type` | string | Required, dot-namespaced | Outbox `event_type` |
| `event_version` | integer | Required | Envelope version; `1` initially |
| `tenant_id` | UUID | Required; **server-derived only** | `principal.merchant_id` from authenticated session |
| `session_id` | UUID | Optional | Aggregate `session_id` when applicable |
| `aggregate_type` | string | Required | Outbox `entity_type` |
| `aggregate_id` | string | Required | Outbox `entity_id` |
| `sequence` | integer | Required; monotonic within tenant stream | `domain_events.event_id` |
| `occurred_at` | ISO-8601 | Required | `domain_events.created_at` |
| `correlation_id` | string | Optional | Request correlation id when available |
| `data` | object | Required; validated payload | Outbox `payload` (safe fields only) |
| `schema_version` | integer | Required | Outbox payload `schema_version` |

### Authorization rules (never trust the client)

- `tenant_id` is **always** derived from the authenticated principal (`AuthenticatedPrincipal.merchant_id`), never from a client-supplied value.
- `session_id` is accepted only when the session is proven to belong to the authenticated principal and tenant (server-side ownership check).
- The SSE connection authorizes the tenant once at connect time; all subsequent events on that connection are filtered to that tenant server-side.

### Fields never included

- Access tokens, bearer tokens, session tokens
- Passwords or password hashes
- API secrets, signing keys, canary `secret_value`, canary HMAC material
- Full payment credentials (card numbers, PayPal credentials, provider access tokens)
- Unnecessary personal data beyond what the existing safe-field whitelist already includes
- Internal security-sensitive evidence beyond the event summary

---

## 2. Event catalog

Events are grouped by business domain. Each entry lists the event type, version, aggregate, producer location (current or required), trigger operation, payload contents, sensitive fields excluded, and the frontend consumer.

### 2.1 Authentication and sessions

| Event type | Version | Aggregate | Producer | Trigger | Payload (`data`) | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `auth.session.created` | 1 | session | `sessions` ORM listener (required: explicit emit on session creation) | New session registered | session_id, user_id, status, trust_level, created_at | None | Sessions, Identity, Dashboard |
| `auth.session.revoked` | 1 | session | `sessions` ORM listener | Session revoked / isolated | session_id, user_id, trust_level, reason | None | Sessions, Dashboard, Incident detail |
| `auth.session.trust_changed` | 1 | session | `sessions` ORM listener | Trust level / risk score updated | session_id, trust_level, risk_score, previous_risk_score | None | Sessions, Identity, Risk, Dashboard |
| `auth.security.event.ingested` | 1 | behavioral_event | `security_events` ORM listener (`behavioral.event`) | Behavioral signal ingested | session_id, event_type, action, risk_score, trust_level | ip_address, device_id, metadata details | Identity, Sessions, Risk |

*Note:* `session.changed` already exists in the outbox via the `sessions` listener; the catalog above refines it into semantically named sub-types at the envelope layer without changing stored event types.

### 2.2 Behavioral identity

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `identity.profile.updated` | 1 | identity | `sessions`/`identities` ORM listener (required) | Identity projection updated | user_id, role, device_count, payee_count, max_risk_score | None | Identity, Sessions |
| `identity.verification.result` | 1 | identity | Required new producer | Step-up verification result | session_id, verification_status, verified_at | OTP code, challenge details | Identity, Sessions |
| `identity.state.changed` | 1 | identity | Required new producer | Twin provisional/confirmed change | user_id, twin_status, sample_count | Raw twin features | Identity |

### 2.3 Trust engine

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `trust.score.updated` | 1 | session | `sessions` ORM listener (`session.changed`) | Session trust/risk updated | session_id, trust_level, risk_score | None | Trust, Sessions, Dashboard |
| `trust.decision.created` | 1 | risk_decision | `risk_decisions` ORM listener (`risk.decision`) | Risk decision persisted | decision_id, session_id, risk_score, trust_level, action, routing_destination, reason_codes | Raw risk signals detail | Trust, Risk, Gateway, Dashboard |
| `trust.threshold.crossed` | 1 | session | Required new producer | Band boundary crossed (normal→restricted→decoy→isolated) | session_id, previous_level, new_level, risk_score | None | Trust, Risk, Dashboard |
| `trust.confidence.changed` | 1 | identity | Required new producer | Identity confidence updated | user_id, confidence_level | None | Identity |

### 2.4 Risk engine

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `risk.assessment.created` | 1 | risk_decision | `risk_decisions` ORM listener | New risk assessment | decision_id, session_id, risk_score, action | None | Risk, Dashboard |
| `risk.level.changed` | 1 | risk_decision | Required new producer | Severity band changed | decision_id, session_id, previous_level, new_level | None | Risk, Dashboard |
| `risk.alert.generated` | 1 | incident | Required new producer (on HIGH/CRITICAL) | Risk alert raised | alert_id, session_id, severity, trigger_reason | None | Dashboard, Risk, Incidents |
| `risk.decision.updated` | 1 | risk_decision | `risk_decisions` ORM listener | Decision re-evaluated | decision_id, session_id, new status | None | Risk |

### 2.5 Gateway

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `gateway.decision.created` | 1 | risk_decision | `risk_decisions` ORM listener (`risk.decision`) | ALLOW/BLOCK/DECOY/ISOLATED routing decision | decision_id, session_id, action, routing_destination, risk_score, trust_level | recipient, amount detail beyond summary | Gateway, Dashboard, Payouts |
| `gateway.decision.allow` | 1 | risk_decision | Same producer | ALLOW action | decision_id, session_id, action, routing_destination | None | Gateway |
| `gateway.decision.block` | 1 | risk_decision | Same producer | BLOCK action | decision_id, session_id, action, trigger_reason | None | Gateway, Incidents |
| `gateway.decision.decoy` | 1 | risk_decision | Same producer | DECOY routing | decision_id, session_id, action | None | Gateway, Honey |
| `gateway.decision.isolated` | 1 | risk_decision | Same producer | ISOLATED routing + isolation | decision_id, session_id, incident_id, trust_level | None | Gateway, Sessions, Incidents |
| `gateway.policy.changed` | 1 | gateway_policy | Required new producer | Trust gateway policy/threshold change | policy_key, previous_value, new_value, changed_at | None | Risk, Dashboard |

### 2.6 Honey Workspace / Canary

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `honey.interaction` | 1 | honey_interaction | Required new producer | Decoy endpoint/resource accessed | session_id, resource, action, occurred_at | Canary secret_value, tag, HMAC | Honey, Dashboard |
| `honey.canary.triggered` | 1 | canary | Required new producer | Armed canary touched | canary_id, kind, tag, session_id, observed_session_id, matched_in | Canary secret_value | Honey, Dashboard, Incidents |
| `honey.canary.reuse` | 1 | canary | Required new producer | Cross-session/merchant canary reuse observed | canary_id, canary_session_id, observed_session_id, observed_merchant_id, requesting_merchant_id | Secret values | Honey, Incidents, Dashboard |
| `honey.alert` | 1 | incident | `incidents` ORM listener (`incident.changed`) | Canary containment incident opened | incident_id, session_id, severity, trigger_reason | None | Honey, Incidents, Dashboard |
| `honey.isolation` | 1 | session | `sessions` ORM listener (`session.changed`) | Session isolated after canary hit | session_id, trust_level, risk_score, incident_id | None | Honey, Sessions |

*Note:* Canary `secret_value` and `tag` are detection metadata; `tag` may appear in payloads but `secret_value` must never be published.

### 2.7 Evidence chain

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `evidence.appended` | 1 | evidence_log | `evidence_log` ORM listener | Evidence entry appended | evidence_seq, session_id, incident_id, event_ref, type | Internal hash internals beyond head | Evidence, Incidents |
| `evidence.sealed` | 1 | incident_seal | `incident_seals` ORM listener (`evidence.sealed`) | Evidence range sealed | seal_id, incident_id, session_id, start_seq, end_seq, head_hash, sealed_at | None | Evidence, Incidents |
| `evidence.verify.completed` | 1 | evidence_log | Required new producer | Chain verification run | checked, valid, head_hash, first_broken_seq, reason | None | Evidence |
| `evidence.tampering.detected` | 1 | evidence_log | Required new producer | Hash chain break detected | first_broken_seq, head_hash, reason | None | Evidence, Dashboard, Incidents |

### 2.8 Incidents

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `incident.created` | 1 | incident | `incidents` ORM listener (`incident.changed`) | Incident opened | incident_id, session_id, title, severity, status, trigger_reason, risk_score | Evidence summary internals | Incidents, Dashboard |
| `incident.updated` | 1 | incident | `incidents` ORM listener | Incident fields updated | incident_id, status, severity, risk_score | None | Incidents |
| `incident.assigned` | 1 | incident | `analyst_actions` ORM listener (`analyst.workflow`) | Analyst action recorded | incident_id, analyst_id, action_type, notes | None | Incidents |
| `incident.escalated` | 1 | incident | `analyst_actions` ORM listener | Incident escalated | incident_id, analyst_id, escalation_reason | None | Incidents, Dashboard |
| `incident.resolved` | 1 | incident | `incidents` ORM listener | Incident resolved/archived | incident_id, status, resolved_at, analyst_id | None | Incidents, Dashboard |

### 2.9 Payments

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `payout.requested` | 1 | payout_request | `payout_requests` ORM listener (`payout.changed`) | Payout submitted to gateway | payout_id, session_id, amount, currency, recipient_email, status, idempotency_key | Provider credentials, full payload | Payments, Dashboard, Agent detail |
| `payout.submitted` | 1 | payout_request | Same producer | Payout sent to provider | payout_id, provider_name, provider_reference, batch_status | Provider raw response | Payments |
| `payout.provider.accepted` | 1 | payout_request | Required new producer (on reconciliation/provider SUCCESS) | Provider accepted payout | payout_id, status, provider_batch_id, executed_at | None | Payments |
| `payout.provider.rejected` | 1 | payout_request | Required new producer (on DENIED/FAILED) | Provider definitively rejected | payout_id, status, batch_status, reason | None | Payments |
| `payout.pending` | 1 | payout_request | Same producer | Outcome ambiguous (PENDING/PROCESSING) | payout_id, status, batch_status, reconciliation_required | None | Payments |
| `payout.completed` | 1 | payout_request | Same producer | Provider confirmed completion (SUCCESS) | payout_id, status, executed_at | Provider credentials | Payments, Dashboard |
| `payout.failed` | 1 | payout_request | Same producer | Terminal failure | payout_id, status, reason | None | Payments |
| `payout.outcome.ambiguous` | 1 | payout_request | Required new provider | Timeout/unknown outcome | payout_id, status, reconciliation_required | None | Payments |
| `payout.reconciled` | 1 | payout_request | `payout_requests` ORM listener via reconciliation worker | Reconciliation updated payout | payout_id, previous_status, new_status, reconciled_at | None | Payments, Reconciliation, Dashboard |

*Note:* Rule 14 — a payout request submission alone never implies completion; `payout.completed` fires only on authoritative provider confirmation.

### 2.10 Agentic commerce

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `agentic.grant.created` | 1 | agent_grant | Required new producer | Spending grant created | grant_id, agent_id, session_id, max_amount, scopes, expires_at | None | Agents, Agentic commerce |
| `agentic.reservation.created` | 1 | agent_grant | Required new producer | Spending reservation reserved | grant_id, reserved_amount, amount | None | Agentic commerce, Dashboard |
| `agentic.reservation.consumed` | 1 | agent_grant | Required new producer | Reservation consumed (payout completed) | grant_id, consumed_amount | None | Agentic commerce |
| `agentic.reservation.released` | 1 | agent_grant | Required new producer | Reservation released (failure/timeout) | grant_id, released_amount | None | Agentic commerce |
| `agentic.limit.approached` | 1 | agent_grant | Required new producer | Spending near grant ceiling | grant_id, consumed_amount, max_amount, pct | None | Agentic commerce, Dashboard |
| `agentic.limit.reached` | 1 | agent_grant | Required new producer | Grant ceiling reached | grant_id, consumed_amount, max_amount | None | Agentic commerce, Dashboard |

### 2.11 Reconciliation and workers

| Event type | Version | Aggregate | Producer | Trigger | Payload | Excluded | Frontend consumer |
|---|---|---|---|---|---|---|---|
| `reconciliation.job.created` | 1 | reconciliation_job | Required new producer | Reconciliation job queued | job_id, payout_id, merchant_id, attempt | None | Reconciliation |
| `reconciliation.job.claimed` | 1 | reconciliation_job | Required new producer | Worker claims job (`FOR UPDATE SKIP LOCKED`) | job_id, worker_id, claimed_at | None | Reconciliation |
| `reconciliation.job.processing` | 1 | reconciliation_job | Required new producer | Job processing started | job_id, status | None | Reconciliation |
| `reconciliation.job.retried` | 1 | reconciliation_job | Required new producer | Retry scheduled with backoff | job_id, attempt, next_retry_at | None | Reconciliation |
| `reconciliation.job.completed` | 1 | reconciliation_job | Required new producer | Job resolved | job_id, payout_id, new_status, resolved | None | Reconciliation, Payments |
| `reconciliation.job.failed` | 1 | reconciliation_job | Required new producer | Job failed / escalated | job_id, payout_id, failure_reason, escalated | None | Reconciliation, Dashboard |

---

## 3. Event type naming conventions

- Dot-namespaced: `<domain>.<entity>.<action>` (e.g. `payout.changed`, `honey.canary.triggered`).
- Versions start at 1; backward-compatible changes add fields; breaking changes increment `event_version` and run in parallel during a deprecation window.
- No two event types share the same semantic for the same aggregate without a clear version/sub-type distinction.

---

## 4. Sequence / ordering

- `sequence` equals the per-merchant `domain_events.event_id` (monotonic BigInteger, assigned inside the transaction).
- Ordering guarantee is **per tenant stream**. Cross-tenant ordering is not required and must not be implied.
- Clients dedup by `event_id` and reject out-of-order/stale events where `sequence <= last_processed_sequence` for that tenant stream.
