# IdentityTwin API Contracts Specification

This document details the request, response, and error contracts for all foundational endpoints in IdentityTwin API v1.

The authoritative schema is maintained in `packages/contracts/openapi.json`.

---

## Standard Error Response Format

All error responses across IdentityTwin use a uniform JSON structure:

```json
{
  "error": {
    "code": "OWNERSHIP_MISMATCH",
    "message": "Resource does not belong to the authenticated session or merchant scope.",
    "details": {}
  }
}
```

### Standard Error Codes:
- `AUTHENTICATION_REQUIRED` (401): Missing, expired, or invalid credentials.
- `INSUFFICIENT_PERMISSIONS` (403): Role-based access control violation (e.g. merchant calling analyst endpoint).
- `OWNERSHIP_MISMATCH` (403): Session, merchant, or resource scope mismatch.
- `POLICY_VIOLATION` (403): Trust Gateway policy denied action (e.g. inactive session, isolation).
- `RESOURCE_NOT_FOUND` (404): Specified resource ID does not exist.
- `DUPLICATE_REQUEST` (409): Idempotent request currently in progress.
- `VALIDATION_ERROR` (422): Payload schema or boundary validation failure.

---

## 1. Health and Readiness Endpoints

### `GET /health`
Liveness probe indicating that the process is running.
- **Auth**: None required.
- **Response** (200 OK):
```json
{
  "status": "ok",
  "service": "IdentityTwin Trust Gateway API",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-10-21T14:30:00Z"
}
```

### `GET /ready`
Readiness probe testing database connectivity.
- **Auth**: None required.
- **Response (200 OK)**:
```json
{
  "status": "ready",
  "database": "connected",
  "timestamp": "2026-10-21T14:30:00Z"
}
```
- **Response (503 Service Unavailable)**: Returned if database connectivity fails.

---

## 2. Event Telemetry Ingestion

### `POST /v1/events`
Ingests behavioral and security telemetry for a merchant session.

- **Auth**: Required (`merchant` or `analyst` role).
- **Request Headers**:
  - `Authorization: Bearer <token>`
- **Request Body**:
```json
{
  "event_type": "behavioral.keystroke",
  "session_id": "22222222-2222-2222-2222-222222222222",
  "occurred_at": "2026-10-21T14:29:55Z",
  "device_id": "fp_mac_chrome_99812",
  "ip_address": "192.168.1.1",
  "action": "input_flight_time",
  "metadata": {
    "key_code": 65,
    "flight_duration_ms": 112,
    "dwell_time_ms": 45
  },
  "idempotency_key": "evt-776123-uuid"
}
```
- **Validation Rules**:
  - `session_id` must match authenticated caller's merchant and user ownership.
  - `occurred_at` must not be > 10 min in the future or > 30 days in the past.
  - `metadata` allows a maximum of 25 keys, scalar values or small lists, no arbitrary unbounded JSON.
- **Response** (201 Created):
```json
{
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "session_id": "22222222-2222-2222-2222-222222222222",
  "server_received_at": "2026-10-21T14:30:00Z",
  "status": "accepted",
  "message": "Security event accepted and scheduled for behavioral analysis."
}
```

---

## 3. Session Trust Management

