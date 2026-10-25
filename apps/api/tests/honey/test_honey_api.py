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
from tests.conftest import NORMAL_SESSION_ID


def test_honey_payout_shape(client, merchant_auth_headers):
    # Call honey payout directly via test client by mounting logic is via app; but easier to call endpoint
    resp = client.post(
        "/v1/honey/payouts",
        json={
            "session_id": str(uuid.uuid4()),
            "identity_id": str(uuid.uuid4()),
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
    session_id = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())
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
    session_id = str(uuid.uuid4())
    first_identity_id = str(uuid.uuid4())
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
    assert second.status_code == 409


def test_honey_canary_issuance_is_repeatable(client, merchant_auth_headers, db_session):
    session_id = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())
    url = f"/v1/honey/developer/apps?session_id={session_id}&identity_id={identity_id}"

    first = client.get(url, headers=merchant_auth_headers)
    second = client.get(url, headers=merchant_auth_headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    api_canary = (
        db_session.query(CanaryRecord)
        .filter_by(session_id=uuid.UUID(session_id), kind="api_credential")
        .one()
    )
    assert all(app["client_secret"] == api_canary.secret_value for app in first.json()["items"])

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
    identity_id = str(uuid.uuid4())
    apps_url = f"/v1/honey/developer/apps?session_id={session_id}&identity_id={identity_id}"
    issued = client.get(apps_url, headers=merchant_auth_headers)
    assert issued.status_code == 200
    secret = issued.json()["items"][0]["client_secret"]

    response = client.post(
        "/v1/honey/developer/credentials/reveal",
        json={
            "session_id": session_id,
            "identity_id": identity_id,
            "client_secret": secret,
        },
        headers=merchant_auth_headers,
    )
    assert response.status_code == 200
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


def test_honey_no_leakage(client, merchant_auth_headers):
    sid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
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
