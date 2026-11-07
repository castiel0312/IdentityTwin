import uuid

from app.gateway.provider import mock_provider_instance
from app.honey.bootstrap import bootstrap
from app.models.canary import CanaryRecord
from app.models.evidence import (
    HoneyActivityLog,
    HoneyApiCredential,
    HoneyBalance,
    HoneyCustomer,
    HoneyInvoice,
    HoneyMerchantProfile,
    HoneyPayee,
    HoneyPayout,
    HoneyTransaction,
    HoneyWorkspaceState,
)
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from tests.conftest import NORMAL_SESSION_ID, TEST_USER_ID


def test_honey_payout_shape(client, merchant_auth_headers):
    # Call honey payout directly via test client by mounting logic is via app; but easier to call endpoint
    resp = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": str(NORMAL_SESSION_ID),
            "identity_id": str(TEST_USER_ID),
            "amount": 1000,
            "recipient_email": "vendor@test.in",
        },
        headers=merchant_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "batch_header" in data
    assert "payout_batch_id" in data["batch_header"]
    assert "items" in data
    assert "links" in data


def test_honey_payout_state_persists_per_session(client, merchant_auth_headers, db_session):
    session_id = str(NORMAL_SESSION_ID)
    identity_id = str(TEST_USER_ID)
    initial_world = bootstrap(session_id, identity_id)
    provider_invocations_before = mock_provider_instance.invocation_count
    profile_url = f"/v1/honey/merchant/profile?session_id={session_id}&identity_id={identity_id}"
    client.get(profile_url, headers=merchant_auth_headers)

    payout_response = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "amount": 1000,
            "recipient_email": "vendor@test.in",
        },
        headers={
            **merchant_auth_headers,
            "PayPal-Request-Id": "honey-state-test-001",
        },
    )
    assert payout_response.status_code == 200

    retry_response = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "amount": 1000,
            "recipient_email": "vendor@test.in",
        },
        headers={
            **merchant_auth_headers,
            "PayPal-Request-Id": "honey-state-test-001",
        },
    )
    assert retry_response.status_code == 200
    assert retry_response.json() == payout_response.json()

    conflicting_retry = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "amount": 1200,
            "recipient_email": "attacker@example.in",
        },
        headers={
            **merchant_auth_headers,
            "PayPal-Request-Id": "honey-state-test-001",
        },
    )
    assert conflicting_retry.status_code == 409
    recipient_conflict = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "amount": 1000,
            "recipient_email": "different-recipient@example.in",
        },
        headers={
            **merchant_auth_headers,
            "PayPal-Request-Id": "honey-state-test-001",
        },
    )
    assert recipient_conflict.status_code == 409

    profile = client.get(profile_url, headers=merchant_auth_headers).json()
    payouts = client.get(
        f"/v1/honey/payouts?session_id={session_id}&identity_id={identity_id}",
        headers=merchant_auth_headers,
    ).json()
    transactions = client.get(
        f"/v1/honey/transactions?session_id={session_id}&identity_id={identity_id}",
        headers=merchant_auth_headers,
    ).json()

    assert profile["balance"]["amount"] == initial_world["balance"]["amount"] - 1000
    assert payouts["total"] == 1
    assert (
        payouts["items"][0]["payout_batch_id"]
        == payout_response.json()["batch_header"]["payout_batch_id"]
    )
    assert transactions["items"][0]["id"] == payout_response.json()["items"][0]["transaction_id"]
    saved_world = db_session.get(HoneyWorkspaceState, session_id).world
    assert any(item["email"] == "vendor@test.in" for item in saved_world["payees"])
    assert db_session.query(HoneyMerchantProfile).filter_by(session_id=session_id).count() == 1
    assert db_session.query(HoneyBalance).filter_by(session_id=session_id).count() == 1
    assert db_session.query(HoneyCustomer).filter_by(session_id=session_id).count() == len(
        initial_world["customers"]
    )
    customer_rows = db_session.query(HoneyCustomer).filter_by(session_id=session_id).all()
    assert all(row.identity_id == identity_id and row.synthetic for row in customer_rows)
    assert db_session.query(HoneyInvoice).filter_by(session_id=session_id).count() == len(
        initial_world["invoices"]
    )
    assert db_session.query(HoneyTransaction).filter_by(session_id=session_id).count() == len(
        saved_world["transactions"]
    )
    assert db_session.query(HoneyPayout).filter_by(session_id=session_id).count() == 1
    assert db_session.query(HoneyPayee).filter_by(session_id=session_id).count() == len(
        saved_world["payees"]
    )
    assert db_session.query(HoneyApiCredential).filter_by(session_id=session_id).count() == len(
        initial_world["api_credentials"]
    )
    assert db_session.query(HoneyActivityLog).filter_by(session_id=session_id).count() >= 4
    assert mock_provider_instance.invocation_count == provider_invocations_before


