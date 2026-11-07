#!/usr/bin/env python3
"""
Seed script for IdentityTwin local demo and development environments.
Seeds test merchants, users, sessions in different trust levels, and test incidents.
"""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.evidence.hashchain import EvidenceChain
from app.honey.bootstrap import get_or_create_world
from app.honey.canary import CanaryRegistryService
from app.models.agent import (
    AgentAuthorizationGrant,
    AgenticCommerceAudit,
    AgentRegistration,
    AgentStatus,
)
from app.models.canary import CanaryRecord
from app.models.event import SecurityEvent
from app.models.idempotency import IdempotencyRecord
from app.models.incident import AnalystActionRecord, IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.principal import Merchant, User
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.models.twin import BehavioralTwin, SessionRiskStateRecord
from app.risk.config import get_risk_config
from app.risk.twin import bucket_ip_address, hash_device, hash_recipient
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
DEMO_ISOLATED_INCIDENT_ID = UUID("66666666-6666-6666-6666-666666666001")
DEMO_INCIDENT_ID_2 = UUID("66666666-6666-6666-6666-666666666002")
DEMO_INCIDENT_ID_3 = UUID("66666666-6666-6666-6666-666666666003")

DEMO_AGENT_ID = UUID("77777777-7777-7777-7777-777777777777")
DEMO_AGENT_GRANT_ID = UUID("88888888-8888-8888-8888-888888888888")
DEMO_AGENT_SCOPE = "payout:execute"

DEMO_SECOND_AGENT_ID = UUID("77777777-7777-7777-7777-777777777778")
DEMO_SECOND_GRANT_ID = UUID("88888888-8888-8888-8888-888888888889")

# Deterministic synthetic payouts used by the console demo. They describe
# completed gateway outcomes; they do not execute payments when seeded.
DEMO_PAYOUTS = [
    (
        "aaaaaaaa-0000-0000-0000-000000000001",
        "bbbbbbbb-0000-0000-0000-000000000001",
        NORMAL_SESSION_ID,
        "finance@northwind.example",
        1840.00,
        "completed",
        TrustLevel.NORMAL.value,
        8.0,
        "ALLOW",
        "PRIMARY",
        "INV-1001",
        -18,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000002",
        "bbbbbbbb-0000-0000-0000-000000000002",
        NORMAL_SESSION_ID,
        "payroll@lumen.example",
        4200.00,
        "completed",
        TrustLevel.NORMAL.value,
        12.0,
        "ALLOW",
        "PRIMARY",
        "INV-1002",
        -14,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000003",
        "bbbbbbbb-0000-0000-0000-000000000003",
        RESTRICTED_SESSION_ID,
        "vendor@atlas-supply.example",
        8600.00,
        "rejected",
        TrustLevel.RESTRICTED.value,
        54.0,
        "REQUIRE_STEP_UP",
        "BLOCKED",
        "INV-1003",
        -8,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000004",
        "bbbbbbbb-0000-0000-0000-000000000004",
        DECOY_SESSION_ID,
        "offshore@quiet-ledger.example",
        12750.00,
        "decoy_completed",
        TrustLevel.DECOY.value,
        76.0,
        "DECOY_FORWARD",
        "DECOY_HONEY",
        "INV-1004",
        -6,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000005",
        "bbbbbbbb-0000-0000-0000-000000000005",
        ISOLATED_SESSION_ID,
        "unknown@credential-drop.example",
        24000.00,
        "blocked",
        TrustLevel.ISOLATED.value,
        96.0,
        "BLOCK",
        "BLOCKED",
        "INV-1005",
        -5,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000006",
        "bbbbbbbb-0000-0000-0000-000000000006",
        NORMAL_SESSION_ID,
        "design@studio-mesa.example",
        640.00,
        "reconciled_completed",
        TrustLevel.NORMAL.value,
        4.0,
        "ALLOW",
        "PRIMARY",
        "INV-1006",
        -4,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000007",
        "bbbbbbbb-0000-0000-0000-000000000007",
        DECOY_SESSION_ID,
        "ops@phantom-batch.example",
        9700.00,
        "decoy_completed",
        TrustLevel.DECOY.value,
        68.0,
        "DECOY_FORWARD",
        "DECOY_HONEY",
        "INV-1007",
        -3,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000008",
        "bbbbbbbb-0000-0000-0000-000000000008",
        RESTRICTED_SESSION_ID,
        "ap@meridian.example",
        3100.00,
        "provider_denied",
        TrustLevel.RESTRICTED.value,
        47.0,
        "REQUIRE_STEP_UP",
        "PRIMARY",
        "INV-1008",
        -2,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000009",
        "bbbbbbbb-0000-0000-0000-000000000009",
        ISOLATED_SESSION_ID,
        "unknown@fast-cash.example",
        15000.00,
        "blocked",
        TrustLevel.ISOLATED.value,
        92.0,
        "BLOCK",
        "BLOCKED",
        "INV-1009",
        -1,
    ),
    (
        "aaaaaaaa-0000-0000-0000-000000000010",
        "bbbbbbbb-0000-0000-0000-000000000010",
        NORMAL_SESSION_ID,
        "benefits@harbor.example",
        2250.00,
        "completed",
        TrustLevel.NORMAL.value,
        16.0,
        "ALLOW",
        "PRIMARY",
        "INV-1010",
        0,
    ),
]


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
                "desktop-chrome-mac",
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
                    ip_address=(
                        "198.51.100.24"
                        if s_id == NORMAL_SESSION_ID
                        else "127.0.0.1"
                    ),
                    last_activity_at=now,
                )
                db.add(sess)
                print(f"Created demo session [{trust}]: {s_id}")

        db.flush()

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
            db.flush()
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

        # 6. Operational demo records used by the console. These are synthetic
        # projections of gateway outcomes, not new payment executions.
        _seed_demo_payouts(db, now)
        _seed_demo_events(db, now)
        _seed_demo_twins_and_risk_state(db, now)
        _seed_demo_incidents(db, now)
        _seed_demo_agent_reads(db, now)
        db.commit()
        _seed_demo_evidence(db, now)
        _seed_demo_honey(db, now)

        isolated = db.get(SessionRecord, ISOLATED_SESSION_ID)
        if isolated is not None and isolated.status != SessionStatus.REVOKED.value:
            isolated.status = SessionStatus.REVOKED.value
            db.commit()

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


