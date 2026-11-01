# Honey Workspace and Evidence Plane

This document describes the implemented Person 4 scope and its current
automated-test coverage.

## Implemented behavior

- Honey endpoints are mounted under `/v1/honey/*` and require an authenticated
  principal with an active session owned by that principal's user and merchant.
  Request-supplied identity IDs must match the authenticated user. They return synthetic merchant,
  customer, invoice, transaction, payee, payout, and developer-app data.
- Selected operations also use provider-shaped paths, including
  `/v1/payments/payouts`, `/v2/invoicing/invoices`, and
  `/v1/reporting/transactions`. They still require simulation `session_id` and
  `identity_id` context so records remain correctly scoped.
- Honey workspace state is persisted in `honey.workspace_state` and mirrored
  into session- and identity-scoped resource tables: `merchant_profile`,
  `balances`, `customers`, `invoices`, `transactions`, `payouts`, `payees`,
  `api_credentials`, and `activity_log`. The seed is deterministic, rows are
  marked synthetic, and a session cannot be rebound to another identity.
- Simulated payouts update that workspace's balance, payout and transaction
  history, and payee list. `PayPal-Request-Id` and `Idempotency-Key` retries
  return the original payout response without applying the balance change twice
  only when the original amount, currency, recipient, session, and identity
  match. Reusing a key with different payout parameters returns HTTP 409.
  These routes do not call the payment provider.
- Canary values are HMAC-derived, scoped to the issuing session, and issuance
  is repeatable per session/kind. They are bound to the session's owning user
  and merchant. Developer-app credentials and invoice exports include canary
  values only for an authenticated owner.
- Canary observations on honey requests inspect headers, path, query, and
  bounded-depth request-body content. Requests are recorded in the honey
  activity log. A matching value in its owning session records evidence,
  opens or updates an incident, isolates that same session, seals its evidence,
  and blocks the honey operation. A value from another session is not consumed
  and cannot isolate the observed session.
- Production startup requires a `CANARY_HMAC_SECRET` with at least 32
  characters and sufficient character entropy; the development fallback is
  never used in production.
- Evidence records contain a canonical payload hash and a chained hash.
  Verification checks sequence continuity, payload hashes, stored previous
  hashes, orphan payloads, and the persisted chain-head checkpoint, including
  detection of a missing final row.
- SQLite runtime initialization and Alembic migration 007 install append-only
  guards for evidence updates/deletes. PostgreSQL migration 007 installs
  mutation guards as well.
- Evidence verification, incident timelines, and attack traces are based on
  persisted evidence. `POST /v1/simulate/attack` exercises the canary
  containment path.
- Seal creation verifies that its incident, session, and merchant belong
  together. Seal-detail responses include only the sealed session's entries;
  hash-chain validation still verifies the complete global sequence interval
  without returning other tenants' payloads.
- Gateway-driven blocks append `gateway_blocked` and `session_isolated`
  evidence linked to the incident and seal the resulting evidence.

## Deployment and testing notes

The API uses `HONEY_DB_URL` for its honey workspace connection, falling back to
`DATABASE_URL` when it is unset. Compose configures the dedicated `honey_rw`
role and runs Alembic upgrades before starting the API. The role bootstrap SQL
is executed only when Postgres initializes a new data directory; an existing
volume will not rerun it automatically.

Automated SQLite tests cover chain tampering and deletion detection, seal
behavior, concurrent appends, canary-triggered containment, repeatable canary
issuance, payout persistence/idempotency, and normalized honey-resource
persistence. SQLite startup installs the same append-only evidence guards;
tests that deliberately tamper with evidence use an isolated scratch database.

The following are historical deployment checks documented by the prior delivery;
they were not rerun during this remediation:

- Migrations apply through `010_normalized_honey_workspace`, including the
  honey schema tables.
- `/health` and `/ready` succeed with the configured application and honey
  database connections.
- The API's `honey_rw` database connection reads and writes the honey schema;
  PostgreSQL reports no readable base tables in `public` for that role.
- A simulated payout persists with its balance and history across an API
  container restart, and a repeated idempotency key does not deduct funds
  twice.
- Attack simulation creates a sealed incident; its persisted timeline and
  attack trace are available, and evidence-chain verification reports valid.
- Canary containment events are forwarded over authenticated, merchant-scoped
  Server-Sent Events at `/v1/events/stream`; recent events can be replayed by
  event ID.
- The Compose API and database share an internal Docker network and have no
  direct external egress. When PayPal Sandbox is selected, the API can use a
  private, unpublished Squid proxy that permits HTTPS CONNECT only to
  `api-m.sandbox.paypal.com:443`; all other proxy destinations are denied.
  The Trust Gateway invokes the PayPal adapter only for allowed payouts, while
  the honey adapter writes to the synthetic workspace and never calls that
  proxy. A separate Nginx gateway preserves host access on port 8000, and
  PostgreSQL is not published on the host.

Remaining deployment limitations:

- The PostgreSQL role initialization script runs only on first initialization
  of the database volume. Existing volumes do not rerun Docker entrypoint SQL.
- The in-process SSE bus is best-effort and has a bounded replay buffer; it is
  not a cross-process or durable broker. Incidents and evidence remain
  persisted as the durable record; run one API worker when relying on live SSE.

The JSON workspace row is the API's transactionally updated snapshot; the
resource tables are persisted alongside it for isolated storage and querying.
Provider-shaped aliases are limited to the listed operations; all payout
values and identities are simulated. Those aliases still require session and
identity context in the request for workspace scoping; they do not implement
the full provider API or replace the separate sandbox integration.

## Local smoke test

Start the API using the repository's local-development instructions. The
evidence endpoint requires the configured development bearer token.

```powershell
$token = if ($env:DEV_AUTH_TOKEN) { $env:DEV_AUTH_TOKEN } else { "dev-secret-token-change-in-prod" }
$headers = @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Method Post -Uri "http://localhost:8000/v1/simulate/attack" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8000/v1/evidence/verify" -Headers $headers
$sessionId = "<active session owned by the authenticated user>"
$identityId = "<authenticated user UUID>"
Invoke-RestMethod -Uri "http://localhost:8000/v1/honey/merchant/profile?session_id=$sessionId&identity_id=$identityId" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8000/v1/merchant/merchant-info?session_id=$sessionId&identity_id=$identityId" -Headers $headers
```

## Security properties and limits

The evidence chain is tamper-evident, not immutable: a privileged database
operator can rewrite both entries and checkpoints. Production deployments need
an independently controlled external anchor or immutable storage. Honey
responses and payout state are test/deception data, not a payment ledger.