def test_honey_workspace_cannot_be_rebound_to_another_identity(client, merchant_auth_headers):
    session_id = str(NORMAL_SESSION_ID)
    first_identity_id = str(TEST_USER_ID)
    second_identity_id = str(uuid.uuid4())

    first = client.get(
        f"/v1/honey/merchant/profile?session_id={session_id}&identity_id={first_identity_id}",
        headers=merchant_auth_headers,
    )
    second = client.get(
        f"/v1/honey/merchant/profile?session_id={session_id}&identity_id={second_identity_id}",
        headers=merchant_auth_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 403


def test_honey_canary_issuance_is_repeatable(client, merchant_auth_headers, db_session):
    session_id = str(NORMAL_SESSION_ID)
    identity_id = str(TEST_USER_ID)
    url = f"/v1/honey/developer/apps?session_id={session_id}&identity_id={identity_id}"

    first = client.get(url, headers=merchant_auth_headers)
    second = client.get(url, headers=merchant_auth_headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    # Canary secrets are no longer exposed in the apps list
    assert all(app["client_secret"] == "HIDDEN" for app in first.json()["items"])

    export = client.get(
        f"/v1/honey/invoices/export?session_id={session_id}&identity_id={identity_id}&format=json",
        headers=merchant_auth_headers,
    )
    assert export.status_code == 200
    invoice_canary = (
        db_session.query(CanaryRecord)
        .filter_by(session_id=uuid.UUID(session_id), kind="invoice_export")
        .one()
    )
    assert {item["reference"] for item in export.json()["items"]} == {invoice_canary.tag}


def test_canary_reveal_isolates_session_and_seals_incident(
    client, merchant_auth_headers, db_session
):
    session_id = str(NORMAL_SESSION_ID)
    identity_id = str(TEST_USER_ID)
    # First call apps endpoint to trigger canary issuance
    apps_url = f"/v1/honey/developer/apps?session_id={session_id}&identity_id={identity_id}"
    client.get(apps_url, headers=merchant_auth_headers)
    # Get the real canary secret from the database (not exposed via API)
    api_canary = (
        db_session.query(CanaryRecord)
        .filter_by(session_id=uuid.UUID(session_id), kind="api_credential")
        .one()
    )
    secret = api_canary.secret_value

    # Submitting a canary secret to any honey endpoint triggers middleware detection
    response = client.post(
        "/v1/honey/developer/credentials/reveal",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "client_secret": secret,
        },
        headers=merchant_auth_headers,
    )
    # Middleware detects canary and returns 403 before reaching the endpoint
    assert response.status_code == 403
    assert "canary" not in response.text.lower()

    session = db_session.get(SessionRecord, NORMAL_SESSION_ID)
    assert session.trust_level == "ISOLATED"
    assert session.risk_score == 100
    assert session.status == "revoked"
    incident = (
        db_session.query(IncidentRecord)
        .filter_by(session_id=NORMAL_SESSION_ID, trigger_reason="CANARY_INTERACTION")
        .first()
    )
    assert incident is not None
    assert incident.sealed_at is not None


def test_canary_from_another_session_cannot_isolate_target_session(
    client, merchant_auth_headers, db_session
):
    source_session_id = str(NORMAL_SESSION_ID)
    target_session_id = str(uuid.UUID("33333333-3333-3333-3333-333333333333"))
    identity_id = str(TEST_USER_ID)
    # First call apps endpoint for source session to trigger canary issuance
    client.get(
        "/v1/honey/developer/apps",
        params={"session_id": source_session_id, "identity_id": identity_id},
        headers=merchant_auth_headers,
    )
    # Get the real canary secret from the source session's database record
    api_canary = (
        db_session.query(CanaryRecord)
        .filter_by(session_id=uuid.UUID(source_session_id), kind="api_credential")
        .one()
    )
    secret = api_canary.secret_value

    # Attempt to use source session's canary with target session's ID
    response = client.post(
        "/v1/honey/developer/credentials/reveal",
        json={
            "session_id": target_session_id,
            "identity_id": identity_id,
            "client_secret": secret,
        },
        headers=merchant_auth_headers,
    )
    # Middleware detects canary but observes session_id mismatch
    # Cross-session reuse is logged but does NOT isolate the target session
    # The canary belongs to source_session, so source_session would be contained if sessions matched
    # Since observed session (target) != canary session (source), no hit is returned
    assert response.status_code == 200  # No canary hit for cross-session reuse

    # Target session should remain unaffected
    target_session = db_session.get(SessionRecord, uuid.UUID(target_session_id))
    assert target_session.status == "active"
    assert target_session.trust_level == "RESTRICTED"
    assert (
        db_session.query(IncidentRecord)
        .filter_by(session_id=uuid.UUID(target_session_id), trigger_reason="CANARY_INTERACTION")
        .count()
        == 0
    )
    # Source session's canary should remain armed (not triggered by cross-session attempt)
    canary = (
        db_session.query(CanaryRecord)
        .filter_by(session_id=uuid.UUID(source_session_id), kind="api_credential")
        .one()
    )
    assert canary.armed is True


def test_honey_no_leakage(client, merchant_auth_headers):
    sid = str(NORMAL_SESSION_ID)
    iid = str(TEST_USER_ID)
    requests = [
        ("get", f"/v1/honey/merchant/profile?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/customers?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/invoices?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/invoices/export?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/transactions?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/payouts?session_id={sid}&identity_id={iid}", None),
        ("get", f"/v1/honey/developer/apps?session_id={sid}&identity_id={iid}", None),
        (
            "post",
            "/v1/honey/payouts",
            {"session_id": sid, "identity_id": iid, "amount": 10},
        ),
    ]
    for method, url, body in requests:
        if method == "get":
            response = client.get(url, headers=merchant_auth_headers)
        else:
            response = client.post(url, json=body, headers=merchant_auth_headers)
        assert response.status_code == 200
        text = response.text.lower()
        for forbidden in ["honey", "fake", "decoy", "canary", "demo", "synthetic", "test"]:
            assert forbidden not in text, (url, forbidden)


def test_honey_routes_require_authentication_and_owned_session(
    client, merchant_auth_headers, other_merchant_auth_headers
):
    protected_routes = [
        (
            "/v1/honey/developer/apps",
            {"session_id": str(NORMAL_SESSION_ID), "identity_id": str(TEST_USER_ID)},
        ),
        (
            "/v1/merchant/merchant-info",
            {"session_id": str(NORMAL_SESSION_ID), "identity_id": str(TEST_USER_ID)},
        ),
    ]
    for path, params in protected_routes:
        response = client.get(path, params=params)
        assert response.status_code == 401

    cross_merchant = client.get(
        "/v1/honey/developer/apps",
        params={"session_id": str(NORMAL_SESSION_ID), "identity_id": str(TEST_USER_ID)},
        headers=other_merchant_auth_headers,
    )
    assert cross_merchant.status_code == 403
