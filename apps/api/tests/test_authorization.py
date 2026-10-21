import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.repositories.session_repo import SessionRepository
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import TrustLevel
from tests.conftest import (
    NORMAL_SESSION_ID,
    OTHER_MERCHANT_ID,
    RESTRICTED_SESSION_ID,
    TEST_INCIDENT_ID,
    TestingSessionLocal,
)


def test_unauthenticated_requests_are_rejected(client: TestClient):
    """
    Requirement 10:
    Unauthenticated requests (no Bearer token or valid dev auth) are rejected with 401.
    """
    endpoints = [
        ("POST", "/v1/events", {"event_type": "auth.login"}),
        ("POST", "/v1/payouts", {"amount": 100}),
        ("GET", "/v1/sessions", None),
        ("GET", f"/v1/sessions/{NORMAL_SESSION_ID}", None),
        ("GET", "/v1/incidents", None),
        ("POST", f"/v1/incidents/{TEST_INCIDENT_ID}/approve", {}),
    ]

    for method, path, body in endpoints:
        if method == "POST":
            res = client.post(path, json=body or {})
        else:
            res = client.get(path)
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"
        assert res.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_merchant_cannot_invoke_analyst_actions(client: TestClient, merchant_auth_headers: dict):
    """
    Requirement 12:
    A merchant user cannot invoke analyst-only actions (approve / resolve incidents).
    Must return 403 Forbidden.
    """
    approve_res = client.post(
        f"/v1/incidents/{TEST_INCIDENT_ID}/approve",
        json={"notes": "Merchant trying to self-approve"},
        headers=merchant_auth_headers,
    )
    assert approve_res.status_code == 403
    assert approve_res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    resolve_res = client.post(
        f"/v1/incidents/{TEST_INCIDENT_ID}/resolve",
        json={"notes": "Merchant trying to resolve"},
        headers=merchant_auth_headers,
    )
    assert resolve_res.status_code == 403
    assert resolve_res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_analyst_cannot_approve_incident_outside_merchant_scope(
    client: TestClient, db_session: Session
):
    """
    Requirement 11:
    An analyst cannot approve incidents belonging to a different merchant domain.
    Must return 403 Forbidden.
    """
    # Seed incident belonging to OTHER_MERCHANT_ID
    other_incident_id = uuid.uuid4()
    other_inc = IncidentRecord(
        incident_id=other_incident_id,
        merchant_id=OTHER_MERCHANT_ID,
        title="Other Merchant Incident",
        description="Foreign incident",
        severity=IncidentSeverity.MEDIUM.value,
        status=IncidentStatus.OPEN.value,
        trigger_reason="SUSPICIOUS_PAYOUT",
    )
    db_session.add(other_inc)
    db_session.commit()

    # Analyst belonging to TEST_MERCHANT_ID attempts approval
    analyst_headers = {
        "Authorization": "Bearer dev-analyst-token",
        "X-Dev-Role": "analyst",
        "X-Dev-Merchant-Id": "00000000-0000-0000-0000-000000000001",
        "X-Dev-User-Id": "00000000-0000-0000-0000-000000000002",
    }

    res = client.post(
        f"/v1/incidents/{other_incident_id}/approve",
        json={"notes": "Unauthorized cross-merchant approval"},
        headers=analyst_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "MERCHANT_SCOPE_VIOLATION"


def test_incident_approval_does_not_change_trust_level(
    client: TestClient, analyst_auth_headers: dict, db_session: Session
):
    """
    Requirement 13:
    Incident approval must NOT automatically override trust decisions or disable isolation.
    Associated session MUST remain RESTRICTED.
    """
    session_repo = SessionRepository(db_session)
    sess_before = session_repo.get_by_id(RESTRICTED_SESSION_ID)
    assert sess_before.trust_level == TrustLevel.RESTRICTED.value

    # Analyst approves incident review
    res = client.post(
        f"/v1/incidents/{TEST_INCIDENT_ID}/approve",
        json={"notes": "Analyst reviewed telemetry. Investigation open."},
        headers=analyst_auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["action"] == "approved"

    # Verify session trust state was NOT overridden
    sess_after = session_repo.get_by_id(RESTRICTED_SESSION_ID)
    assert sess_after.trust_level == TrustLevel.RESTRICTED.value
    assert sess_after.trust_level != TrustLevel.NORMAL.value


def test_database_persistence_survives_lifecycle(db_session: Session):
    """
    Requirement 14:
    Verify database records and constraints persist across session lifecycles.
    """
    new_sess_id = uuid.uuid4()
    test_merchant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    test_user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    # 1. Write in current transaction
    record = SessionRecord(
        session_id=new_sess_id,
        user_id=test_user_id,
        merchant_id=test_merchant_id,
        trust_level="ISOLATED",
        risk_score=98.5,
        status="active",
        device_fingerprint="fp-persistence-check",
    )
    db_session.add(record)
    db_session.commit()

    # 2. Query through a brand new distinct session
    new_db = TestingSessionLocal()
    try:
        retrieved = new_db.query(SessionRecord).filter_by(session_id=new_sess_id).first()
        assert retrieved is not None
        assert retrieved.trust_level == "ISOLATED"
        assert retrieved.risk_score == 98.5
        assert retrieved.device_fingerprint == "fp-persistence-check"
    finally:
        new_db.close()


def test_errors_do_not_expose_secrets_or_credentials(
    client: TestClient, merchant_auth_headers: dict
):
    """
    Requirement 15:
    Error responses and JSON payloads must never expose internal secrets,
    database connection strings, or sensitive passwords.
    """
    # Cause a validation exception
    res = client.post(
        "/v1/payouts",
        json={"invalid_key": "junk_data"},
        headers=merchant_auth_headers,
    )
    assert res.status_code == 422
    content_str = res.text.lower()

    # Check for secret leakage
    forbidden_tokens = [
        "secret",
        "password",
        "database_url",
        "identitytwin_pass",
        "private_key",
    ]
    for token in forbidden_tokens:
        assert token not in content_str, f"Found sensitive leak: '{token}' in response"
