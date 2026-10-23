"""
Agentic commerce adapter tests (Person 3).

These tests exercise the internal agentic adapter contract end to end:
an AI agent states which registered agent it is and which delegation
authorizes it, and the backend normalizes that into the canonical Trust
Gateway payout request.

Covered invariants:
  * an authorized agent is executed by the Trust Gateway exactly like a
    human initiated payout (same risk evaluation, same routing, same
    idempotency semantics),
  * unauthorized agents (unknown, foreign merchant, suspended, wrong grant,
    wrong user, expired, revoked, missing scope, amount over the delegated
    limit) are rejected before any provider call,
  * missing authorization context is rejected by schema validation,
  * duplicate agent requests are deduplicated and never double-execute,
  * an agent can neither reuse a human payout idempotency key nor smuggle
    trust state, merchant identity or risk scores into the request,
  * risk based routing is unchanged for agent traffic: RESTRICTED requires
    step-up, DECOY only reaches the honey workspace, ISOLATED is blocked,
  * the agentic path never contacts a payment provider directly.

SAFETY: the service under test is always wired to the synthetic mock
provider adapter, so no test in this module can contact PayPal.
"""

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.gateway.agentic import (
    AgenticCommerceAdapter,
    AgenticCommerceService,
    IAgenticCommerceAdapter,
    get_agentic_commerce_service,
)
from app.gateway.policy import get_gateway_policy
from app.gateway.provider import decoy_provider_instance, mock_provider_instance
from app.gateway.service import TrustGatewayService
from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
    AgentStatus,
)
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.risk.service import get_risk_engine
from app.schemas.agentic import AgentScope
from app.schemas.payouts import PayoutRequest
from tests.conftest import (
    DECOY_SESSION_ID,
    ISOLATED_SESSION_ID,
    NORMAL_SESSION_ID,
    OTHER_MERCHANT_ID,
    RESTRICTED_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)

AGENTIC_URL = "/v1/agentic/payouts"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _build_service() -> AgenticCommerceService:
    """Wire the agentic service to the synthetic mock provider (never PayPal)."""
    gateway = TrustGatewayService(
        policy=get_gateway_policy(),
        risk_engine=get_risk_engine(),
        provider_adapter=mock_provider_instance,
        decoy_adapter=decoy_provider_instance,
    )
    return AgenticCommerceService(adapter=AgenticCommerceAdapter(), gateway_service=gateway)


@pytest.fixture
def agentic_client(client: TestClient) -> TestClient:
    """Client bound to a deterministic agentic service (mock provider only)."""
    from app.main import app

    app.dependency_overrides[get_agentic_commerce_service] = _build_service
    return client


