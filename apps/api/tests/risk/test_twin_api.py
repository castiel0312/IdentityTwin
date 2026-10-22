"""API level tests for the behavioural identity twin viewer."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def _now() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


def _create_session(
    client: TestClient, headers: dict, device_id: str, ip_address: str | None = None
) -> str:
    body: dict = {"device_fingerprint": device_id}
    if ip_address:
        body["ip_address"] = ip_address
    res = client.post("/v1/sessions", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["session_id"]


def _post_event(client: TestClient, headers: dict, session_id: str, index: int) -> None:
    res = client.post(
        "/v1/events",
        json={
            "event_type": "auth.login",
            "session_id": session_id,
            "occurred_at": _now(),
            "device_id": "device-alpha",
            "ip_address": "203.0.113.10",
            "action": "auth.login",
            "metadata": {"location": "Bengaluru"},
            "idempotency_key": f"twin-api-{index}-{uuid.uuid4().hex}",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text


def test_twin_profile_is_returned_for_a_known_identity(
    client: TestClient, merchant_auth_headers: dict
):
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    session_id = _create_session(client, merchant_auth_headers, "device-alpha")
    for index in range(12):
        _post_event(client, merchant_auth_headers, session_id, index)

    res = client.get(f"/v1/identities/{user_id}/twin", headers=merchant_auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["user_id"] == user_id
    assert body["merchant_id"] == merchant_auth_headers["X-Dev-Merchant-Id"]
    assert body["sample_count"] >= settings.RISK_MIN_SAMPLES
    assert body["is_provisional"] is False
    assert body["confirmed_device_count"] == 1
    assert body["confirmed_location_count"] == 1
    assert body["active_hours"]
    assert body["hour_histogram"]
    # Raw identifiers are never exposed, only the salted digests.
    assert "device-alpha" not in body["device_fingerprints"]
    assert all(len(item) == 64 for item in body["device_fingerprints"])
    assert body["location_buckets"] == ["BENGALURU"]


def test_twin_profile_reports_a_missing_twin(client: TestClient, merchant_auth_headers: dict):
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    res = client.get(f"/v1/identities/{user_id}/twin", headers=merchant_auth_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "TWIN_NOT_FOUND"


def test_twin_profile_rejects_an_unknown_identity(client: TestClient, merchant_auth_headers: dict):
    res = client.get(f"/v1/identities/{uuid.uuid4()}/twin", headers=merchant_auth_headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "IDENTITY_NOT_FOUND"


def test_twin_profile_is_merchant_scoped(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
):
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    session_id = _create_session(client, merchant_auth_headers, "device-alpha")
    for index in range(12):
        _post_event(client, merchant_auth_headers, session_id, index)

    res = client.get(f"/v1/identities/{user_id}/twin", headers=other_merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "IDENTITY_OWNERSHIP_MISMATCH"


def test_twin_profile_can_compare_a_live_session(client: TestClient, merchant_auth_headers: dict):
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    baseline = _create_session(client, merchant_auth_headers, "device-alpha")
    for index in range(12):
        _post_event(client, merchant_auth_headers, baseline, index)

    attack = _create_session(client, merchant_auth_headers, "device-attacker", "198.51.100.7")
    res = client.post(
        "/v1/events",
        json={
            "event_type": "auth.login",
            "session_id": attack,
            "occurred_at": _now(),
            "device_id": "device-attacker",
            "ip_address": "198.51.100.7",
            "action": "auth.login",
            "metadata": {"location": "Delhi"},
            "idempotency_key": f"twin-attack-{uuid.uuid4().hex}",
        },
        headers=merchant_auth_headers,
    )
    assert res.status_code == 201, res.text

    twin_res = client.get(
        f"/v1/identities/{user_id}/twin",
        params={"compare_session_id": attack},
        headers=merchant_auth_headers,
    )
    assert twin_res.status_code == 200, twin_res.text
    deviation = twin_res.json()["deviation"]

    assert deviation["session_id"] == attack
    assert deviation["is_new_device"] is True
    assert deviation["is_new_location"] is True
    assert "NEW_DEVICE" in deviation["risk_signals"]
    assert deviation["risk_score"] > 0
    assert deviation["reason_codes"]


def test_twin_profile_rejects_a_foreign_compare_session(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
):
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    baseline = _create_session(client, merchant_auth_headers, "device-alpha")
    for index in range(12):
        _post_event(client, merchant_auth_headers, baseline, index)

    other_session = _create_session(client, other_merchant_auth_headers, "device-foreign")
    res = client.get(
        f"/v1/identities/{user_id}/twin",
        params={"compare_session_id": other_session},
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "SESSION_OWNERSHIP_MISMATCH"


def test_twin_profile_requires_authentication(client: TestClient):
    user_id = "11111111-1111-1111-1111-111111111111"
    res = client.get(f"/v1/identities/{user_id}/twin")
    assert res.status_code in (401, 403)


@pytest.mark.parametrize(
    "path",
    ["/v1/identities/{user_id}/twin", "/v1/identities/{user_id}/twin?compare_session_id=x"],
)
def test_twin_endpoint_is_published_in_the_openapi_contract(client: TestClient, path: str):
    schema = client.get("/openapi.json").json()
    assert "/v1/identities/{id}/twin" in schema["paths"]
    operation = schema["paths"]["/v1/identities/{id}/twin"]["get"]
    assert operation["tags"] == ["Behavioral Identity Twin (Person 2 - Risk Intelligence)"]
    assert "compare_session_id" in {parameter["name"] for parameter in operation["parameters"]}
