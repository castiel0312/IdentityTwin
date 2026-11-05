# IdentityTwin — Known Limitations

**Date:** 2026-11-04
**Purpose:** Honest, explicit documentation of every capability that is not yet implemented, not yet verified, or environmentally constrained. Nothing here is concealed as a success.

---

## 1. Not implemented (gaps)

### Stub endpoints (501 NOT_IMPLEMENTED)
- `POST /v1/signatures/{id}/approve` — cryptographic signature approval on evidence bundles (Person 5).
- `GET /v1/stream` — real-time telemetry stream / SSE stub (Person 2 / Person 5).
These return 501 with a documented owner and planned protocol; they are not presented as implemented.

---

## 2. Environmentally constrained (verified honestly, not claimed)

### Successful PayPal Sandbox payout
IdentityTwin reaches PayPal Sandbox through the squid egress proxy, obtains a real OAuth token, and sends a genuine payout request to `/v1/payments/payouts`. PayPal answers with a genuine `403 PAYOUT_NOT_AVAILABLE` (`debug_id: f235886aed87f`) because the configured sandbox account is country-restricted from sending payouts.
- **What IS verified:** connectivity, OAuth, real request, honest error propagation (no fabricated success, `provider_reference=null`, payout not completed).
- **What is NOT verified:** a *completed* sandbox payout transaction. That requires a PayPal Sandbox account permitted to send payouts (a PayPal-side account configuration).
- **Status:** BLOCKED on PayPal account configuration, not an IdentityTwin defect.

### PostgreSQL host port
Host port access to PostgreSQL is intentionally **not published**. `docker-compose.yml` uses the private Docker network (`db:5432`) because `identitytwin_private` is an `internal: true` network (host port mappings are not published on internal networks). The API, alembic, and seed all connect via `db:5432`. Operators who need direct host DB access must either use `docker compose exec db psql ...` or change the network from internal to bridge (a security trade-off: internal networking forces all egress through the squid proxy).

---

## 3. Test-coverage limitations

- `tests/test_reconciliation_worker.py` requires `psycopg` (PostgreSQL-only module) and could not run in the local SQLite test environment (`ModuleNotFoundError: No module named 'psycopg'`). It should be run against a PostgreSQL database with `psycopg` installed.
- A *successful* PayPal sandbox payout could not be demonstrated (see above); the sandbox account is country-restricted. All PayPal routing-safety invariants were instead verified with `httpx.MockTransport` (no network) plus one genuine (rejected) sandbox call.
- Playwright E2E tests require a downloaded Chromium browser (`~/.cache/ms-playwright` or `~/Library/Caches/ms-playwright`).

---

## 4. AI / LLM limitations

- The optional LLM narrative is disabled by default (`AI_LLM_ENABLED=false`). When enabled, it requires explicit `AI_LLM_BASE_URL`, `AI_LLM_API_KEY`, `AI_LLM_MODEL` and a public, non-private HTTPS URL.
- The Investigator is read-only and advisory: it never influences trust levels, risk scores, routing, or payments, and never authorizes payments or revokes credentials.

---

## 5. Evidence integrity scope

- SHA-256 evidence chaining provides tamper detection within the database. It is **not** equivalent to immutable external storage or independent custody. The E2E and docs explicitly state: "not proof of immutability or independent custody."

---

## 6. Hackathon submission readiness

| Criterion | Status |
|-----------|--------|
| Docker starts from clean environment | PASS |
| PostgreSQL migrations succeed | PASS |
| Backend and frontend operational | PASS |
| Existing tests pass | PASS (618) |
| Risk decisions deterministic/explainable | PASS |
| Genuine sandbox provider transaction demonstrated | BLOCKED (PayPal account country-restricted; genuine rejection verified) |
| Restricted actions obey policy | PASS |
| Decoy actions never reach real provider | PASS |
| Canary access forces isolation | PASS |
| Evidence integrity works | PASS |
| AI narratives reference genuine evidence | PASS (deterministic; LLM optional) |
| Vaccination requires human approval | PASS (analyst approval mandatory; PROPOSED never applied; ACTIVE only; revoked never matches) |
| Second merchant demonstrates earlier detection | PASS (cross-merchant demonstration via `tests/test_vaccination.py`) |
| Dashboard reflects real backend state | PASS (E2E) |
| Full attack replay succeeds | PASS (canary drill via `POST /v1/simulate/attack`) |
| README/deployment accurate | PARTIAL (this audit documents verified behavior) |

**Bottom line:** IdentityTwin's core security boundary (Trust Gateway routing, honey/decoy confinement, canary containment, evidence integrity, idempotency) is implemented and verified. Security Vaccination is implemented and verified: signatures are generated from confirmed attacks, analyst approval is mandatory, only ACTIVE signatures are applied, cross-merchant matching works, merchant data remains isolated, and the second-merchant demonstration succeeds. One hackathon success criterion remains environmentally blocked (completed PayPal sandbox payout — sandbox account country-restricted; genuine rejection verified). All limitations are documented rather than claimed.