def _seed_demo_payouts(db, now: datetime) -> None:
    """Create deterministic gateway outcomes for analytics and ledger screens."""
    for (
        payout_raw,
        decision_raw,
        session_id,
        recipient,
        amount,
        status,
        trust,
        score,
        action,
        routing,
        reference,
        hour_offset,
    ) in DEMO_PAYOUTS:
        payout_id = UUID(payout_raw)
        if db.get(PayoutRequestRecord, payout_id) is not None:
            continue
        decision_id = UUID(decision_raw)
        occurred = now + timedelta(hours=hour_offset)
        signals = {
            "NEW_DEVICE": 18.0 if score >= 30 else 0.0,
            "NEW_PAYEE": 16.0 if score >= 40 else 0.0,
            "LARGE_PAYOUT": 21.0 if amount >= 5000 else 8.0,
            "UNUSUAL_TIME": 11.0 if score >= 50 else 0.0,
        }
        reason_codes = [name for name, points in signals.items() if points > 0]
        db.add(
            RiskDecisionRecord(
                decision_id=decision_id,
                session_id=session_id,
                merchant_id=DEMO_MERCHANT_ID,
                risk_score=score,
                trust_level=trust,
                action=action,
                routing_destination=routing,
                reason_codes=reason_codes,
                risk_signals=signals,
                evaluated_at=occurred,
                created_at=occurred,
                updated_at=occurred,
            )
        )
        provider = "honey_synthetic_decoy" if routing == "DECOY_HONEY" else "mock_sandbox"
        db.add(
            PayoutRequestRecord(
                payout_id=payout_id,
                decision_id=decision_id,
                session_id=session_id,
                merchant_id=DEMO_MERCHANT_ID,
                user_id=DEMO_MERCHANT_USER_ID,
                recipient_email=recipient,
                amount=amount,
                currency="USD",
                reference_note=reference,
                idempotency_key=f"demo-payout-{payout_id}",
                status=status,
                provider_name=provider,
                provider_reference=f"{provider}-ref-{payout_id.hex[:8]}",
                provider_payload={"batch_status": "SUCCESS", "sandbox": True},
                executed_at=occurred,
                created_at=occurred,
                updated_at=occurred,
            )
        )
        db.add(
            IdempotencyRecord(
                record_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-idempotency:{payout_id}"),
                idempotency_key=f"demo-payout-{payout_id}",
                merchant_id=DEMO_MERCHANT_ID,
                request_hash="0" * 64,
                status="completed" if status != "blocked" else "failed",
                response_code=200 if status != "blocked" else 403,
                response_payload={"payout_id": str(payout_id), "status": status},
                expires_at=now + timedelta(days=7),
                created_at=occurred,
                updated_at=occurred,
            )
        )


