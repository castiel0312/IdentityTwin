import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.gateway.provider import mock_provider_instance
from app.models.session import SessionRecord
from app.schemas.sessions import SessionStatus, TrustLevel
from tests.conftest import (
    DECOY_SESSION_ID,
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    RESTRICTED_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def test_ast_scan_no_provider_imports_outside_gateway():
    """
    Invariant (a):
    AST scan failing if any module outside app/gateway imports IPaymentProviderAdapter,
    MockPaymentProviderAdapter, PayPalSandboxAdapter, DecoyHoneyAdapter,
    get_payment_provider, or get_decoy_provider.
    """
    forbidden_symbols = {
        "IPaymentProviderAdapter",
        "MockPaymentProviderAdapter",
        "PayPalSandboxAdapter",
        "DecoyHoneyAdapter",
        "get_payment_provider",
        "get_decoy_provider",
    }

    app_dir = Path(__file__).resolve().parent.parent / "app"
    gateway_dir = app_dir / "gateway"

    violations = []

    for py_file in app_dir.rglob("*.py"):
        # Whitelist only modules inside app/gateway
        if gateway_dir in py_file.parents:
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError as e:
            pytest.fail(f"Syntax error parsing {py_file}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_symbols:
                        violations.append(
                            f"{py_file.name}:{node.lineno} imports '{alias.name}' directly"
                        )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden_symbols:
                        violations.append(
                            f"{py_file.name}:{node.lineno} imports '{alias.name}' from '{node.module}'"
                        )

    assert not violations, (
        "Security architectural boundary violation: Payment provider adapters/getters imported outside app/gateway:\n"
        + "\n".join(violations)
    )


@pytest.mark.parametrize(
    "session_id,expected_status,expected_action,expected_provider_count",
    [
        (NORMAL_SESSION_ID, "completed", "ALLOW", 1),
        (RESTRICTED_SESSION_ID, "rejected", "REQUIRE_STEP_UP", 0),
        (DECOY_SESSION_ID, "decoy_completed", "DECOY_FORWARD", 0),
        (ISOLATED_SESSION_ID, "blocked", "BLOCK", 0),
    ],
)
def test_provider_invocation_matrix_trust_levels(
    client: TestClient,
    merchant_auth_headers: dict,
    session_id: uuid.UUID,
    expected_status: str,
    expected_action: str,
    expected_provider_count: int,
):
    """
    Invariant (b):
    Provider invocation matrix across NORMAL/RESTRICTED/DECOY/ISOLATED.
    Provider called exactly once for NORMAL, zero otherwise.
    """
    mock_provider_instance.reset()

    payload = {
        "session_id": str(session_id),
        "recipient_email": "contractor@supplier.com",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": f"matrix-{session_id}-{uuid.uuid4()}",
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == expected_status
    assert data["action"] == expected_action
    assert mock_provider_instance.invocation_count == expected_provider_count


def test_provider_invocation_matrix_revoked_session(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """
    Invariant (b - revoked):
    Revoked sessions must fail-closed with 403 Forbidden.
    Payment provider is never called.
    """
    mock_provider_instance.reset()

    revoked_session_id = uuid.uuid4()
    sess = SessionRecord(
        session_id=revoked_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=0.0,
        status=SessionStatus.REVOKED.value,
    )
    db_session.add(sess)
    db_session.commit()

    payload = {
        "session_id": str(revoked_session_id),
        "recipient_email": "contractor@supplier.com",
        "amount": 100.00,
        "currency": "USD",
        "idempotency_key": f"matrix-revoked-{uuid.uuid4()}",
    }
    res = client.post("/v1/payouts", json=payload, headers=merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "INACTIVE_SESSION"
    assert mock_provider_instance.invocation_count == 0


def test_hero_attack_sequence_canary_to_payout_block(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """
    Invariant (c):
    The hero attack sequence:
    1. Active session in NORMAL state.
    2. Telemetry ingestion triggers canary trap.
    3. Session is isolated and revoked; security incident is filed.
    4. Attacker attempts payout via POST /v1/payouts.
    5. Payout is denied, session remains isolated, provider count is 0.
    """
    mock_provider_instance.reset()

    hero_session_id = uuid.uuid4()
    sess = SessionRecord(
        session_id=hero_session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
    )
    db_session.add(sess)
    db_session.commit()

    now = datetime.now(timezone.utc)

    # 1. Normal telemetry event
    res_normal = client.post(
        "/v1/events",
        json={
            "session_id": str(hero_session_id),
            "event_type": "navigation.pageview",
            "action": "view_payouts_dashboard",
            "occurred_at": now.isoformat(),
            "metadata": {"url": "/merchant/payouts"},
        },
        headers=merchant_auth_headers,
    )
    assert res_normal.status_code == 201
    assert res_normal.json()["trust_level"] == "NORMAL"

    # 2. Hero canary attack event
    res_canary = client.post(
        "/v1/events",
        json={
            "session_id": str(hero_session_id),
            "event_type": "security.anomaly_detected",
            "action": "canary_trigger",
            "occurred_at": now.isoformat(),
            "metadata": {"canary": True, "trap": "honey_token_accessed"},
        },
        headers=merchant_auth_headers,
    )
    assert res_canary.status_code == 201
    assert res_canary.json()["trust_level"] == "ISOLATED"

    # 3. Verify session was revoked in database
    db_session.refresh(sess)
    assert sess.status == SessionStatus.REVOKED.value
    assert sess.trust_level == "ISOLATED"

    # 4. Attacker immediately attempts protected payout on compromised session
    res_payout = client.post(
        "/v1/payouts",
        json={
            "session_id": str(hero_session_id),
            "recipient_email": "attacker@exfiltration.net",
            "amount": 999.00,
            "currency": "USD",
            "idempotency_key": "hero-attack-exfil-" + str(uuid.uuid4()),
        },
        headers=merchant_auth_headers,
    )
    # Blocked due to inactive/revoked session state
    assert res_payout.status_code == 403
    assert res_payout.json()["error"]["code"] == "INACTIVE_SESSION"

    # Real payment provider was NEVER contacted
    assert mock_provider_instance.invocation_count == 0
