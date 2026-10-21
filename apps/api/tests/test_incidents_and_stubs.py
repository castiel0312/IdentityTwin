import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.gateway.provider import mock_provider_instance
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel
from tests.conftest import (
    OTHER_MERCHANT_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def test_approve_revocation_analyst_success(
    client: TestClient,
    analyst_auth_headers: dict,
    db_session: Session,
):
    """
    POST /v1/incidents/{id}/approve-revocation:
    Requires analyst/admin, merchant-scoped, audit-logged;
    Never re-enables a session or executes a payout.
    """
    mock_provider_instance.reset()

    # 1. Create a session and an associated incident
    test_session_id = uuid.uuid4()
    sess = SessionRecord(
        session_id=test_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level=TrustLevel.ISOLATED.value,
        risk_score=90.0,
        status=SessionStatus.REVOKED.value,
    )
    db_session.add(sess)

    incident_id = uuid.uuid4()
    incident = IncidentRecord(
        incident_id=incident_id,
        merchant_id=TEST_MERCHANT_ID,
        session_id=test_session_id,
        title="Canary Honeypot Access",
        description="Session revoked after canary breach.",
        severity=IncidentSeverity.CRITICAL.value,
        status=IncidentStatus.OPEN.value,
        risk_score=95.0,
        trigger_reason="CANARY_INTERACTION",
    )
    db_session.add(incident)
    db_session.commit()

    # 2. Analyst approves the revocation
    res = client.post(
        f"/v1/incidents/{incident_id}/approve-revocation",
        json={
            "notes": "Reviewed attack details. Permanent session revocation confirmed.",
            "resolution_reason": "CONFIRMED_ACCOUNT_TAKEOVER",
        },
        headers=analyst_auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "approved_revocation"
    assert data["new_status"] == "RESOLVED"
    assert "revoked" in data["message"].lower()

    # 3. Invariants: Session remains revoked; provider was NEVER called
    db_session.refresh(sess)
    assert sess.status == SessionStatus.REVOKED.value
    assert mock_provider_instance.invocation_count == 0


def test_approve_revocation_merchant_forbidden(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """Merchants cannot approve their own incidents or session revocations."""
    incident_id = uuid.uuid4()
    incident = IncidentRecord(
        incident_id=incident_id,
        merchant_id=TEST_MERCHANT_ID,
        title="Unauthorized Merchant Approval Attempt",
        description="Testing RBAC enforcement.",
        severity=IncidentSeverity.HIGH.value,
        status=IncidentStatus.OPEN.value,
        risk_score=85.0,
        trigger_reason="SUSPICIOUS_TRANSFER",
    )
    db_session.add(incident)
    db_session.commit()

    res = client.post(
        f"/v1/incidents/{incident_id}/approve-revocation",
        json={"notes": "Trying to approve without analyst role."},
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_approve_revocation_cross_merchant_rejected(
    client: TestClient,
    analyst_auth_headers: dict,
    db_session: Session,
):
    """Analysts cannot approve incidents belonging to other merchants."""
    incident_id = uuid.uuid4()
    incident = IncidentRecord(
        incident_id=incident_id,
        merchant_id=OTHER_MERCHANT_ID,
        title="Other Merchant Incident",
        description="Cross-merchant boundary test.",
        severity=IncidentSeverity.CRITICAL.value,
        status=IncidentStatus.OPEN.value,
        risk_score=90.0,
        trigger_reason="CROSS_MERCHANT_TEST",
    )
    db_session.add(incident)
    db_session.commit()

    res = client.post(
        f"/v1/incidents/{incident_id}/approve-revocation",
        json={"notes": "Attempting cross-merchant approval."},
        headers=analyst_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "MERCHANT_SCOPE_VIOLATION"


def test_501_stubs_return_standard_error_and_owner_tags(
    client: TestClient,
    merchant_auth_headers: dict,
):
    """Verify all 5 typed stubs return 501 with the standard error body and owner metadata."""
    sample_uuid = str(uuid.uuid4())

    endpoints = [
        ("GET", "/v1/stream", {}),
        ("GET", f"/v1/identities/{sample_uuid}/twin", {}),
        ("POST", f"/v1/signatures/{sample_uuid}/approve", {}),
        ("GET", f"/v1/evidence/verify?evidence_id={sample_uuid}", {}),
        ("POST", "/v1/simulate/attack", {}),
    ]

    for method, path, body in endpoints:
        if method == "GET":
            res = client.get(path, headers=merchant_auth_headers)
        else:
            res = client.post(path, json=body, headers=merchant_auth_headers)

        assert res.status_code == 501, f"Expected 501 on {method} {path}, got {res.status_code}"
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_IMPLEMENTED"
        assert "owner" in data["error"]["details"]