def _seed_demo_events(db, now: datetime) -> None:
    """Populate the session investigation timeline with deterministic events."""
    session_specs = [
        (NORMAL_SESSION_ID, "desktop-chrome-mac", "198.51.100.24", 0),
        (RESTRICTED_SESSION_ID, "mobile-safari-new", "203.0.113.44", 8),
        (DECOY_SESSION_ID, "tor-exit-fingerprint", "185.220.101.9", 16),
        (ISOLATED_SESSION_ID, "bot-signature-credential-stuffing", "45.155.205.12", 24),
    ]
    event_types = [
        ("login", "session.login"),
        ("payee_added", "payee.register"),
        ("payout", "payout.execute"),
        ("device_change", "device.change"),
        ("payout", "payout.execute"),
        ("payee_added", "payee.register"),
    ]
    for session_id, device, ip, base_offset in session_specs:
        for index, (event_type, action) in enumerate(event_types):
            occurred = now - timedelta(hours=base_offset + index * 2)
            event_id = uuid.uuid5(
                uuid.NAMESPACE_DNS, f"demo-event:{session_id}:{index}"
            )
            if db.get(SecurityEvent, event_id) is not None:
                continue
            metadata = {"amount": 0.0}
            if event_type == "payout":
                metadata = {"amount": [1840.0, 8600.0, 12750.0, 24000.0][index % 4]}
            if event_type == "payee_added":
                metadata = {"recipient": "beneficiary@example.test"}
            db.add(
                SecurityEvent(
                    event_id=event_id,
                    session_id=session_id,
                    merchant_id=DEMO_MERCHANT_ID,
                    user_id=DEMO_MERCHANT_USER_ID,
                    event_type=event_type,
                    occurred_at=occurred,
                    device_id=device,
                    ip_address=ip,
                    action=action,
                    metadata_payload=metadata,
                    idempotency_key=f"demo-event-{event_id}",
                    processed_by_risk_engine=True,
                    created_at=occurred,
                    updated_at=occurred,
                )
            )


