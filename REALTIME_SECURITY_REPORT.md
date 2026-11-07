# REALTIME SECURITY REPORT

**Project:** IdentityTwin  
**Release candidate:** `63a3a9d935f0c4b36469d68f40e10bb9496284ff`  
**Constraint honored:** No code was changed during this audit. This report analyzes the security posture of the real-time architecture and the rules that must be preserved.

---

## 1. Tenant isolation (preserved and to be preserved)

- **Server-side scope only:** The SSE endpoint resolves `tenant_id` (`merchant_id`) from `AuthenticatedPrincipal`, which is derived from the validated bearer token/OIDC claims. Client-supplied `tenant_id` or `merchant_id` is never trusted for authorization (rule 7).
- **Outbox reads are tenant-filtered:** Every `domain_events` query includes `WHERE merchant_id = :merchant_id`; a client can only ever receive its own tenant's events.
- **No cross-tenant broadcast:** No event is published to a global channel; fan-out is per-tenant (or tenant-filtered on a shared channel).
- **Session scope:** `session_id` in payloads is validated against server-side ownership records before being used for any server-side filtering.

**Expected result:** Cross-tenant event exposure = zero.

---

## 2. Authentication

- SSE connection requires a valid bearer token; invalid/missing token → 401/403 before the stream opens.
- Production: OIDC/JWT validated via JWKS. Development: fixed dev tokens only; `X-Dev-*` overrides permitted only after a valid dev token.
- Token refresh handling on the frontend: 401 triggers refresh or sign-out; stream torn down and re-established with the new session.
- No auth tokens, bearer tokens, or session tokens appear in event payloads or logs (rule 8).

---

## 3. Data sensitivity in event payloads

Existing safe-field whitelist (`apps/api/app/services/domain_events.py`) limits `data` to non-sensitive fields per table. This must be extended to all new producers:

| Never included | Reason |
|---|---|
| Access tokens / passwords / API secrets | Credential leakage |
| Canary `secret_value` / HMAC material | Detection material must not be replayed to clients |
| Full payment credentials / card numbers | PCI-sensitive |
| Full provider payment responses | Sensitive payment information (rule 8) |
| Internal security-sensitive evidence beyond summary | Evidence chain confidentiality |
| Unnecessary personal data | Data minimization |

`payout.provider.accepted/rejected/completed` publish status and references only, never provider credentials or raw provider responses.

---

## 4. Authorization rejections

- SSE authorization failures are logged (count, generic reason) without exposing tenant-sensitive details.
- Per-tenant delivery failures are observable operationally without leaking one tenant's identifier to another.
- Invalid event payloads are rejected and logged; malformed `Last-Event-ID` → 400.

---

## 5. Security rules cross-reference

| Rule | Status in current architecture |
|---|---|
| Preserve security and tenant isolation | Existing: merchant-scoped SSE and outbox reads; must extend to all new producers |
| Do not expose secrets/payment info | Existing safe-field whitelist; extend to all new event types |
| Never trust client tenant/session | Existing: server-derived `principal.merchant_id` |
| No pre-commit event publishing | Existing: `after_flush_postexec` within transaction |
| No duplicate events | Existing: idempotency keys on payouts/event ingest; client dedup by `event_id` |

**Security verdict:** The foundation is tenant-isolated and authenticated. The implementation must extend the same server-derived scoping and safe-field whitelisting to every new event producer and consumer without introducing client-trusted tenant identity.
