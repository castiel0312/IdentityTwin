"""Contract tests for the read-only operational projections.

These endpoints are deliberately read-only. The tests assert merchant scoping,
server-derived projections and the safety boundaries the console relies on.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.evidence.hashchain import EvidenceChain
from app.honey.bootstrap import get_or_create_world
from app.honey.canary import CanaryRegistryService
from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
)
from app.models.event import SecurityEvent
from app.models.idempotency import IdempotencyRecord
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.principal import User
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.models.twin import BehavioralTwin, SessionRiskStateRecord
from app.schemas.sessions import TrustLevel
from tests.conftest import (
    DECOY_SESSION_ID,
    OTHER_MERCHANT_ID,
    RESTRICTED_SESSION_ID,
    TEST_INCIDENT_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def _seed_payout(db: Session, *, recipient: str) -> PayoutRequestRecord:
    now = datetime.now(timezone.utc)
    decision = RiskDecisionRecord(
        decision_id=uuid.uuid4(),
        session_id=RESTRICTED_SESSION_ID,
        merchant_id=TEST_MERCHANT_ID,
        risk_score=72.5,
        trust_level=TrustLevel.DECOY.value,
        action="DECOY_FORWARD",
        routing_destination="DECOY_HONEY",
        reason_codes=["NEW_DEVICE", "DECOY_ROUTED_TO_HONEY"],
        risk_signals={"NEW_DEVICE": 18.0},
        evaluated_at=now,
    )
    db.add(decision)
    db.flush()
    payout = PayoutRequestRecord(
        payout_id=uuid.uuid4(),
        decision_id=decision.decision_id,
        session_id=RESTRICTED_SESSION_ID,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        recipient_email=recipient,
        amount=1234.56,
        currency="USD",
        reference_note="read-model test",
        idempotency_key=f"idem-{uuid.uuid4().hex}",
        status="decoy_completed",
        provider_name="honey_synthetic_decoy",
        provider_reference="decoy-ref",
        provider_payload={"authorization": "must-not-leak", "batch_status": "SUCCESS"},
        executed_at=now,
    )
    db.add(payout)
    db.add(
        IdempotencyRecord(
            idempotency_key=payout.idempotency_key,
            merchant_id=TEST_MERCHANT_ID,
            request_hash="a" * 64,
            status="completed",
            response_code=200,
            response_payload={},
            expires_at=now + timedelta(hours=1),
        )
    )
    db.commit()
    db.refresh(payout)
    return payout


def test_payout_list_and_detail_are_merchant_scoped_and_redacted(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    recipient = f"ledger-{uuid.uuid4().hex}@example.com"
    payout = _seed_payout(db_session, recipient=recipient)

    response = client.get(
        "/v1/payouts",
        params={"q": recipient, "page_size": 10},
        headers=merchant_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["payout_id"] == str(payout.payout_id)
    assert item["risk_score"] == 72.5
    assert item["trust_level"] == "DECOY"

    detail = client.get(
        f"/v1/payouts/{payout.payout_id}", headers=merchant_auth_headers
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["request"]["recipient_email"] == recipient
    assert payload["decision"]["signal_weights"]["NEW_DEVICE"] == 18.0
    assert payload["provider"]["payload"]["authorization"] == "[REDACTED]"
    assert payload["step_up"]["required"] is False
    assert any(item["key"] == "provider" for item in payload["timeline"])

    hidden = client.get(
        f"/v1/payouts/{payout.payout_id}", headers=other_merchant_auth_headers
    )
    assert hidden.status_code == 404


def test_analytics_overview_is_range_bounded(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    payout = _seed_payout(db_session, recipient=f"analytics-{uuid.uuid4().hex}@example.com")
    now = datetime.now(timezone.utc)
    response = client.get(
        "/v1/analytics/overview",
        params={
            "start": (now - timedelta(minutes=10)).isoformat(),
            "end": (now + timedelta(minutes=1)).isoformat(),
        },
        headers=merchant_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is False
    assert body["totals"]["payouts_total"] >= 1
    assert body["totals"]["decoy_routed"] >= 1
    assert len(body["timeline"]) >= 1
    assert sum(bucket["payouts"] for bucket in body["timeline"]) >= 1
    assert any(
        item["payout_id"] == str(payout.payout_id)
        for item in body["recent_activity"]
        if item["payout_id"]
    )


def test_system_context_never_projects_secrets(
    client: TestClient,
    merchant_auth_headers: dict,
):
    from app.core.config import settings

    response = client.get("/v1/system/context", headers=merchant_auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principal"]["merchant_id"] == str(TEST_MERCHANT_ID)
    assert body["auth"]["oidc_configured"] is False
    assert body["risk"]["sequence_window_seconds"] == 1800
    serialized = json.dumps(body).lower()
    assert "client_secret" not in serialized
    assert "authorization" not in serialized
    if settings.PAYPAL_CLIENT_SECRET:
        assert settings.PAYPAL_CLIENT_SECRET.lower() not in serialized


def test_identity_list_and_detail(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    twin = BehavioralTwin(
        twin_id=uuid.uuid4(),
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        sample_count=3,
        confirmed_devices=["sha256:device"],
        confirmed_locations=["203.0.113.0/24"],
        payee_observations={"payee-1": 1},
        hour_histogram={"9": 4, "10": 2},
        amount_count=4,
        total_amount=900.0,
    )
    db_session.add(twin)
    db_session.commit()

    listing = client.get("/v1/identities", headers=merchant_auth_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] >= 1
    item = next(
        row for row in body["items"] if row["user_id"] == str(TEST_USER_ID)
    )
    assert item["twin"]["is_provisional"] is True
    assert item["twin"]["sample_count"] == 3

    detail = client.get(
        f"/v1/identities/{TEST_USER_ID}", headers=merchant_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["identity"]["user_id"] == str(TEST_USER_ID)


def test_session_activity_projects_events_and_sequences(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    now = datetime.now(timezone.utc)
    db_session.add(
        SecurityEvent(
            event_id=uuid.uuid4(),
            session_id=RESTRICTED_SESSION_ID,
            merchant_id=TEST_MERCHANT_ID,
            user_id=TEST_USER_ID,
            event_type="payout",
            occurred_at=now,
            device_id="sha256:device",
            ip_address="203.0.113.9",
            action="payout.execute",
            metadata_payload={"amount": 100},
        )
    )
    db_session.add(
        SessionRiskStateRecord(
            state_id=uuid.uuid4(),
            session_id=RESTRICTED_SESSION_ID,
            merchant_id=TEST_MERCHANT_ID,
            user_id=TEST_USER_ID,
            current_score=45.0,
            raw_points_sum=50.0,
            decay_points_total=5.0,
            contributions=[
                {
                    "name": "NEW_DEVICE",
                    "points": 18.0,
                    "reason_code": "NEW_DEVICE",
                    "kind": "signal",
                    "occurred_at": now.isoformat(),
                }
            ],
            latched_signals=["NEW_DEVICE"],
            sequence_markers=[
                {
                    "marker_id": "marker-1",
                    "sequence_type": "PAYEE_ADD_THEN_PAYOUT",
                    "recipient_hash": "hash",
                    "occurred_at": now.isoformat(),
                }
            ],
            last_evaluated_at=now,
        )
    )
    db_session.commit()

    response = client.get(
        f"/v1/sessions/{RESTRICTED_SESSION_ID}/activity",
        headers=merchant_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk_ledger"]["current_score"] == 45.0
    assert body["sequences"]["window_seconds"] == 1800
    assert body["sequences"]["markers"][0]["sequence_type"] == "PAYEE_ADD_THEN_PAYOUT"
    assert body["devices"] == ["sha256:device"]


def test_incident_filters_and_action_availability(
    client: TestClient,
    merchant_auth_headers: dict,
    analyst_auth_headers: dict,
):
    listing = client.get(
        "/v1/incidents",
        params={"q": "Anomaly", "sort": "-risk_score"},
        headers=merchant_auth_headers,
    )
    assert listing.status_code == 200, listing.text
    assert any(
        item["incident_id"] == str(TEST_INCIDENT_ID)
        for item in listing.json()["items"]
    )

    merchant_actions = client.get(
        f"/v1/incidents/{TEST_INCIDENT_ID}/actions",
        headers=merchant_auth_headers,
    )
    assert merchant_actions.status_code == 200
    assert all(not action["allowed"] for action in merchant_actions.json()["actions"])

    analyst_actions = client.get(
        f"/v1/incidents/{TEST_INCIDENT_ID}/actions",
        headers=analyst_auth_headers,
    )
    assert analyst_actions.status_code == 200
    approve = next(
        action
        for action in analyst_actions.json()["actions"]
        if action["action"] == "approve"
    )
    assert approve["allowed"] is True

    seal = client.get(
        f"/v1/incidents/{TEST_INCIDENT_ID}/seal", headers=merchant_auth_headers
    )
    assert seal.status_code == 200
    assert seal.json()["sealed"] is False


def test_agent_reads_and_error_catalog(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    now = datetime.now(timezone.utc)
    agent = AgentRegistration(
        agent_id=uuid.uuid4(),
        merchant_id=TEST_MERCHANT_ID,
        display_name="Procurement Copilot",
        agent_type="procurement",
        vendor="Example AI",
        scopes=["payout:execute"],
        status="active",
        max_payout_amount=5000.0,
        is_active=True,
    )
    grant = AgentAuthorizationGrant(
        grant_id=uuid.uuid4(),
        agent_id=agent.agent_id,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=RESTRICTED_SESSION_ID,
        scopes=["payout:execute"],
        max_amount=1000.0,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(agent)
    db_session.flush()
    db_session.add(grant)
    audit = AgenticCommerceAudit(
        audit_id=uuid.uuid4(),
        agent_id=agent.agent_id,
        grant_id=grant.grant_id,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=RESTRICTED_SESSION_ID,
        payout_id=None,
        idempotency_key=f"agent-{uuid.uuid4().hex}",
        recipient_email="agent@example.com",
        amount=100.0,
        currency="USD",
        status="rejected",
        outcome="AGENT_AMOUNT_LIMIT_EXCEEDED",
        agent_context={"intent": "test"},
    )
    db_session.add(audit)
    db_session.commit()

    listing = client.get(
        "/v1/agents",
        headers=merchant_auth_headers,
        params={"q": "Procurement Copilot", "page_size": 100},
    )
    assert listing.status_code == 200, listing.text
    item = next(
        row for row in listing.json()["items"] if row["agent_id"] == str(agent.agent_id)
    )
    assert item["active_grants"] == 1
    assert item["audit_attempts"] == 1

    detail = client.get(
        f"/v1/agents/{agent.agent_id}", headers=merchant_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["grants"][0]["status"] == "active"

    audit_list = client.get(
        "/v1/agents/audit",
        headers=merchant_auth_headers,
        params={"agent_id": str(agent.agent_id), "status": "rejected", "page_size": 100},
    )
    assert audit_list.status_code == 200
    assert any(
        row["audit_id"] == str(audit.audit_id)
        for row in audit_list.json()["items"]
    )

    catalog = client.get(
        "/v1/agents/authorization-errors", headers=merchant_auth_headers
    )
    assert catalog.status_code == 200
    codes = {row["code"] for row in catalog.json()["errors"]}
    assert "AGENT_IDEMPOTENCY_KEY_CONFLICT" in codes
    assert "AGENT_AMOUNT_LIMIT_EXCEEDED" in codes

    hidden = client.get(
        f"/v1/agents/{agent.agent_id}", headers=other_merchant_auth_headers
    )
    assert hidden.status_code == 404


def test_evidence_seals_and_seal_range_verification(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    chain = EvidenceChain(db_session)
    chain.append(
        "login",
        {
            "type": "login",
            "session_id": str(RESTRICTED_SESSION_ID),
            "summary": "test login",
        },
    )
    chain.append(
        "payout",
        {
            "type": "payout",
            "session_id": str(RESTRICTED_SESSION_ID),
            "summary": "test payout",
            "authorization": "must-not-leak",
        },
    )
    sealed = chain.seal(TEST_INCIDENT_ID, RESTRICTED_SESSION_ID, TEST_MERCHANT_ID)
    seal_id = sealed["seal_id"]

    listing = client.get("/v1/evidence/seals", headers=merchant_auth_headers)
    assert listing.status_code == 200, listing.text
    assert any(item["seal_id"] == seal_id for item in listing.json()["items"])

    detail = client.get(
        f"/v1/evidence/seals/{seal_id}", headers=merchant_auth_headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["seal_verification"]["valid"] is True
    assert body["seal_verification"]["scope"] == "seal_range"
    assert body["entries"][1]["payload"]["authorization"] == "[REDACTED]"
    assert len(body["limitations"]) >= 3

    hidden = client.get(
        f"/v1/evidence/seals/{seal_id}", headers=other_merchant_auth_headers
    )
    assert hidden.status_code == 404


def test_evidence_seal_hides_interleaved_foreign_merchant_entries(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    foreign_user_id = uuid.uuid4()
    foreign_session_id = uuid.uuid4()
    foreign_incident_id = uuid.uuid4()
    db_session.add(
        User(
            user_id=foreign_user_id,
            merchant_id=OTHER_MERCHANT_ID,
            email=f"{foreign_user_id}@other.test",
            role="merchant",
        )
    )
    db_session.add(
        SessionRecord(
            session_id=foreign_session_id,
            user_id=foreign_user_id,
            merchant_id=OTHER_MERCHANT_ID,
            status="active",
        )
    )
    db_session.add(
        IncidentRecord(
            incident_id=foreign_incident_id,
            merchant_id=OTHER_MERCHANT_ID,
            session_id=foreign_session_id,
            title="Foreign tenant incident",
            description="Foreign tenant evidence test",
            trigger_reason="TEST",
        )
    )
    db_session.commit()

    chain = EvidenceChain(db_session)
    chain.append(
        "merchant_one_event",
        {
            "type": "merchant_one_event",
            "session_id": str(RESTRICTED_SESSION_ID),
            "merchant_id": str(TEST_MERCHANT_ID),
        },
    )
    chain.append(
        "merchant_two_event",
        {
            "type": "merchant_two_event",
            "session_id": str(foreign_session_id),
            "merchant_id": str(OTHER_MERCHANT_ID),
            "recipient": "private-recipient@other.test",
        },
    )
    chain.append(
        "merchant_one_followup",
        {
            "type": "merchant_one_followup",
            "session_id": str(RESTRICTED_SESSION_ID),
            "merchant_id": str(TEST_MERCHANT_ID),
        },
    )
    with pytest.raises(ValueError, match="incident, session and merchant"):
        chain.seal(TEST_INCIDENT_ID, RESTRICTED_SESSION_ID, OTHER_MERCHANT_ID)
    first_seal = chain.seal(TEST_INCIDENT_ID, RESTRICTED_SESSION_ID, TEST_MERCHANT_ID)
    second_seal = chain.seal(foreign_incident_id, foreign_session_id, OTHER_MERCHANT_ID)

    first_detail = client.get(
        f"/v1/evidence/seals/{first_seal['seal_id']}",
        headers=merchant_auth_headers,
    )
    assert first_detail.status_code == 200
    assert first_detail.json()["seal_verification"]["valid"] is True
    first_payloads = [entry["payload"] for entry in first_detail.json()["entries"]]
    assert all(payload.get("merchant_id") != str(OTHER_MERCHANT_ID) for payload in first_payloads)
    assert all(
        payload.get("recipient") != "private-recipient@other.test" for payload in first_payloads
    )

    reverse_cross_access = client.get(
        f"/v1/evidence/seals/{second_seal['seal_id']}",
        headers=merchant_auth_headers,
    )
    assert reverse_cross_access.status_code == 404
    foreign_detail = client.get(
        f"/v1/evidence/seals/{first_seal['seal_id']}",
        headers=other_merchant_auth_headers,
    )
    assert foreign_detail.status_code == 404


def test_honey_operator_projection_excludes_canary_secrets(
    client: TestClient,
    merchant_auth_headers: dict,
    other_merchant_auth_headers: dict,
    db_session: Session,
):
    world = get_or_create_world(
        db_session, str(DECOY_SESSION_ID), str(TEST_USER_ID)
    )
    issued = CanaryRegistryService(db_session).issue(
        str(DECOY_SESSION_ID), str(TEST_USER_ID), str(TEST_MERCHANT_ID)
    )
    secret = issued[0]["secret_value"]

    listing = client.get(
        "/v1/honey/operator/workspaces", headers=merchant_auth_headers
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    workspace = next(
        item
        for item in body["items"]
        if item["session_id"] == str(DECOY_SESSION_ID)
    )
    assert workspace["synthetic"] is True
    assert workspace["canary_count"] == 5
    assert secret not in listing.text
    assert world["merchant"]["name"] == workspace["merchant_name"]

    detail = client.get(
        f"/v1/honey/operator/workspaces/{DECOY_SESSION_ID}",
        headers=merchant_auth_headers,
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["workspace"]["synthetic"] is True
    assert secret not in detail.text
    assert len(detail_body["canaries"]) == 5
    assert detail_body["payees"]

    canaries = client.get(
        "/v1/honey/operator/canaries", headers=merchant_auth_headers
    )
    assert canaries.status_code == 200
    assert canaries.json()["total"] == 5
    assert "secret_value" not in canaries.text

    hidden = client.get(
        f"/v1/honey/operator/workspaces/{DECOY_SESSION_ID}",
        headers=other_merchant_auth_headers,
    )
    assert hidden.status_code == 404


def test_risk_decisions_and_config(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    now = datetime.now(timezone.utc)
    decision = RiskDecisionRecord(
        decision_id=uuid.uuid4(),
        session_id=RESTRICTED_SESSION_ID,
        merchant_id=TEST_MERCHANT_ID,
        risk_score=61.0,
        trust_level=TrustLevel.DECOY.value,
        action="DECOY_FORWARD",
        routing_destination="DECOY_HONEY",
        reason_codes=["NEW_DEVICE"],
        risk_signals={"NEW_DEVICE": 18.0},
        evaluated_at=now,
    )
    db_session.add(decision)
    db_session.commit()

    listing = client.get(
        "/v1/risk/decisions",
        params={"session_id": str(RESTRICTED_SESSION_ID)},
        headers=merchant_auth_headers,
    )
    assert listing.status_code == 200, listing.text
    assert any(
        item["decision_id"] == str(decision.decision_id)
        for item in listing.json()["items"]
    )

    detail = client.get(
        f"/v1/risk/decisions/{decision.decision_id}",
        headers=merchant_auth_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["decision"]["risk_score"] == 61.0
    assert any(
        signal["name"] == "NEW_DEVICE" and signal["weight"] == 18.0
        for signal in detail.json()["signals"]
    )

    config = client.get("/v1/risk/config", headers=merchant_auth_headers)
    assert config.status_code == 200
    assert config.json()["sequence_window_seconds"] == 1800
    assert config.json()["thresholds"]["isolated"] == 90.0


def test_decision_detail_reason_codes_include_latched_signal_from_ledger(
    client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """
    Regression test for a display-consistency bug:

    A session-scoped signal (UNUSUAL_TIME) can fire in an earlier evaluation,
    be latched, and persist its contribution in the session risk ledger. A later
    evaluation does not re-emit it, so the persisted RiskDecisionRecord's
    reason_cases/risk_signals omit it. The detail view must still surface the
    signal from the authoritative contribution ledger so reason codes remain
    consistent with the stored contributions.
    """
    session_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Session owned by the test merchant.
    session = SessionRecord(
        session_id=session_id,
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=27.0,
        status="active",
        device_fingerprint="device-unusual",
        ip_address="203.0.113.10",
        last_activity_at=now,
    )
    db_session.add(session)

    # Ledger contribution from an earlier evaluation: UNUSUAL_TIME fired then
    # and was latched; it is not re-emitted by the current evaluation.
    unusual_contribution = {
        "name": "UNUSUAL_TIME",
        "points": 11.0,
        "reason_code": "UNUSUAL_TRANSACTION_TIME",
        "kind": "signal",
        "event_id": str(uuid.uuid4()),
        "occurred_at": now.isoformat(),
        "latch_key": "UNUSUAL_TIME",
        "detail": {},
    }
    state_record = SessionRiskStateRecord(
        state_id=uuid.uuid4(),
        session_id=session_id,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        carried_forward=0.0,
        raw_points_sum=27.0,
        decay_points_total=0.0,
        current_score=27.0,
        canary_points=0.0,
        contributions=[unusual_contribution],
        latched_signals=["UNUSUAL_TIME"],
        fired_payees=[],
        registered_payees=[],
        sequence_markers=[],
        consumed_markers=[],
        event_fingerprints=[],
        canary_seen=False,
        last_evaluated_at=now,
    )
    db_session.add(state_record)

    # Persisted decision from the current evaluation: UNUSUAL_TIME is latched
    # so it is not re-emitted here; only NEW_PAYEE fired plus the policy code.
    decision = RiskDecisionRecord(
        decision_id=decision_id,
        session_id=session_id,
        merchant_id=TEST_MERCHANT_ID,
        risk_score=27.0,
        trust_level=TrustLevel.NORMAL.value,
        action="ALLOW",
        routing_destination="PROVIDER_MOCK",
        reason_codes=["NEW_PAYEE_DESTINATION", "NORMAL_TRUST_ELIGIBLE"],
        risk_signals={"NEW_PAYEE": 16.0},
        evaluated_at=now,
    )
    db_session.add(decision)
    db_session.commit()

    detail = client.get(
        f"/v1/risk/decisions/{decision_id}",
        headers=merchant_auth_headers,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()

    # The signal reason code from the ledger is present even though the current
    # evaluation did not re-emit it.
    assert "UNUSUAL_TRANSACTION_TIME" in body["decision"]["reason_codes"], body
    assert "NEW_PAYEE_DESTINATION" in body["decision"]["reason_codes"], body
    assert "NORMAL_TRUST_ELIGIBLE" in body["decision"]["reason_codes"], body

    # The risk signals summary also reflects the ledger contribution.
    signals = {s["name"]: s["weight"] for s in body["signals"]}
    assert "UNUSUAL_TIME" in signals, body
    assert signals["UNUSUAL_TIME"] == 11.0, body

    # Contributions still show the ledger entry.
    contribution_names = {c["name"] for c in body["contributions"]}
    assert "UNUSUAL_TIME" in contribution_names, body


def test_simulation_scenarios_and_calibration(
    client: TestClient,
    merchant_auth_headers: dict,
):
    scenarios = client.get(
        "/v1/simulate/scenarios", headers=merchant_auth_headers
    )
    assert scenarios.status_code == 200
    assert [item["id"] for item in scenarios.json()["scenarios"]] == [
        "account_takeover_canary_drill"
    ]

    calibration = client.get(
        "/v1/simulate/calibration", headers=merchant_auth_headers
    )
    assert calibration.status_code == 200, calibration.text
    body = calibration.json()
    assert body["synthetic_dataset"] is True
    assert body["calibration"]["identities"] > 0
    assert body["holdout"]["identities"] > 0
    assert body["overall"]["events"] > 0
    assert any("synthetic" in note.lower() for note in body["limitations"])


def test_unauthorized_reads_are_rejected(client: TestClient):
    assert client.get("/v1/payouts").status_code == 401
    assert client.get("/v1/analytics/overview").status_code == 401
    assert client.get("/v1/system/context").status_code == 401
    assert client.get("/v1/evidence/seals").status_code == 401
    assert client.get("/v1/honey/operator/workspaces").status_code == 401
    assert client.get("/v1/risk/config").status_code == 401