def _seed_demo_twins_and_risk_state(db, now: datetime) -> None:
    risk_config = get_risk_config()
    salt = risk_config.device_hash_salt
    for user_id, samples, devices, payees, total in [
        (
            DEMO_MERCHANT_USER_ID,
            42,
            ["desktop-chrome-mac", "iphone-safari"],
            {"finance@northwind.example": 6, "payroll@lumen.example": 3},
            18400.0,
        ),
        (
            DEMO_ANALYST_USER_ID,
            9,
            ["analyst-thinkpad"],
            {"security-vendor@example.test": 1},
            1200.0,
        ),
    ]:
        existing = (
            db.query(BehavioralTwin)
            .filter_by(merchant_id=DEMO_MERCHANT_ID, user_id=user_id)
            .first()
        )
        # The risk engine compares salted device hashes, coarse IP buckets and
        # hashed recipients. Seeding raw labels would make a known demo context
        # appear new on the first live payout. Keep existing demo twins repaired
        # too, so re-running `make seed` fixes a database created by an older
        # seed version.
        hashed_devices = {
            hash_device(device, salt) or device: 12 for device in devices
        }
        hashed_locations = {
            bucket_ip_address("198.51.100.24") or "198.51": 32,
            bucket_ip_address("203.0.113.44") or "203.0": 10,
        }
        hashed_payees = {
            hash_recipient(payee) or payee: count
            for payee, count in payees.items()
        }
        histogram = {"8": 6, "9": 14, "10": 9, "14": 7, "15": 6}
        if existing is None:
            db.add(
                BehavioralTwin(
                    twin_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-twin:{user_id}"),
                    merchant_id=DEMO_MERCHANT_ID,
                    user_id=user_id,
                    sample_count=samples,
                    confirmed_devices=list(hashed_devices),
                    confirmed_locations=list(hashed_locations),
                    payee_observations=hashed_payees,
                    device_observations=hashed_devices,
                    location_observations=hashed_locations,
                    hour_histogram=histogram,
                    total_amount=total,
                    amount_count=samples,
                    last_updated_at=now,
                    created_at=now - timedelta(days=90),
                    updated_at=now,
                )
            )
        else:
            existing.sample_count = samples
            existing.confirmed_devices = list(hashed_devices)
            existing.confirmed_locations = list(hashed_locations)
            existing.payee_observations = hashed_payees
            existing.device_observations = hashed_devices
            existing.location_observations = hashed_locations
            existing.hour_histogram = histogram
            existing.total_amount = total
            existing.amount_count = samples
            existing.last_updated_at = now
            existing.updated_at = now

    risk_states = [
        (
            RESTRICTED_SESSION_ID,
            55.0,
            [
                ("NEW_DEVICE", 18.0, "New device fingerprint"),
                ("NEW_PAYEE", 16.0, "Recipient not previously confirmed"),
                ("LARGE_PAYOUT", 21.0, "Payout above behavioural baseline"),
            ],
            ["NEW_DEVICE", "NEW_PAYEE"],
            ["PAYEE_ADD_THEN_PAYOUT"],
        ),
        (
            DECOY_SESSION_ID,
            75.0,
            [
                ("NEW_DEVICE", 18.0, "Tor exit fingerprint"),
                ("UNUSUAL_TIME", 11.0, "Activity outside usual hours"),
                ("NEW_PAYEE_LARGE_PAYOUT", 9.0, "New payee with high amount"),
                ("CANARY_INTERACTION", 11.0, "Canary touched in synthetic world"),
            ],
            ["NEW_DEVICE", "CANARY_INTERACTION"],
            ["PAYEE_ADD_THEN_PAYOUT"],
        ),
        (
            ISOLATED_SESSION_ID,
            95.0,
            [
                ("NEW_DEVICE", 18.0, "Automation fingerprint"),
                ("CANARY_INTERACTION", 11.0, "Canary interaction forces isolation"),
                ("LARGE_PAYOUT", 21.0, "High-value attempt"),
            ],
            ["NEW_DEVICE", "CANARY_INTERACTION"],
            ["PAYEE_ADD_THEN_PAYOUT"],
        ),
    ]
    for session_id, score, contributions, latched, sequences in risk_states:
        existing = (
            db.query(SessionRiskStateRecord).filter_by(session_id=session_id).first()
        )
        if existing is not None:
            continue
        db.add(
            SessionRiskStateRecord(
                state_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-risk-state:{session_id}"),
                session_id=session_id,
                merchant_id=DEMO_MERCHANT_ID,
                user_id=DEMO_MERCHANT_USER_ID,
                carried_forward=0.0,
                raw_points_sum=sum(item[1] for item in contributions),
                decay_points_total=0.0,
                current_score=score,
                canary_points=11.0 if "CANARY_INTERACTION" in latched else 0.0,
                contributions=[
                    {
                        "name": name,
                        "points": points,
                        "reason_code": name,
                        "kind": "signal",
                        "occurred_at": (now - timedelta(hours=index + 1)).isoformat(),
                        "detail": {"summary": summary},
                    }
                    for index, (name, points, summary) in enumerate(contributions)
                ],
                latched_signals=latched,
                fired_payees=["beneficiary@example.test"],
                registered_payees=["new-payee@example.test"],
                sequence_markers=[
                    {
                        "marker_id": f"{session_id}-marker-{index}",
                        "sequence_type": sequence,
                        "recipient_hash": "sha256:demo-recipient",
                        "occurred_at": (now - timedelta(hours=index + 1)).isoformat(),
                    }
                    for index, sequence in enumerate(sequences)
                ],
                consumed_markers=[],
                event_fingerprints=[],
                canary_seen="CANARY_INTERACTION" in latched,
                last_evaluated_at=now,
                created_at=now - timedelta(days=1),
                updated_at=now,
            )
        )