### `GET /v1/sessions`
Lists active sessions within the authenticated merchant's domain.
- **Auth**: Required.
- **Query Parameters**: `page` (default 1), `page_size` (default 20, max 100).
- **Response** (200 OK):
```json
{
  "items": [
    {
      "session_id": "22222222-2222-2222-2222-222222222222",
      "user_id": "11111111-1111-1111-1111-111111111111",
      "merchant_id": "00000000-0000-0000-0000-000000000001",
      "trust_level": "NORMAL",
      "risk_score": 0.0,
      "status": "active",
      "device_fingerprint": "desktop-chrome-mac-verified",
      "ip_address": "127.0.0.1",
      "created_at": "2026-10-21T12:00:00Z",
      "updated_at": "2026-10-21T14:20:00Z",
      "last_activity_at": "2026-10-21T14:29:55Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### `GET /v1/sessions/{session_id}`
Returns authoritative trust status and risk score for a single session.
- **Auth**: Required. Validates merchant scope.
- **Response** (200 OK): Same as single session item above.

### `POST /v1/sessions/{session_id}/step-up`
Issues a time-bound (5-minute) cryptographic step-up verification challenge bound to session and merchant.
- **Auth**: Required (`merchant` role).
- **Response** (201 Created):
```json
{
  "challenge_id": "88888888-8888-8888-8888-888888888888",
  "session_id": "33333333-3333-3333-3333-333333333333",
  "expires_at": "2026-10-21T14:35:00Z",
  "simulated_otp": "491823"
}
```

### `POST /v1/sessions/{session_id}/step-up/verify`
Validates the one-time verification code and marks the challenge verified.
- **Auth**: Required (`merchant` role).
- **Request Body**:
```json
{
  "challenge_id": "88888888-8888-8888-8888-888888888888",
  "code": "491823"
}
```
- **Response** (200 OK):
```json
{
  "challenge_id": "88888888-8888-8888-8888-888888888888",
  "session_id": "33333333-3333-3333-3333-333333333333",
  "status": "verified",
  "step_up_token": "88888888-8888-8888-8888-888888888888",
  "expires_at": "2026-10-21T14:35:00Z"
}
```

---

## 4. Protected Payout Operations

### `POST /v1/payouts`
Executes protected payout through the centralized Trust Gateway service.
- **Auth**: Required (`merchant` role).
- **Request Body**:
```json
{
  "session_id": "22222222-2222-2222-2222-222222222222",
  "recipient_email": "contractor@supplier.com",
  "amount": 1250.00,
  "currency": "USD",
  "reference_note": "Invoice #8921",
  "idempotency_key": "payout-idem-9812401"
}
```
- **Response** (200 OK) for `NORMAL` trust state:
```json
{
  "payout_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "decision_id": "9c8a7b6a-5432-10fe-dcba-9876543210ab",
  "session_id": "22222222-2222-2222-2222-222222222222",
  "status": "completed",
  "trust_level": "NORMAL",
  "action": "ALLOW",
  "routing_destination": "PROVIDER_MOCK",
  "risk_score": 0.0,
  "reason_codes": [
    "BASELINE_NORMAL_OPERATION",
    "POLICY_NORMAL_EXECUTION_PERMITTED"
  ],
  "provider_reference": "SYNTH-MOCK-TXN-A1B2C3D4E5F6",
  "amount": 1250.00,
  "currency": "USD",
  "recipient_email": "contractor@supplier.com",
  "created_at": "2026-10-21T14:30:00Z",
  "is_duplicate": false
}
```
- **Response** (200 OK) for `RESTRICTED` trust state:
```json
{
  "payout_id": "e3b0c442-98fc-1c14-9afb-4c8996fb9242",
  "decision_id": "11223344-5566-7788-99aa-bbccddeeff00",
  "session_id": "33333333-3333-3333-3333-333333333333",
  "status": "rejected",
  "trust_level": "RESTRICTED",
  "action": "REQUIRE_STEP_UP",
  "routing_destination": "RESTRICTED_REJECT",
  "risk_score": 60.0,
  "reason_codes": [
    "RESTRICTED_STEP_UP_REQUIRED",
    "POLICY_ENFORCED_STEP_UP_CHALLENGE_REQUIRED"
  ],
  "provider_reference": null,
  "amount": 1250.00,
  "currency": "USD",
  "recipient_email": "contractor@supplier.com",
  "created_at": "2026-10-21T14:30:00Z",
  "is_duplicate": false
}
```
- **Response** (200 OK) for `DECOY` trust state:
```json
{
  "status": "decoy_completed",
  "trust_level": "DECOY",
  "action": "DECOY_FORWARD",
  "routing_destination": "DECOY_HONEY",
  "provider_reference": "HONEY-DECOY-SIM-TXN-7F8E9D0C1B2A"
}
```
- **Response** (200 OK) for `ISOLATED` trust state:
```json
{
  "status": "blocked",
  "trust_level": "ISOLATED",
  "action": "BLOCK",
  "routing_destination": "ISOLATED_BLOCK",
  "provider_reference": null
}
```

---

## 5. Incident Management Endpoints

### `GET /v1/incidents`
Lists incidents for the merchant domain.
- **Auth**: Required (`merchant` or `analyst`).
- **Query Parameters**: `status`, `severity`, `page`, `page_size`.
- **Response** (200 OK):
```json
{
  "items": [
    {
      "incident_id": "66666666-6666-6666-6666-666666666666",
      "merchant_id": "00000000-0000-0000-0000-000000000001",
      "session_id": "33333333-3333-3333-3333-333333333333",
      "title": "Suspicious Rapid Device Fingerprint Shift",
      "description": "User session exhibited an abrupt behavioral anomaly during payout preparation.",
      "severity": "HIGH",
      "status": "OPEN",
      "risk_score": 78.5,
      "trigger_reason": "BEHAVIORAL_BIOMETRIC_ANOMALY",
      "evidence_summary": {
        "mouse_velocity_delta": 4.8,
        "keystroke_flight_time_variance": 0.32
      },
      "created_at": "2026-10-21T13:00:00Z",
      "updated_at": "2026-10-21T13:00:00Z",
      "resolved_at": null,
      "resolved_by": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### `POST /v1/incidents/{incident_id}/approve`
Records an analyst approval review for an open incident.
- **Auth**: Required (`analyst` role only. Merchant callers receive 403 Forbidden).
- **Request Body**:
```json
{
  "notes": "Reviewed biometric anomaly telemetry. Verified with secondary merchant channel.",
  "resolution_reason": "LEGITIMATE_EXCEPTION"
}
```
- **Response** (200 OK):
```json
{
  "incident_id": "66666666-6666-6666-6666-666666666666",
  "action": "approved",
  "previous_status": "OPEN",
  "new_status": "APPROVED",
  "analyst_id": "00000000-0000-0000-0000-000000000002",
  "timestamp": "2026-10-21T14:35:00Z",
  "notes": "Reviewed biometric anomaly telemetry. Verified with secondary merchant channel.",
  "message": "Incident review approved. Audit trail updated."
}
```

### `POST /v1/incidents/{incident_id}/resolve`
Resolves and archives an incident.
- **Auth**: Required (`analyst` role only).
- **Request Body**: Same as approve request.
- **Response** (200 OK): Returns new_status `"RESOLVED"`.

### `POST /v1/incidents/{incident_id}/approve-revocation`
Confirms permanent session revocation in response to an anomaly or canary security incident.
- **Auth**: Required (`analyst` or `admin` role). Validates merchant scope.
- **Request Body**:
```json
{
  "notes": "Reviewed attack telemetry. Confirmed account compromise. Session revocation permanently approved.",
  "resolution_reason": "CONFIRMED_ACCOUNT_TAKEOVER"
}
```
- **Invariant**: Strictly audit-logged. Never re-enables a session or triggers a payout.
- **Response** (200 OK): Returns new_status `"RESOLVED"` and action `"approved_revocation"`.

---

## 6. PayPal Webhook Endpoints

### `POST /v1/webhooks/paypal`
Receives and reconciles asynchronous notifications from PayPal Sandbox via the Trust Gateway verification layer.
- **Auth**: Cryptographic signature validation via PayPal HTTP transmission headers.
- **Required Headers**:
  - `paypal-auth-algo`: e.g. `SHA256withRSA`
  - `paypal-cert-url`: URL pointing to PayPal certificate
  - `paypal-transmission-id`: Unique PayPal transmission UUID
  - `paypal-transmission-sig`: Base64 signature
  - `paypal-transmission-time`: ISO 8601 timestamp
- **Request Body**:
```json
{
  "id": "WH-90812739812",
  "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
  "resource_type": "payouts",
  "resource": {
    "batch_header": {
      "payout_batch_id": "28J99401HG871234F",
      "batch_status": "SUCCESS"
    }
  }
}
```
- **Response** (200 OK):
```json
{
  "status": "processed",
  "event_id": "WH-90812739812",
  "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
  "message": "PayPal webhook event verified, deduplicated, and reconciled successfully."
}
```
- **Error Response** (400 Bad Request): Returned when signature verification fails (`INVALID_WEBHOOK_SIGNATURE`).

---

## 7. Future Subsystem Typed Stubs (HTTP 501)

These endpoints define the typed contracts for modules owned by other team members. They return standard structured error envelopes with HTTP status 501:

### Standard 501 Error Envelope
```json
{
  "error": {
    "code": "NOT_IMPLEMENTED",
    "message": "Endpoint not yet implemented.",
    "details": {
      "owner": "Person X (Role)"
    }
  }
}
```

### Stubs by Owner:
- **`GET /v1/stream`**: Real-time event and telemetry streaming (SSE / WebSocket). Tagged: `Real-Time Streaming (Person 2 - Risk & Person 5 - Evidence)`.
- **`POST /v1/signatures/{id}/approve`**: Cryptographic evidence bundle notarization and signature sign-off. Tagged: `Evidence Signatures (Person 5 - Evidence Integrity)`.
- **`GET /v1/evidence/verify?evidence_id={id}`**: Cryptographic chain-of-custody verification. Tagged: `Evidence Verification (Person 5 - Evidence Integrity)`.
- **`POST /v1/simulate/attack`**: Adversarial account-takeover drill runner. Tagged: `Attack Simulation (Person 4 - Honey Workspace & Red Team)`.

---

## 8. Behavioral Identity Twin (Person 2 - Risk Intelligence)

The twin viewer was previously a 501 stub owned by Person 2. It is now implemented and documented here.

### `GET /v1/identities/{id}/twin`

Returns the behavioural baseline established for one identity inside the authenticated merchant domain.

**Query Parameters**:
- `compare_session_id` (optional, UUID): session to compare against the established baseline.

**Response** (200 OK):
```json
{
  "user_id": "11111111-1111-1111-1111-111111111111",
  "merchant_id": "22222222-2222-2222-2222-222222222222",
  "twin_id": "33333333-3333-3333-3333-333333333333",
  "sample_count": 42,
  "is_provisional": false,
  "confirmed_device_count": 2,
  "confirmed_location_count": 2,
  "confirmed_payee_count": 3,
  "pending_payee_count": 1,
  "active_hours": [9, 10, 11],
  "hour_histogram": {"9": 12, "10": 18, "11": 12},
  "total_amount": 12450.0,
  "amount_count": 42,
  "device_fingerprints": ["<salted sha256 digest>"],
  "location_buckets": ["BENGALURU"],
  "last_updated_at": "2026-10-21T14:30:00Z",
  "deviation": {
    "session_id": "44444444-4444-4444-4444-444444444444",
    "risk_score": 32.0,
    "trust_level": "RESTRICTED",
    "risk_signals": {"NEW_DEVICE": 18.0, "NEW_LOCATION": 14.0},
    "reason_codes": ["NEW_DEVICE_DETECTED", "NEW_LOCATION_DETECTED"],
    "is_new_device": true,
    "is_new_location": true,
    "session_carried_forward": 0.0,
    "raw_points_sum": 32.0,
    "decay_points": 0.0
  }
}
```

**Invariants**:
- **Merchant scoped**: an identity that belongs to another merchant domain returns HTTP 403 with `IDENTITY_OWNERSHIP_MISMATCH`. A foreign `compare_session_id` returns HTTP 403 with `SESSION_OWNERSHIP_MISMATCH`.
- **No raw identifiers**: device fingerprints are stored and returned only as salted SHA-256 digests; locations are returned as coarse buckets.
- **Errors**: HTTP 404 `IDENTITY_NOT_FOUND` for an unknown identity, HTTP 404 `TWIN_NOT_FOUND` when no twin has been established yet, HTTP 404 `SESSION_NOT_FOUND` for an unknown `compare_session_id`.

