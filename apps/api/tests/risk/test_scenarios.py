"""End to end replay of the eight attack scenario fixtures.

Every scenario is replayed through the public HTTP API so that the whole
pipeline (event ingestion -> risk engine -> session trust state) is exercised.
The expected values live in the fixture files, which keeps the assertions free
of scenario specific engine logic.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.risk.timezones import resolve_timezone

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SCENARIO_PATHS = sorted(FIXTURE_DIR.glob("scenario_*.json"))
SCENARIOS = [json.loads(path.read_text(encoding="utf-8")) for path in SCENARIO_PATHS]
SCENARIO_IDS = [scenario["scenario_id"] for scenario in SCENARIOS]


def _tz():
    return resolve_timezone(settings.RISK_DEFAULT_TIMEZONE)


def _anchor_date():
    now = datetime.now(timezone.utc).astimezone(_tz())
    return (now - timedelta(days=7)).date()


def _event_time(day_offset: int, local_time: str) -> datetime:
    date = _anchor_date() + timedelta(days=day_offset)
    hour, minute = (int(part) for part in local_time.split(":"))
    naive = datetime(date.year, date.month, date.day, hour, minute)
    return naive.replace(tzinfo=_tz()).astimezone(timezone.utc)


def _shift(local_time: str, minutes: int) -> str:
    hour, minute = (int(part) for part in local_time.split(":"))
    total = (hour * 60 + minute + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _expand(entries: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for entry in entries:
        repeat = int(entry.get("repeat", 1))
        spacing = int(entry.get("repeat_spacing_minutes", 1))
        for index in range(repeat):
            item = dict(entry)
            item["local_time"] = _shift(entry["local_time"], index * spacing)
            expanded.append(item)
    return expanded


def _event_payload(scenario_id: str, session_id: str, event: dict, index: int) -> dict:
    occurred = _event_time(int(event.get("day_offset", 0)), event["local_time"])
    metadata: dict = {}
    if event.get("location"):
        metadata["location"] = event["location"]
    if event.get("amount") is not None:
        metadata["amount"] = event["amount"]
    if event.get("recipient"):
        metadata["recipient_email"] = event["recipient"]
    if event.get("canary_token"):
        metadata["canary_token"] = event["canary_token"]
    return {
        "event_type": event["event_type"],
        "session_id": str(session_id),
        "occurred_at": occurred.isoformat(),
        "device_id": event.get("device_id"),
        "ip_address": event.get("ip_address"),
        "action": event["action"],
        "metadata": metadata,
        "idempotency_key": f"{scenario_id}-{index}-{uuid.uuid4().hex}",
    }


def _create_session(client: TestClient, headers: dict, device_id: str, ip_address: str | None):
    body = {"device_fingerprint": device_id}
    if ip_address:
        body["ip_address"] = ip_address
    res = client.post("/v1/sessions", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["session_id"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
def test_scenario_replay_matches_expected_escalation(
    client: TestClient,
    merchant_auth_headers: dict,
    scenario: dict,
):
    identity = scenario["identity"]
    scenario_id = scenario["scenario_id"]

    baseline_session_id = _create_session(
        client,
        merchant_auth_headers,
        identity["device_id"],
        identity.get("ip_address"),
    )

    for index, event in enumerate(_expand(scenario["baseline"])):
        payload = _event_payload(scenario_id, baseline_session_id, event, index)
        res = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
        assert res.status_code == 201, res.text

    # The baseline must have established a non provisional twin, otherwise the
    # scenario would not exercise the contract weights.
    user_id = merchant_auth_headers["X-Dev-User-Id"]
    twin_res = client.get(f"/v1/identities/{user_id}/twin", headers=merchant_auth_headers)
    assert twin_res.status_code == 200, twin_res.text
    twin = twin_res.json()
    assert twin["is_provisional"] is False
    assert twin["sample_count"] >= settings.RISK_MIN_SAMPLES

    attack_device = scenario["attack"][0].get("device_id", identity["device_id"])
    attack_session_id = _create_session(
        client,
        merchant_auth_headers,
        attack_device,
        scenario["attack"][0].get("ip_address"),
    )

    for index, event in enumerate(scenario["attack"]):
        payload = _event_payload(scenario_id, attack_session_id, event, 1000 + index)
        res = client.post("/v1/events", json=payload, headers=merchant_auth_headers)
        assert res.status_code == 201, res.text
        data = res.json()
        expected = event["expected"]

        assert data["risk_score"] == expected["risk_score"], (
            f"{scenario_id} step {event['step']}: {data['risk_signals']}"
        )
        assert data["trust_level"] == expected["trust_level"], (
            f"{scenario_id} step {event['step']}: {data['reason_codes']}"
        )
        for signal in expected["signals"]:
            assert signal in data["risk_signals"], f"{scenario_id} missing {signal}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
def test_scenario_attack_never_teaches_the_twin(
    client: TestClient,
    merchant_auth_headers: dict,
    scenario: dict,
):
    """Anomalous activity must never be learned into the identity twin."""
    identity = scenario["identity"]
    scenario_id = scenario["scenario_id"]
    expect_learning = bool(scenario.get("expect_attack_learning", False))

    baseline_session_id = _create_session(
        client,
        merchant_auth_headers,
        identity["device_id"],
        identity.get("ip_address"),
    )
    for index, event in enumerate(_expand(scenario["baseline"])):
        payload = _event_payload(scenario_id, baseline_session_id, event, index)
        client.post("/v1/events", json=payload, headers=merchant_auth_headers)

    user_id = merchant_auth_headers["X-Dev-User-Id"]
    before = client.get(f"/v1/identities/{user_id}/twin", headers=merchant_auth_headers).json()

    attack_device = scenario["attack"][0].get("device_id", identity["device_id"])
    attack_session_id = _create_session(
        client,
        merchant_auth_headers,
        attack_device,
        scenario["attack"][0].get("ip_address"),
    )
    for index, event in enumerate(scenario["attack"]):
        payload = _event_payload(scenario_id, attack_session_id, event, 2000 + index)
        client.post("/v1/events", json=payload, headers=merchant_auth_headers)

    after = client.get(f"/v1/identities/{user_id}/twin", headers=merchant_auth_headers).json()
    assert after["confirmed_device_count"] == before["confirmed_device_count"]
    assert after["confirmed_location_count"] == before["confirmed_location_count"]

    if expect_learning:
        # Benign activity keeps the twin fresh, so the sample count grows.
        assert after["sample_count"] == before["sample_count"] + len(scenario["attack"])
    else:
        assert after["sample_count"] == before["sample_count"]