def _seed_demo_incidents(db, now: datetime) -> None:
    extra = [
        (
            DEMO_ISOLATED_INCIDENT_ID,
            ISOLATED_SESSION_ID,
            "Canary Interaction Forced Session Isolation",
            "A scoped synthetic canary was touched. The backend isolated the session and revoked it.",
            IncidentSeverity.CRITICAL.value,
            IncidentStatus.UNDER_REVIEW.value,
            96.0,
            "CANARY_INTERACTION",
        ),
        (
            DEMO_INCIDENT_ID_2,
            DECOY_SESSION_ID,
            "Decoy Payout Routed to Synthetic Workspace",
            "A high-risk payout was redirected to the synthetic honey world for observation.",
            IncidentSeverity.MEDIUM.value,
            IncidentStatus.APPROVED.value,
            76.0,
            "DECOY_FORWARD",
        ),
        (
            DEMO_INCIDENT_ID_3,
            NORMAL_SESSION_ID,
            "Unrecognized Device at Payout Confirmation",
            "A new device was observed during a routine payout confirmation.",
            IncidentSeverity.LOW.value,
            IncidentStatus.RESOLVED.value,
            24.0,
            "NEW_DEVICE",
        ),
    ]
    for (
        incident_id,
        session_id,
        title,
        description,
        severity,
        status,
        score,
        reason,
    ) in extra:
        if db.get(IncidentRecord, incident_id) is None:
            db.add(
                IncidentRecord(
                    incident_id=incident_id,
                    merchant_id=DEMO_MERCHANT_ID,
                    session_id=session_id,
                    title=title,
                    description=description,
                    severity=severity,
                    status=status,
                    risk_score=score,
                    trigger_reason=reason,
                    evidence_summary={
                        "risk_score": score,
                        "signal": reason,
                        "synthetic_context": "hoe" if session_id == DECOY_SESSION_ID else None,
                    },
                    resolved_at=now - timedelta(hours=4)
                    if status == IncidentStatus.RESOLVED.value
                    else None,
                )
            )

    action = (
        db.query(AnalystActionRecord)
        .filter_by(incident_id=DEMO_INCIDENT_ID_2, action_type="approved")
        .first()
    )
    if action is None:
        db.add(
            AnalystActionRecord(
                action_id=uuid.uuid5(uuid.NAMESPACE_DNS, "demo-analyst-action"),
                incident_id=DEMO_INCIDENT_ID_2,
                analyst_id=DEMO_ANALYST_USER_ID,
                action_type="approved",
                notes="Reviewed synthetic routing and approved containment outcome.",
                action_metadata={"previous_status": "OPEN"},
                performed_at=now - timedelta(hours=6),
                created_at=now - timedelta(hours=6),
                updated_at=now - timedelta(hours=6),
            )
        )


def _seed_demo_agent_reads(db, now: datetime) -> None:
    second = db.get(AgentRegistration, DEMO_SECOND_AGENT_ID)
    if second is None:
        db.add(
            AgentRegistration(
                agent_id=DEMO_SECOND_AGENT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                display_name="Ledger Reconciliation Agent",
                agent_type="reconciliation",
                vendor="identitytwin-demo",
                scopes=["payout:read"],
                status=AgentStatus.SUSPENDED,
                max_payout_amount=0.0,
                is_active=False,
                description="Suspended demo agent kept for registry history.",
                created_at=now - timedelta(days=30),
                updated_at=now - timedelta(days=3),
            )
        )
    db.flush()
    if db.get(AgentAuthorizationGrant, DEMO_SECOND_GRANT_ID) is None:
        db.add(
            AgentAuthorizationGrant(
                grant_id=DEMO_SECOND_GRANT_ID,
                agent_id=DEMO_SECOND_AGENT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                user_id=DEMO_MERCHANT_USER_ID,
                session_id=None,
                scopes=["payout:read"],
                max_amount=0.0,
                issued_at=now - timedelta(days=30),
                expires_at=now - timedelta(days=2),
                revoked_at=now - timedelta(days=3),
                delegated_by_user_id=DEMO_MERCHANT_USER_ID,
                created_at=now - timedelta(days=30),
                updated_at=now - timedelta(days=3),
            )
        )

    audits = [
        ("accepted", "AUTHORIZED", 120.0, "purchase"),
        ("accepted", "AUTHORIZED", 240.0, "purchase"),
        ("rejected", "AGENT_AMOUNT_LIMIT_EXCEEDED", 900.0, "purchase"),
        ("blocked", "AGENT_SCOPE_NOT_GRANTED", 75.0, "refund"),
        ("accepted", "AUTHORIZED", 49.0, "purchase"),
    ]
    for index, (status, outcome, amount, intent) in enumerate(audits):
        audit_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-agent-audit:{index}")
        if db.get(AgenticCommerceAudit, audit_id) is not None:
            continue
        db.add(
            AgenticCommerceAudit(
                audit_id=audit_id,
                agent_id=DEMO_AGENT_ID,
                grant_id=DEMO_AGENT_GRANT_ID,
                merchant_id=DEMO_MERCHANT_ID,
                user_id=DEMO_MERCHANT_USER_ID,
                session_id=NORMAL_SESSION_ID,
                payout_id=None,
                idempotency_key=f"demo-agent-audit-{index}",
                recipient_email=f"merchant-{index}@example.test",
                amount=amount,
                currency="USD",
                status=status,
                outcome=outcome,
                agent_context={"intent": intent, "synthetic": True},
                created_at=now - timedelta(hours=index * 3 + 1),
                updated_at=now - timedelta(hours=index * 3 + 1),
            )
        )


