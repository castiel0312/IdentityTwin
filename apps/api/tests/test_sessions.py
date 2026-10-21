from fastapi.testclient import TestClient

from tests.conftest import NORMAL_SESSION_ID


def test_list_sessions_scoped_to_merchant(client: TestClient, merchant_auth_headers: dict):
    response = client.get("/v1/sessions", headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    # Check session structure
    first_session = data["items"][0]
    assert "session_id" in first_session
    assert "trust_level" in first_session
    assert "risk_score" in first_session


def test_get_session_by_id(client: TestClient, merchant_auth_headers: dict):
    response = client.get(f"/v1/sessions/{NORMAL_SESSION_ID}", headers=merchant_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(NORMAL_SESSION_ID)
    assert data["trust_level"] == "NORMAL"


def test_get_session_cross_merchant_forbidden(
    client: TestClient, other_merchant_auth_headers: dict
):
    response = client.get(f"/v1/sessions/{NORMAL_SESSION_ID}", headers=other_merchant_auth_headers)
    assert response.status_code == 403


def test_create_session_initializes_normal_trust(client: TestClient, merchant_auth_headers: dict):
    payload = {
        "device_fingerprint": "new-test-device-fp",
        "ip_address": "127.0.0.1",
    }
    response = client.post("/v1/sessions", json=payload, headers=merchant_auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["trust_level"] == "NORMAL"
    assert data["risk_score"] == 0.0
    assert data["status"] == "active"
