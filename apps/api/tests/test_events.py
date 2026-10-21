import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tests.conftest import NORMAL_SESSION_ID


def test_valid_event_ingestion(client: TestClient, merchant_auth_headers: dict):
    now = datetime.now(timezone.utc)
    payload = {
        "event_type": "behavioral.keystroke",
        "session_id": str(NORMAL_SESSION_ID),
        "occurred_at": now.isoformat(),
        "device_id": "test-device-fingerprint-123",
        "ip_address": "192.168.1.100",
        "action": "input_flight_time",
        "metadata": {
            "key_code": 65,
            "flight_duration_ms": 112,
            "dwell_time_ms": 45,
        },
        "idempotency_key": "event-key-" + str(uuid.uuid4()),
    }

    response = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "accepted"
    assert data["session_id"] == str(NORMAL_SESSION_ID)
    assert "event_id" in data
    assert "server_received_at" in data


def test_event_ingestion_ownership_mismatch_rejected(
    client: TestClient, other_merchant_auth_headers: dict
):
    """
    Critical Invariant:
    A merchant caller cannot ingest events into a session belonging to another merchant.
    Must return 403 Forbidden.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "event_type": "navigation.pageview",
        "session_id": str(NORMAL_SESSION_ID),  # belongs to TEST_MERCHANT_ID
        "occurred_at": now.isoformat(),
        "action": "view_payouts",
        "metadata": {"path": "/payouts"},
    }

    response = client.post("/v1/events", json=payload, headers=other_merchant_auth_headers)
    assert response.status_code == 403
    error_data = response.json()["error"]
    assert error_data["code"] == "SESSION_OWNERSHIP_MISMATCH"


def test_event_ingestion_nonexistent_session_rejected(
    client: TestClient, merchant_auth_headers: dict
):
    now = datetime.now(timezone.utc)
    fake_session_id = str(uuid.uuid4())
    payload = {
        "event_type": "session.heartbeat",
        "session_id": fake_session_id,
        "occurred_at": now.isoformat(),
        "action": "ping",
        "metadata": {},
    }

    response = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_event_ingestion_future_timestamp_rejected(client: TestClient, merchant_auth_headers: dict):
    far_future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    payload = {
        "event_type": "auth.login",
        "session_id": str(NORMAL_SESSION_ID),
        "occurred_at": far_future,
        "action": "login",
        "metadata": {},
    }

    response = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 422


def test_event_ingestion_unbounded_metadata_rejected(
    client: TestClient, merchant_auth_headers: dict
):
    # Over 25 keys constraint
    oversized_metadata = {f"key_{i}": f"value_{i}" for i in range(30)}
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_type": "session.heartbeat",
        "session_id": str(NORMAL_SESSION_ID),
        "occurred_at": now,
        "action": "ping",
        "metadata": oversized_metadata,
    }

    response = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 422