def _seed_demo_evidence(db, now: datetime) -> None:
    from app.models.evidence import EvidenceLogEntry, IncidentSeal

    if db.query(EvidenceLogEntry).count() == 0:
        chain = EvidenceChain(db)
        for session_id, summary in [
            (NORMAL_SESSION_ID, "Session login from a confirmed device."),
            (RESTRICTED_SESSION_ID, "New device observed at payout confirmation."),
            (DECOY_SESSION_ID, "Payout redirected to a synthetic honey workspace."),
            (ISOLATED_SESSION_ID, "Canary interaction detected; containment triggered."),
        ]:
            chain.append(
                "login",
                {
                    "type": "login",
                    "session_id": str(session_id),
                    "summary": summary,
                    "occurred_at": (now - timedelta(hours=30)).isoformat(),
                },
            )
            chain.append(
                "payout",
                {
                    "type": "payout",
                    "session_id": str(session_id),
                    "summary": "Authoritative gateway payout outcome recorded.",
                    "occurred_at": (now - timedelta(hours=20)).isoformat(),
                },
            )
        chain.append(
            "canary_trigger",
            {
                "type": "canary_trigger",
                "session_id": str(ISOLATED_SESSION_ID),
                "summary": "Scoped canary touched; session isolation requested.",
                "occurred_at": (now - timedelta(hours=8)).isoformat(),
            },
        )

    seal_exists = (
        db.query(IncidentSeal)
        .filter_by(incident_id=DEMO_ISOLATED_INCIDENT_ID)
        .first()
    )
    if seal_exists is None:
        try:
            EvidenceChain(db).seal(
                DEMO_ISOLATED_INCIDENT_ID,
                ISOLATED_SESSION_ID,
                DEMO_MERCHANT_ID,
            )
        except ValueError:
            # An existing unsealed chain may not contain the session events.
            pass


def _seed_demo_honey(db, now: datetime) -> None:
    """Create synthetic honey worlds and canaries without exposing secrets."""
    for session_id in (DECOY_SESSION_ID, ISOLATED_SESSION_ID):
        get_or_create_world(db, str(session_id), str(DEMO_MERCHANT_USER_ID))
        CanaryRegistryService(db).issue(
            str(session_id), str(DEMO_MERCHANT_USER_ID), str(DEMO_MERCHANT_ID)
        )
    # Create a canary for NORMAL_SESSION with a known secret for E2E testing
    # The secret is "E2E_TEST_CANARY_SECRET_KNOWN_VALUE" (not HMAC-derived)
    normal_session_canary = (
        db.query(CanaryRecord)
        .filter_by(session_id=NORMAL_SESSION_ID, kind="api_credential")
        .first()
    )
    if normal_session_canary is None:
        normal_session_canary = CanaryRecord(
            session_id=NORMAL_SESSION_ID,
            identity_id=DEMO_MERCHANT_USER_ID,
            merchant_id=DEMO_MERCHANT_ID,
            kind="api_credential",
            tag="E2E-TEST-CRED",
            secret_value="E2E_TEST_CANARY_SECRET_KNOWN_VALUE",
            armed=True,
            trigger_meta={},
        )
        db.add(normal_session_canary)
    else:
        # Ensure the known secret is set for E2E testing
        normal_session_canary.secret_value = "E2E_TEST_CANARY_SECRET_KNOWN_VALUE"
        normal_session_canary.armed = True
        normal_session_canary.triggered_at = None
        normal_session_canary.trigger_meta = {}
    db.flush()

    triggered = (
        db.query(CanaryRecord)
        .filter_by(session_id=DECOY_SESSION_ID, kind="api_key")
        .first()
    )
    if triggered is not None and triggered.triggered_at is None:
        triggered.triggered_at = now - timedelta(hours=5)
        triggered.trigger_meta = {"route": "/api/honey/credentials", "synthetic": True}


if __name__ == "__main__":
    seed()