def _register_agent(
    db: Session,
    *,
    merchant_id: uuid.UUID = TEST_MERCHANT_ID,
    user_id: uuid.UUID = TEST_USER_ID,
    scopes: tuple[str, ...] = (AgentScope.PAYOUT_EXECUTE.value,),
    grant_scopes: tuple[str, ...] | None = None,
    grant_max_amount: float | None = None,
    agent_max_amount: float | None = None,
    status: str = AgentStatus.ACTIVE,
    is_active: bool = True,
    session_id: uuid.UUID | None = None,
    expires_in_minutes: int = 60,
    revoked: bool = False,
    consumed: bool = False,
) -> tuple[AgentRegistration, AgentAuthorizationGrant]:
    agent = AgentRegistration(
        merchant_id=merchant_id,
        display_name="Demo Shopping Agent",
        agent_type="shopping_assistant",
        vendor="identitytwin-demo",
        scopes=list(scopes),
        status=status,
        max_payout_amount=agent_max_amount,
        is_active=is_active,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    now = datetime.now(timezone.utc)
    grant = AgentAuthorizationGrant(
        agent_id=agent.agent_id,
        merchant_id=merchant_id,
        user_id=user_id,
        session_id=session_id,
        scopes=list(grant_scopes if grant_scopes is not None else scopes),
        max_amount=grant_max_amount,
        issued_at=now,
        expires_at=now + timedelta(minutes=expires_in_minutes),
        revoked_at=now if revoked else None,
        consumed_at=now if consumed else None,
        delegated_by_user_id=user_id,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return agent, grant


def _payload(
    agent: AgentRegistration,
    grant: AgentAuthorizationGrant,
    *,
    session_id: uuid.UUID = NORMAL_SESSION_ID,
    amount: float = 120.0,
    idempotency_key: str | None = None,
    **overrides,
) -> dict:
    body = {
        "agent_id": str(agent.agent_id),
        "authorization_grant_id": str(grant.grant_id),
        "session_id": str(session_id),
        "recipient_email": "vendor@agentic.example",
        "amount": amount,
        "currency": "USD",
        "reference_note": "Agent initiated settlement",
        "idempotency_key": idempotency_key or f"agentic-{uuid.uuid4().hex}",
    }
    body.update(overrides)
    return body


# ----------------------------------------------------------------------
# Authorized agents
# ----------------------------------------------------------------------


def test_authorized_agent_payout_completes_through_trust_gateway(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An authorized agent is executed by the Trust Gateway, exactly once."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "completed"
    assert data["action"] == "ALLOW"
    assert data["trust_level"] == "NORMAL"
    assert data["routing_destination"] in ("PROVIDER_MOCK", "PROVIDER_PAYPAL")
    assert data["provider_reference"].startswith("SYNTH-MOCK-TXN-")
    assert mock_provider_instance.invocation_count == 1

    # Agent provenance is attached to the gateway response.
    assert data["agent_id"] == str(agent.agent_id)
    assert data["agent_display_name"] == "Demo Shopping Agent"
    assert data["agent_type"] == "shopping_assistant"
    assert data["authorization_grant_id"] == str(grant.grant_id)
    assert data["delegated_by_user_id"] == str(TEST_USER_ID)

    # The payout is owned by the authenticated merchant and user, never by
    # anything supplied in the agent request body.
    payout = (
        db_session.query(PayoutRequestRecord)
        .filter_by(payout_id=uuid.UUID(data["payout_id"]))
        .one()
    )
    assert payout.merchant_id == TEST_MERCHANT_ID
    assert payout.user_id == TEST_USER_ID
    assert payout.session_id == NORMAL_SESSION_ID
    assert payout.amount == 120.0
    assert f"[agent:{agent.agent_id}]" in payout.reference_note


def test_authorized_agent_request_is_recorded_in_the_audit_trail(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """Every agent initiated attempt is attributable in the audit trail."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)
    key = f"agentic-audit-{uuid.uuid4().hex}"

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, idempotency_key=key),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 200, res.text

    audit = (
        db_session.query(AgenticCommerceAudit)
        .filter_by(merchant_id=TEST_MERCHANT_ID, idempotency_key=key)
        .one()
    )
    assert audit.agent_id == agent.agent_id
    assert audit.grant_id == grant.grant_id
    assert audit.user_id == TEST_USER_ID
    assert audit.session_id == NORMAL_SESSION_ID
    assert audit.payout_id == uuid.UUID(res.json()["payout_id"])
    assert audit.status == "completed"
    assert audit.outcome == "ALLOW"
    assert audit.amount == 120.0
    assert audit.agent_context["agent_display_name"] == "Demo Shopping Agent"
    assert audit.agent_context["grant_id"] == str(grant.grant_id)
    assert audit.agent_context["scopes"] == [AgentScope.PAYOUT_EXECUTE.value]


def test_agent_identity_is_resolved_server_side_not_taken_from_the_body(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """The agent cannot describe itself: identity comes from the registry."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(
            agent,
            grant,
            agent_display_name="Totally Legitimate Agent",
            agent_type="system",
            vendor="attacker",
            scopes=["payout:execute", "admin:everything"],
        ),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 422, res.text
    assert mock_provider_instance.invocation_count == 0


# ----------------------------------------------------------------------
# Unauthorized agents
# ----------------------------------------------------------------------


def test_unregistered_agent_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
):
    """An unknown agent reference never reaches the gateway."""
    mock_provider_instance.reset()

    body = {
        "agent_id": str(uuid.uuid4()),
        "authorization_grant_id": str(uuid.uuid4()),
        "session_id": str(NORMAL_SESSION_ID),
        "recipient_email": "vendor@agentic.example",
        "amount": 100.0,
        "currency": "USD",
        "idempotency_key": f"agentic-unknown-{uuid.uuid4().hex}",
    }

    res = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_NOT_REGISTERED"
    assert mock_provider_instance.invocation_count == 0


def test_agent_registered_to_another_merchant_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """Cross-merchant agent use is rejected."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, merchant_id=OTHER_MERCHANT_ID)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_MERCHANT_MISMATCH"
    assert mock_provider_instance.invocation_count == 0


def test_suspended_agent_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A suspended agent registration cannot act."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, status=AgentStatus.SUSPENDED)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_NOT_ACTIVE"
    assert mock_provider_instance.invocation_count == 0


def test_missing_grant_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An agent without a delegation grant cannot act."""
    mock_provider_instance.reset()
    agent, _ = _register_agent(db_session)

    body = _payload(agent, _register_agent(db_session)[1])
    body["authorization_grant_id"] = str(uuid.uuid4())

    res = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_MISSING"
    assert mock_provider_instance.invocation_count == 0


def test_grant_issued_to_another_agent_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A grant cannot be replayed against a different agent."""
    mock_provider_instance.reset()
    agent, _ = _register_agent(db_session)
    _, other_grant = _register_agent(db_session)

    body = _payload(agent, other_grant)

    res = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_AGENT_MISMATCH"
    assert mock_provider_instance.invocation_count == 0


def test_grant_issued_to_another_user_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A delegation only authorizes the user it was issued to."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, user_id=uuid.uuid4())

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_PRINCIPAL_MISMATCH"
    assert mock_provider_instance.invocation_count == 0


def test_expired_grant_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An expired delegation authorizes nothing."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, expires_in_minutes=-5)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_EXPIRED"
    assert mock_provider_instance.invocation_count == 0


def test_revoked_grant_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A revoked delegation authorizes nothing."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, revoked=True)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_REVOKED"
    assert mock_provider_instance.invocation_count == 0


def test_consumed_grant_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A single use delegation cannot be replayed for a different request."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, consumed=True)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_CONSUMED"
    assert mock_provider_instance.invocation_count == 0


def test_consumed_grant_still_allows_the_replay_of_its_own_request(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """
    A single use grant authorizes only its own request: the retry of that
    request still returns the cached result instead of an authorization error.
    """
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)
    key = f"agentic-single-use-{uuid.uuid4().hex}"
    body = _payload(agent, grant, idempotency_key=key)

    first = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert first.status_code == 200, first.text

    grant.consumed_at = datetime.now(timezone.utc)
    db_session.commit()

    replay = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["is_duplicate"] is True
    assert replay.json()["payout_id"] == first.json()["payout_id"]
    assert mock_provider_instance.invocation_count == 1

    # A different request on the same consumed grant is refused.
    other = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, idempotency_key=f"agentic-other-{uuid.uuid4().hex}"),
        headers=merchant_auth_headers,
    )
    assert other.status_code == 403
    assert other.json()["error"]["code"] == "AGENT_AUTHORIZATION_CONSUMED"
    assert mock_provider_instance.invocation_count == 1


def test_grant_bound_to_another_session_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A session bound delegation cannot be used from another session."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, session_id=RESTRICTED_SESSION_ID)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, session_id=NORMAL_SESSION_ID),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AUTHORIZATION_SESSION_MISMATCH"
    assert mock_provider_instance.invocation_count == 0


def test_missing_scope_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An agent without the payout scope cannot execute a payout."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(
        db_session,
        scopes=(AgentScope.PAYOUT_READ.value,),
        grant_scopes=(AgentScope.PAYOUT_READ.value,),
    )

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_SCOPE_NOT_GRANTED"
    assert mock_provider_instance.invocation_count == 0


def test_amount_above_delegated_limit_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """The delegation amount ceiling is enforced before execution."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, grant_max_amount=50.0)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, amount=500.0),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AMOUNT_LIMIT_EXCEEDED"
    assert mock_provider_instance.invocation_count == 0


def test_agent_ceiling_is_applied_in_addition_to_the_grant_ceiling(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """The strictest of the registration and delegation ceilings applies."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session, grant_max_amount=500.0, agent_max_amount=25.0)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, amount=100.0),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "AGENT_AMOUNT_LIMIT_EXCEEDED"
    assert mock_provider_instance.invocation_count == 0


# ----------------------------------------------------------------------
# Missing context
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["agent_id", "authorization_grant_id", "session_id", "idempotency_key", "recipient_email"],
)
def test_missing_authorization_context_is_rejected_by_validation(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
    missing_field: str,
):
    """Missing agent context fails schema validation, it never defaults."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    body = _payload(agent, grant)
    body.pop(missing_field)

    res = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    assert res.status_code == 422, res.text
    assert mock_provider_instance.invocation_count == 0


def test_agent_cannot_smuggle_trust_state_or_merchant_identity(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """Trust state, risk score and merchant identity are never caller supplied."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(
            agent,
            grant,
            trust_level="NORMAL",
            risk_score=0.0,
            merchant_id=str(OTHER_MERCHANT_ID),
        ),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 422, res.text
    assert mock_provider_instance.invocation_count == 0


def test_agent_request_for_unknown_session_is_rejected(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An unknown session never reaches a provider and is audited as failed."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, session_id=uuid.uuid4()),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert mock_provider_instance.invocation_count == 0

    audit = (
        db_session.query(AgenticCommerceAudit)
        .filter_by(agent_id=agent.agent_id)
        .order_by(AgenticCommerceAudit.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.status == "failed"


# ----------------------------------------------------------------------
# Duplicates
# ----------------------------------------------------------------------


def test_duplicate_agent_request_is_deduplicated(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """A retried agent request returns the cached result and never pays twice."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)
    key = f"agentic-duplicate-{uuid.uuid4().hex}"
    body = _payload(agent, grant, idempotency_key=key)

    first = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)
    second = agentic_client.post(AGENTIC_URL, json=body, headers=merchant_auth_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["is_duplicate"] is False
    assert second.json()["is_duplicate"] is True
    assert second.json()["payout_id"] == first.json()["payout_id"]
    assert second.json()["provider_reference"] == first.json()["provider_reference"]
    assert mock_provider_instance.invocation_count == 1

    payouts = db_session.query(PayoutRequestRecord).filter_by(idempotency_key=key).all()
    assert len(payouts) == 1


def test_agent_cannot_reuse_the_idempotency_key_of_a_human_payout(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """An agent may not inherit the cached result of a direct human payout."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)
    key = f"shared-key-{uuid.uuid4().hex}"

    human = agentic_client.post(
        "/v1/payouts",
        json={
            "session_id": str(NORMAL_SESSION_ID),
            "recipient_email": "vendor@agentic.example",
            "amount": 120.0,
            "currency": "USD",
            "idempotency_key": key,
        },
        headers=merchant_auth_headers,
    )
    assert human.status_code == 200, human.text

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, idempotency_key=key),
        headers=merchant_auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "AGENT_IDEMPOTENCY_KEY_CONFLICT"
    assert mock_provider_instance.invocation_count == 1  # only the human payout executed


def test_agent_cannot_reuse_the_idempotency_key_of_another_agent(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """Two agents of the same merchant do not share an idempotency namespace."""
    mock_provider_instance.reset()
    agent_a, grant_a = _register_agent(db_session)
    agent_b, grant_b = _register_agent(db_session)
    key = f"agentic-cross-agent-{uuid.uuid4().hex}"

    first = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent_a, grant_a, idempotency_key=key),
        headers=merchant_auth_headers,
    )
    assert first.status_code == 200, first.text

    second = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent_b, grant_b, idempotency_key=key),
        headers=merchant_auth_headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "AGENT_IDEMPOTENCY_KEY_CONFLICT"
    assert mock_provider_instance.invocation_count == 1


# ----------------------------------------------------------------------
# Risk based routing for agent traffic
# ----------------------------------------------------------------------


def test_restricted_session_agent_request_requires_step_up(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """RESTRICTED sessions are rejected by policy, the provider is untouched."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, session_id=RESTRICTED_SESSION_ID),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "rejected"
    assert data["action"] == "REQUIRE_STEP_UP"
    assert data["routing_destination"] == "RESTRICTED_REJECT"
    assert data["provider_reference"] is None
    assert mock_provider_instance.invocation_count == 0


def test_decoy_session_agent_request_reaches_only_the_honey_workspace(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """DECOY sessions are forwarded to the honey workspace only."""
    mock_provider_instance.reset()
    decoy_provider_instance.invocation_count = 0
    agent, grant = _register_agent(db_session)

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, session_id=DECOY_SESSION_ID),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "decoy_completed"
    assert data["action"] == "DECOY_FORWARD"
    assert data["routing_destination"] == "DECOY_HONEY"
    assert data["provider_reference"].startswith("HONEY-DECOY-SIM-TXN-")
    assert mock_provider_instance.invocation_count == 0
    assert decoy_provider_instance.invocation_count == 1


def test_isolated_session_agent_request_is_blocked_and_opens_an_incident(
    agentic_client: TestClient,
    merchant_auth_headers: dict,
    db_session: Session,
):
    """ISOLATED sessions are blocked, never executed, and raise an incident."""
    mock_provider_instance.reset()
    agent, grant = _register_agent(db_session)

    incidents_before = db_session.query(IncidentRecord).count()

    res = agentic_client.post(
        AGENTIC_URL,
        json=_payload(agent, grant, session_id=ISOLATED_SESSION_ID),
        headers=merchant_auth_headers,
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "blocked"
    assert data["action"] == "BLOCK"
    assert data["routing_destination"] == "ISOLATED_BLOCK"
    assert data["provider_reference"] is None
    assert mock_provider_instance.invocation_count == 0
    assert db_session.query(IncidentRecord).count() == incidents_before + 1


# ----------------------------------------------------------------------
# Adapter contract
# ----------------------------------------------------------------------


def test_adapter_implements_the_documented_interface():
    """The concrete adapter satisfies the internal adapter protocol."""
    assert isinstance(AgenticCommerceAdapter(), IAgenticCommerceAdapter)


def test_normalization_preserves_identity_and_idempotency_key(
    db_session: Session,
):
    """
    Normalization keeps the session identity and the caller supplied
    idempotency key, and never introduces a merchant identity of its own.
    """
    from app.core.security import AuthenticatedPrincipal, RoleEnum

    agent, grant = _register_agent(db_session)
    principal = AuthenticatedPrincipal(
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        role=RoleEnum.MERCHANT,
    )
    adapter = AgenticCommerceAdapter()
    request_body = _payload(agent, grant, idempotency_key="agentic-normalize-key-0001")

    from app.schemas.agentic import AgenticCommerceRequest

    request = AgenticCommerceRequest(**request_body)
    decision = adapter.authorize(db=db_session, request=request, principal=principal)
    normalized = adapter.normalize(request=request, principal=principal, decision=decision)

    assert isinstance(normalized, PayoutRequest)
    assert normalized.session_id == NORMAL_SESSION_ID
    assert normalized.idempotency_key == "agentic-normalize-key-0001"
    assert normalized.amount == 120.0
    assert normalized.currency == "USD"
    assert f"[agent:{agent.agent_id}]" in normalized.reference_note
    # The merchant identity is not a request field: it is always resolved
    # from the authenticated principal by the Trust Gateway.
    assert "merchant_id" not in PayoutRequest.model_fields


def test_agentic_modules_never_import_payment_providers_directly():
    """
    The agentic path must not reach a provider adapter: it normalizes into
    the Trust Gateway, which owns every provider decision.
    """
    forbidden = {
        "IPaymentProviderAdapter",
        "MockPaymentProviderAdapter",
        "PayPalSandboxAdapter",
        "DecoyHoneyAdapter",
        "get_payment_provider",
        "get_decoy_provider",
    }
    app_dir = Path(__file__).resolve().parent.parent / "app"
    targets = [app_dir / "gateway" / "agentic.py", app_dir / "api" / "routes" / "agentic.py"]

    violations = []
    for target in targets:
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden:
                        violations.append(f"{target.name}:{node.lineno} imports '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden:
                        violations.append(
                            f"{target.name}:{node.lineno} imports '{alias.name}' from '{node.module}'"
                        )

    assert not violations, (
        "Agentic commerce must delegate to the Trust Gateway, never to a provider adapter:\n"
        + "\n".join(violations)
    )
