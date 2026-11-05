# AI Investigator (Person 6)

The AI Investigator is a **read-only, advisory** layer over deterministic security
evidence. It never scores, routes, isolates, approves, restores a session or
executes a payout. The Trust Gateway, risk engine, honey plane and payment
provider remain authoritative.

## Endpoints

| Method | Path | Authorization |
| --- | --- | --- |
| `POST` | `/v1/incidents/{incident_id}/investigations` | Analyst/Admin, merchant-scoped |
| `GET` | `/v1/incidents/{incident_id}/investigations` | Authenticated, merchant-scoped |
| `GET` | `/v1/investigations/{investigation_id}` | Authenticated, merchant-scoped |

Cross-tenant incidents and investigations return `404` so tenant existence is
not disclosed. Merchants cannot run investigations.

## Pipeline

1. **Bounded extraction** - incident, session, security events, risk decisions,
   payouts, evidence-chain entries, canaries and seal are loaded for one
   merchant scope only, with deterministic ordering and limits
   (`AI_INVESTIGATION_MAX_EVENTS`). Evidence-chain queries filter by
   `session_id` and `merchant_id` in SQL and are bounded; listing investigations
   never reads the chain.
2. **Allowlisted LLM projection** - the LLM never receives `evidence_summary`,
   incident titles or descriptions, event metadata, IP addresses, device IDs,
   recipient emails, canary tags or arbitrary evidence-chain payloads. Only an
   explicit allowlist of enum/code-like and numeric fields is forwarded, and all
   strings are normalized. Addresses, names, emails, phone numbers, IPv4/IPv6
   addresses, SSNs, short account/routing numbers and credentials are removed
   from any remaining free text as defence in depth.
3. **Deterministic findings** - signals such as `NEW_DEVICE`, `NEW_PAYEE`,
   `LARGE_PAYOUT`, `NEW_PAYEE_LARGE_PAYOUT`, `PAYEE_ADD_THEN_PAYOUT`,
   `CANARY_INTERACTION`, blocked payouts, decoy containment and session
   revocation. Findings cite evidence references and hashes.
4. **Advisory recommendations** - every item is `advisory_only` and
   `requires_human_approval`; nothing is applied automatically.
5. **Narrative** - a deterministic narrative is always produced. The optional
   LLM narrative runs only when explicitly configured, is schema-validated and
   falls back to the deterministic text on any failure or invalid output.

## Configuration

```dotenv
AI_INVESTIGATION_ENABLED=true
AI_LLM_ENABLED=false
AI_LLM_BASE_URL=
AI_LLM_EGRESS_HOST=
AI_LLM_API_KEY=
AI_LLM_MODEL=
AI_LLM_TIMEOUT=10.0
AI_LLM_MAX_INPUT_CHARS=12000
AI_LLM_MAX_RESPONSE_BYTES=65536
AI_INVESTIGATION_MAX_EVENTS=100
```

When `AI_LLM_ENABLED=true`, configure all of `AI_LLM_BASE_URL`,
`AI_LLM_EGRESS_HOST`, `AI_LLM_API_KEY` and `AI_LLM_MODEL`. The egress host must
exactly match the URL hostname, and Compose allows the proxy to CONNECT only to
that hostname on TLS port 443 (in addition to the allowlisted PayPal Sandbox
host). Put the API key in an untracked local `.env` or, outside local
development, a managed secret store; never commit it or put it in a frontend
variable. The base URL must be a public HTTPS origin without embedded
credentials. Loopback, private, link-local, reserved and internal hostnames
are rejected; DNS rebinding remains a residual risk because DNS is not pinned.
The provider must expose an OpenAI-compatible `POST
{base_url}/chat/completions` endpoint. Provider failure results in
`status="FALLBACK"`, `ai_used=false` and a deterministic narrative; the API
request itself still succeeds. The configured LLM is used only for the
investigation narrative; deterministic findings and gateway decisions remain
separate and authoritative.

Evidence is delimited as untrusted data in the prompt and must never be treated
as instructions. Oversized projections are reduced structurally
(field-by-field) before serialization; JSON is never cut mid-value.

## Guarantees

- No import path from the investigation package into the gateway, risk engine,
  payout execution or provider adapters.
- No writes except the new `investigations` row containing the redacted bundle.
- Recommendations are never executed.
- The LLM never receives raw secrets, credentials, tokens, payment payloads,
  recipient emails, free-text incident summaries, titles, descriptions, event
  metadata or arbitrary evidence-chain payloads. This is enforced by an explicit
  allowlist, not by regexes alone.
- Regex-based PII scrubbing is defence in depth for any remaining free text; it
  is **not** the primary guarantee.
- Investigation results cannot change routing, risk scores, trust levels,
  session status, access decisions or payment execution.

## Migrations

`014_investigations` creates the `investigations` table and its indexes.
`015_evidence_scope_columns` adds denormalized `session_id`/`merchant_id`
columns to `evidence_log` so investigation queries can be filtered and bounded
in SQL without scanning the global chain. Those columns are not part of the hash
chain and do not change chain integrity.
