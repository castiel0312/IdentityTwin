# IdentityTwin Remaining Acceptance Blockers

**Updated:** 2026-11-04 (UTC)

The items below are limits on acceptance coverage or product guarantees, not claims that the verified live flows failed. No production policy, risk threshold, or authentication check was weakened to run these tests.

| # | Status | Blocker / limitation | Evidence and impact | Safe next step |
|---|---|---|---|---|
| 1 | **BLOCKED** | PayPal Sandbox payout was not executed. | Sandbox OAuth succeeded and read-only `userinfo` returned HTTP 200. The running gateway was in `mock` mode, and no controlled Sandbox receiver account was configured. Sending to an unverified recipient would not meet the controlled-account requirement. | Provision/identify an approved Sandbox receiver account, then run one separately keyed low-value Sandbox payout through a Sandbox-configured gateway and verify provider status/reconciliation. |
| 2 | **BLOCKED** | Live LLM investigation narrative was unavailable. | The analyst workflow completed, was persisted, redacted, and deterministic, with `ai_used=false` and no model name. LLM use was disabled in the current stack. | Enable an approved non-production model configuration and repeat the analyst investigation; verify redaction, output provenance, and read-only behavior. |
| 3 | **LIMITATION** | Full frontend real-time acceptance remains incomplete. | The authenticated, tenant-scoped outbox now persists ordered events for 30 days and replay survived an API restart. Live browser verification covered containment, payout/risk events, overview metrics/activity, and the payout ledger. Session detail, incident, vaccination, evidence, and analyst workflow page updates were not independently observed. | Independently exercise each remaining event class with its corresponding page open; verify database state, event, automatic UI update, and tenant isolation before claiming full real-time behavior. |
| 4 | **LIMITATION** | There is no durable provider invocation counter/metrics endpoint. | Mock and honey executions are corroborated by persisted provider identity, references, environment, and adapter-local invocation markers. Zero-call routes persisted `provider_name=none` and null references, and gateway policy branches do not invoke those adapters. The local counter is not an independent, durable per-request metric. | Add a durable provider-attempt ledger or exported metric keyed by payout/decision ID if acceptance requires independent call counts. |
| 5 | **COVERAGE NOTE** | Cross-merchant vaccination was verified with controlled synthetic development tenants, not production merchants. | A source merchant created/approved a signature; an isolated development merchant matched it, persisted the match, and received a restricted gateway decision. No real merchant account or real payment was used. | No action is needed for development acceptance. For broader rollout, repeat with approved non-production tenant fixtures and verify tenant-boundary isolation. |

## Completed fixes and validation

- Fixed SSE event-ID precision loss by preserving decimal IDs as strings and comparing with `BigInt`; the adjacent-ID regression and live browser update both passed.
- Added a durable tenant-scoped event outbox, ordered replay, reconnect recovery after API restart, 30-day retention, and frontend query synchronization for supported event classes.
- Fixed the overview's frozen analytics range after live SSE invalidation failed to include a newly completed payout. Live dashboard count advanced 27→28 without reload after the correction.
- Full automated suites passed: backend **645 passed**, frontend unit **20 passed**, Playwright **12 passed**.
- Frontend build/type-check passed. Targeted lint on the modified overview files reported no warnings or errors.
- The live stack used development auth and the mock provider for payouts. Sandbox credentials/tokens, OTP values, and recipient details are not reproduced here.
