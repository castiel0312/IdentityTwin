#!/usr/bin/env python3
"""
Seed script for IdentityTwin local demo and development environments.
Seeds test merchants, users, sessions in different trust levels, and test incidents.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.agent import AgentAuthorizationGrant, AgentRegistration, AgentStatus
from app.models.incident import IncidentRecord
from app.models.principal import Merchant, User
from app.models.session import SessionRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel

DEMO_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_MERCHANT_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
DEMO_ANALYST_USER_ID = UUID("00000000-0000-0000-0000-000000000002")

NORMAL_SESSION_ID = UUID("22222222-2222-2222-2222-222222222222")
RESTRICTED_SESSION_ID = UUID("33333333-3333-3333-3333-333333333333")
DECOY_SESSION_ID = UUID("44444444-4444-4444-4444-444444444444")
ISOLATED_SESSION_ID = UUID("55555555-5555-5555-5555-555555555555")

DEMO_INCIDENT_ID = UUID("66666666-6666-6666-6666-666666666666")

DEMO_AGENT_ID = UUID("77777777-7777-7777-7777-777777777777")
DEMO_AGENT_GRANT_ID = UUID("88888888-8888-8888-8888-888888888888")
DEMO_AGENT_SCOPE = "payout:execute"


def seed() -> None:
    print("Ensuring database tables exist...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Merchant
        merchant = db.query(Merchant).filter_by(merchant_id=DEMO_MERCHANT_ID).first()
        if not merchant:
            merchant = Merchant(
                merchant_id=DEMO_MERCHANT_ID,
                name="Acme Payments Demo Co.",
                slug="acme-demo",
                is_active=True,
            )
            db.add(merchant)
            print("Created demo merchant: Acme Payments Demo Co.")
        else:
            print("Demo merchant already exists.")

        # 2. Users (Merchant & Analyst)
        merchant_user = db.query(User).filter_by(user_id=DEMO_MERCHANT_USER_ID).first()
        if not merchant_user:
            merchant_user = User(
                user_id=DEMO_MERCHANT_USER_ID,
                merchant_id=DEMO_MERCHANT_ID,
                email="merchant-dev@identitytwin.local",
                role="merchant",
                is_active=True,
            )
            db.add(merchant_user)
            print("Created demo merchant user: merchant-dev@identitytwin.local")

        analyst_user = db.query(User).filter_by(user_id=DEMO_ANALYST_USER_ID).first()
        if not analyst_user:
            analyst_user = User(
                user_id=DEMO_ANALYST_USER_ID,
                merchant_id=DEMO_MERCHANT_ID,
                email="analyst-dev@identitytwin.local",
                role="analyst",
                is_active=True,
            )
            db.add(analyst_user)
            print("Created demo analyst user: analyst-dev@identitytwin.local")

        db.commit()

        # 3. Sessions in representative trust states
        sessions_to_seed = [
            (
                NORMAL_SESSION_ID,
                TrustLevel.NORMAL.value,
                0.0,
                "desktop-chrome-mac-verified",
            ),
            (
                RESTRICTED_SESSION_ID,
                TrustLevel.RESTRICTED.value,
                55.0,
                "mobile-safari-unrecognized",
            ),
            (
                DECOY_SESSION_ID,
                TrustLevel.DECOY.value,
                75.0,
                "tor-exit-node-fingerprint",
            ),
            (
                ISOLATED_SESSION_ID,
                TrustLevel.ISOLATED.value,
                95.0,
                "credential-stuffing-bot-sig",
            ),
        ]

        now = datetime.now(UTC)
        for s_id, trust, score, fp in sessions_to_seed:
            existing_session = (
                db.query(SessionRecord).filter_by(session_id=s_id).first()
            )
            if not existing_session:
                sess = SessionRecord(
                    session_id=s_id,
                    user_id=DEMO_MERCHANT_USER_ID,
                    merchant_id=DEMO_MERCHANT_ID,
                    trust_level=trust,
                    risk_score=score,
                    status=SessionStatus.ACTIVE.value,
                    device_fingerprint=fp,
                    ip_address="127.0.0.1",
                    last_activity_at=now,
                )
                db.add(sess)
                print(f"Created demo session [{trust}]: {s_id}")

        # 4. Incident
        incident = (
            db.query(IncidentRecord).filter_by(incident_id=DEMO_INCIDENT_ID).first()
        )
        if not incident:
            incident = IncidentRecord(
                incident_id=DEMO_INCIDENT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                session_id=RESTRICTED_SESSION_ID,
                title="Suspicious Rapid Device Fingerprint Shift",
                description="User session exhibited an abrupt behavioral anomaly during payout preparation.",
                severity=IncidentSeverity.HIGH.value,
                status=IncidentStatus.OPEN.value,
                risk_score=78.5,
                trigger_reason="BEHAVIORAL_BIOMETRIC_ANOMALY",
                evidence_summary={
                    "mouse_velocity_delta": 4.8,
                    "keystroke_flight_time_variance": 0.32,
                    "location_distance_km": 1240,
                },
            )
            db.add(incident)
            print(f"Created demo incident: {DEMO_INCIDENT_ID}")

        # 5. Agentic commerce registry: a registered AI agent and the
        # delegation grant that authorizes it for the demo merchant user.
        agent = db.query(AgentRegistration).filter_by(agent_id=DEMO_AGENT_ID).first()
        if not agent:
            agent = AgentRegistration(
                agent_id=DEMO_AGENT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                display_name="Acme Shopping Assistant",
                agent_type="shopping_assistant",
                vendor="identitytwin-demo",
                scopes=[DEMO_AGENT_SCOPE],
                status=AgentStatus.ACTIVE,
                max_payout_amount=500.0,
                is_active=True,
                description="Demo agent allowed to settle merchant payouts up to 500.00.",
            )
            db.add(agent)
            print(f"Created demo agent: {DEMO_AGENT_ID}")

        grant = (
            db.query(AgentAuthorizationGrant)
            .filter_by(grant_id=DEMO_AGENT_GRANT_ID)
            .first()
        )
        if not grant:
            grant = AgentAuthorizationGrant(
                grant_id=DEMO_AGENT_GRANT_ID,
                agent_id=DEMO_AGENT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                user_id=DEMO_MERCHANT_USER_ID,
                session_id=None,
                scopes=[DEMO_AGENT_SCOPE],
                max_amount=250.0,
                issued_at=now,
                expires_at=now + timedelta(days=30),
                delegated_by_user_id=DEMO_MERCHANT_USER_ID,
            )
            db.add(grant)
            print(f"Created demo agent grant: {DEMO_AGENT_GRANT_ID}")

        db.commit()
        print("\nDemo seeding successfully completed!")
        print("----------------------------------------------------------------")
        print(f"Demo Merchant ID:     {DEMO_MERCHANT_ID}")
        print(f"Merchant User ID:     {DEMO_MERCHANT_USER_ID}")
        print(f"Analyst User ID:      {DEMO_ANALYST_USER_ID}")
        print(f"Normal Session:       {NORMAL_SESSION_ID} (Trust: NORMAL)")
        print(f"Restricted Session:   {RESTRICTED_SESSION_ID} (Trust: RESTRICTED)")
        print(f"Decoy Session:        {DECOY_SESSION_ID} (Trust: DECOY)")
        print(f"Isolated Session:     {ISOLATED_SESSION_ID} (Trust: ISOLATED)")
        print(f"Demo Incident:        {DEMO_INCIDENT_ID}")
        print(f"Demo Agent ID:        {DEMO_AGENT_ID}")
        print(f"Demo Agent Grant ID:  {DEMO_AGENT_GRANT_ID}")
        print("----------------------------------------------------------------")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
