"""
P3 Automated PayPal Reconciliation Worker — PostgreSQL test suite.

These tests run against a real PostgreSQL database
(``identitytwin_reconciliation_test``) and exercise the background
reconciliation worker end to end:

1. successful automatic reconciliation
2. failed automatic reconciliation
3. processing status stays unresolved
4. missing provider batch id → escalated, never resubmitted
5. retry and exponential backoff
6. maximum retry exhaustion → manual escalation
7. concurrent worker execution (no duplicate processing)
8. duplicate reconciliation is idempotent
9. application restart and recovery
10. reservation correctness (exactly-once consume / release)
11. cross-merchant isolation
12. graceful shutdown

The shared ``conftest.py`` configures SQLite; these tests deliberately bypass
it and use a dedicated PostgreSQL engine/session so the worker's
``SELECT ... FOR UPDATE SKIP LOCKED`` locking is exercised on its real dialect.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, make_url, table, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.repositories.reconciliation_repo import ReconciliationRepository
from app.gateway.provider import ProviderPayoutResult
from app.gateway.reconciliation_worker import ReconciliationWorker
from app.gateway.service import TrustGatewayService
from app.models.agent import AgentAuthorizationGrant, AgentRegistration
from app.models.payout import PayoutRequestRecord
from app.models.principal import Merchant, User
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.schemas.sessions import SessionStatus, TrustLevel

# ---------------------------------------------------------------------------
# Dedicated PostgreSQL test database
# ---------------------------------------------------------------------------
PG_DATABASE_URL = os.environ.get(
    "IDENTITYTWIN_RECONCILIATION_TEST_DATABASE_URL",
    "postgresql+psycopg://identitytwin_test:identitytwin_test"
    "@127.0.0.1:55432/identitytwin_reconciliation_test",
)
if make_url(PG_DATABASE_URL).database != "identitytwin_reconciliation_test":
    raise ValueError(
        "IDENTITYTWIN_RECONCILIATION_TEST_DATABASE_URL must target the dedicated "
        "'identitytwin_reconciliation_test' database; this test suite drops its tables."
    )

pg_engine = create_engine(PG_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

TEST_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000201")
TEST_USER_ID = UUID("11111111-1111-1111-1111-111111111201")
TEST_USER_2_ID = UUID("11111111-1111-1111-1111-111111111202")

NORMAL_SESSION_ID = UUID("22222222-2222-2222-2222-222222222201")
OTHER_SESSION_ID = UUID("22222222-2222-2222-2222-222222222202")


# ---------------------------------------------------------------------------
# Test double provider: controllable batch status, never touches the network.
# ---------------------------------------------------------------------------
class FakeReconciliationProvider:
    """Fake payment provider for reconciliation tests.

    ``get_payout_batch`` returns a configurable batch status per batch id.
    Not a PayPal adapter: no credentials, no network, no sensitive data.
    """

    def __init__(self):
        self.batches: dict[str, str] = {}
        self.invocation_count = 0

    def get_payout_batch(self, payout_batch_id: str) -> ProviderPayoutResult | None:
        self.invocation_count += 1
        status = self.batches.get(payout_batch_id, "PENDING")
        return ProviderPayoutResult(
            success=status == "SUCCESS",
            provider_name="fake_provider",
            provider_transaction_id=payout_batch_id,
            environment="fake",
            details={"batch_status": status},
            executed_at=datetime.now(timezone.utc),
            batch_status=status,
            provider_batch_id=payout_batch_id,
        )

    def execute_payout(self, request, merchant_id):  # pragma: no cover - unused
        raise NotImplementedError

    def verify_webhook_signature(self, headers, raw_body):  # pragma: no cover - unused
        return False


# ---------------------------------------------------------------------------
# PostgreSQL fixtures
# ---------------------------------------------------------------------------
_TABLES_FOR_WIPE = (
    "agentic_commerce_audit",
    "payout_requests",
    "agent_authorization_grants",
    "risk_decisions",
    "agent_registrations",
    "sessions",
    "users",
    "merchants",
)


def _wipe_tables(session):
    for table_name in _TABLES_FOR_WIPE:
        session.execute(delete(table(table_name)))
    session.commit()


@pytest.fixture(scope="module", autouse=True)
def pg_schema():
    """Create all tables once per module on PostgreSQL, drop at the end."""
    with pg_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS honey"))
    Base.metadata.create_all(bind=pg_engine)
    yield
    Base.metadata.drop_all(bind=pg_engine)
    pg_engine.dispose()


@pytest.fixture(autouse=True)
def db():
    """Fresh PostgreSQL session per test; all tables wiped afterwards for isolation."""
    session = TestingSessionLocal()
    yield session
    session.close()
    wipe_session = TestingSessionLocal()
    try:
        _wipe_tables(wipe_session)
    finally:
        wipe_session.close()


@pytest.fixture
def seed_merchant(db):
    merchant = Merchant(merchant_id=TEST_MERCHANT_ID, name="Test Merchant", slug="test-merchant")
    other = Merchant(merchant_id=OTHER_MERCHANT_ID, name="Other Merchant", slug="other-merchant")
    user = User(
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        email="merchant@test.com",
        role="merchant",
    )
    user_2 = User(
        user_id=TEST_USER_2_ID,
        merchant_id=OTHER_MERCHANT_ID,
        email="other@test.com",
        role="merchant",
    )
    db.add_all([merchant, other, user, user_2])
    db.commit()
    return {
        "merchant": merchant,
        "other": other,
        "user": user,
        "user_2": user_2,
    }


def _make_decision(db, session_id, merchant_id):
    decision = RiskDecisionRecord(
        decision_id=uuid4(),
        session_id=session_id,
        merchant_id=merchant_id,
        risk_score=0.0,
        trust_level=TrustLevel.NORMAL.value,
        action="ALLOW",
        routing_destination="PROVIDER_PAYPAL",
        reason_codes=["POLICY_NORMAL_EXECUTION_PERMITTED"],
        risk_signals={},
        evaluated_at=datetime.now(timezone.utc),
    )
    db.add(decision)
    db.flush()
    return decision


def _make_session(db, session_id, merchant_id, user_id):
    session = SessionRecord(
        session_id=session_id,
        user_id=user_id,
        merchant_id=merchant_id,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
        last_activity_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()
    return session


def _make_grant(db, session_id, merchant_id, reserved_amount=0.0):
    agent_id = uuid4()
    agent = AgentRegistration(
        agent_id=agent_id,
        merchant_id=merchant_id,
        display_name="Test Agent",
        agent_type="shopping_assistant",
        scopes=["payout.execute"],
        status="active",
        is_active=True,
    )
    db.add(agent)
    db.flush()
    grant = AgentAuthorizationGrant(
        grant_id=uuid4(),
        agent_id=agent_id,
        merchant_id=merchant_id,
        user_id=TEST_USER_ID,
        session_id=session_id,
        scopes=["payout.execute"],
        max_amount=10000.0,
        total_consumed_amount=0.0,
        reserved_amount=reserved_amount,
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(grant)
    db.flush()
    return grant


def _create_payout(
    db,
    *,
    merchant_id,
    user_id,
    session_id,
    decision_id,
    status="pending",
    provider_batch_id="BATCH-1",
    provider_name="fake_provider",
    amount=100.0,
    created_at=None,
    reconciliation_attempts=0,
    next_retry_at=None,
    escalated_at=None,
):
    payout = PayoutRequestRecord(
        payout_id=uuid4(),
        decision_id=decision_id,
        session_id=session_id,
        merchant_id=merchant_id,
        user_id=user_id,
        recipient_email="contractor@example.com",
        amount=amount,
        currency="USD",
        reference_note="test payout",
        idempotency_key=f"idem-{uuid4()}",
        status=status,
        provider_name=provider_name,
        provider_reference=provider_batch_id,
        provider_batch_id=provider_batch_id,
        sender_batch_id=None,
        sender_item_id=None,
        provider_payload={},
        executed_at=None,
        reconciliation_attempts=reconciliation_attempts,
        next_retry_at=next_retry_at,
        escalated_at=escalated_at,
    )
    if created_at is not None:
        payout.created_at = created_at
    db.add(payout)
    db.flush()
    return payout


def _make_service(fake_provider):
    return TrustGatewayService(
        policy=None,
        risk_engine=None,
        provider_adapter=fake_provider,
        decoy_adapter=None,
    )


def _make_worker(service, interval=1.0):
    return ReconciliationWorker(
        gateway_service=service,
        session_factory=TestingSessionLocal,
        interval=interval,
        batch_size=50,
    )


# ---------------------------------------------------------------------------
# 1. Successful automatic reconciliation
# ---------------------------------------------------------------------------
def test_successful_automatic_reconciliation(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["BATCH-SUCCESS"] = "SUCCESS"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    grant = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=100.0)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="BATCH-SUCCESS",
        amount=100.0,
    )
    db.commit()

    worker._reconcile_cycle()

    db.refresh(payout)
    assert payout.status == "completed"
    assert payout.reconciliation_attempts == 1
    assert payout.last_reconciled_at is not None
    assert payout.next_retry_at is None
    assert payout.escalated_at is None

    # Reservation consumed exactly once.
    db.refresh(grant)
    assert grant.total_consumed_amount == 100.0
    assert grant.reserved_amount == 0.0

    # Idempotent: re-running reconciliation on a completed payout changes nothing.
    worker._reconcile_cycle()
    db.refresh(payout)
    assert payout.status == "completed"
    assert payout.reconciliation_attempts == 1  # not incremented again


# ---------------------------------------------------------------------------
# 2. Failed automatic reconciliation
# ---------------------------------------------------------------------------
def test_failed_automatic_reconciliation(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["BATCH-FAIL"] = "FAILED"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    grant = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=100.0)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="BATCH-FAIL",
        amount=100.0,
    )
    db.commit()

    worker._reconcile_cycle()

    db.refresh(payout)
    assert payout.status == "failed"
    assert payout.reconciliation_attempts == 1
    assert payout.next_retry_at is None
    assert payout.escalated_at is None

    # Reservation released exactly once.
    db.refresh(grant)
    assert grant.reserved_amount == 0.0
    assert grant.total_consumed_amount == 0.0


# ---------------------------------------------------------------------------
# 3. Processing status remains unresolved
# ---------------------------------------------------------------------------
def test_processing_remains_unresolved(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["BATCH-PROC"] = "PROCESSING"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="BATCH-PROC",
        amount=100.0,
    )
    db.commit()

    worker._reconcile_cycle()

    db.refresh(payout)
    assert payout.status == "processing"
    assert payout.reconciliation_attempts == 1
    # Retry scheduled, not resolved, not escalated, reservation untouched.
    assert payout.next_retry_at is not None
    assert payout.next_retry_at > datetime.now(timezone.utc)
    assert payout.escalated_at is None


# ---------------------------------------------------------------------------
# 4. Missing provider batch id → escalated, never automatically resubmitted
# ---------------------------------------------------------------------------
def test_missing_provider_batch_id_escalated(db, seed_merchant):
    service = _make_service(FakeReconciliationProvider())
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id=None,
        amount=100.0,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.commit()

    worker._reconcile_cycle()

    db.refresh(payout)
    assert payout.escalated_at is not None
    assert payout.escalation_reason == "no_provider_reference"
    assert payout.next_retry_at is None
    assert payout.status == "pending"  # not resubmitted, not marked failed

    # The provider must never be invoked for a payout without a batch id.
    assert service.provider_adapter.invocation_count == 0


# ---------------------------------------------------------------------------
# 5. Retry and exponential backoff
# ---------------------------------------------------------------------------
def test_retry_and_exponential_backoff(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["BACKOFF-BATCH"] = "PROCESSING"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="BACKOFF-BATCH",
        amount=100.0,
    )
    db.commit()

    now = datetime.now(timezone.utc)

    # Cycle 1: attempt 1, backoff 30s.
    worker._reconcile_cycle()
    db.refresh(payout)
    assert payout.status == "processing"
    assert payout.reconciliation_attempts == 1
    delta1 = (payout.next_retry_at - payout.last_reconciled_at).total_seconds()
    assert abs(delta1 - 30.0) < 2, f"expected ~30s, got {delta1}"

    # Simulate the retry interval elapsing.
    payout.next_retry_at = now
    db.commit()

    # Cycle 2: attempt 2, backoff 60s.
    worker._reconcile_cycle()
    db.refresh(payout)
    assert payout.reconciliation_attempts == 2
    delta2 = (payout.next_retry_at - payout.last_reconciled_at).total_seconds()
    assert abs(delta2 - 60.0) < 2, f"expected ~60s, got {delta2}"

    payout.next_retry_at = now
    db.commit()

    # Cycle 3: attempt 3, backoff 120s.
    worker._reconcile_cycle()
    db.refresh(payout)
    assert payout.reconciliation_attempts == 3
    delta3 = (payout.next_retry_at - payout.last_reconciled_at).total_seconds()
    assert abs(delta3 - 120.0) < 2, f"expected ~120s, got {delta3}"

    assert fake_provider.invocation_count == 3


# ---------------------------------------------------------------------------
# 6. Maximum retry exhaustion → manual escalation
# ---------------------------------------------------------------------------
def test_maximum_retry_exhaustion(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["EXHAUST-BATCH"] = "PROCESSING"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="EXHAUST-BATCH",
        amount=100.0,
    )
    db.commit()

    now = datetime.now(timezone.utc)
    for i in range(1, 11):
        worker._reconcile_cycle()
        db.refresh(payout)
        assert payout.reconciliation_attempts == i, f"expected attempt {i}"
        if i < 10:
            assert payout.escalated_at is None
            assert payout.next_retry_at is not None
            payout.next_retry_at = now
            db.commit()
        else:
            # 10th automated attempt: escalated, not resolved, no retry.
            assert payout.escalated_at is not None
            assert payout.escalation_reason == "max_reconciliation_attempts_exhausted"
            assert payout.next_retry_at is None
            assert payout.status == "processing"  # unresolved

    # Retry exhaustion must NOT release the reservation, mark failed, or
    # delete idempotency records. (No grant here, so no reservation; assert
    # status stayed unresolved and provider was invoked exactly 10 times.)
    assert payout.status != "failed"
    assert fake_provider.invocation_count == 10


# ---------------------------------------------------------------------------
# 7. Concurrent worker execution (no duplicate processing)
# ---------------------------------------------------------------------------
def test_concurrent_worker_execution(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    statuses = {f"BATCH-CONC-{i}": "SUCCESS" if i % 2 == 0 else "FAILED" for i in range(10)}
    fake_provider.batches = statuses
    service = _make_service(fake_provider)

    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)

    payouts = []
    for i in range(10):
        _grant = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=50.0)
        conc_decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
        payouts.append(
            _create_payout(
                db,
                merchant_id=TEST_MERCHANT_ID,
                user_id=TEST_USER_ID,
                session_id=NORMAL_SESSION_ID,
                decision_id=conc_decision.decision_id,
                status="pending",
                provider_batch_id=f"BATCH-CONC-{i}",
                amount=50.0,
            )
        )
    db.commit()

    def run_cycle():
        worker = _make_worker(service)
        worker._reconcile_cycle()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_cycle) for _ in range(4)]
        for f in futures:
            f.result()

    # Each payout processed exactly once.
    for p in payouts:
        db.refresh(p)
        assert p.reconciliation_attempts == 1, (
            f"payout {p.payout_id} processed {p.reconciliation_attempts} times"
        )

    assert fake_provider.invocation_count == 10


# ---------------------------------------------------------------------------
# 8. Duplicate reconciliation is idempotent
# ---------------------------------------------------------------------------
def test_duplicate_reconciliation_idempotent(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["IDEMP-BATCH"] = "SUCCESS"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    grant = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=75.0)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="IDEMP-BATCH",
        amount=75.0,
    )
    db.commit()

    worker._reconcile_cycle()
    worker._reconcile_cycle()
    worker._reconcile_cycle()

    db.refresh(payout)
    assert payout.status == "completed"
    assert payout.reconciliation_attempts == 1  # reconciled once
    assert fake_provider.invocation_count == 1  # provider polled once

    db.refresh(grant)
    assert grant.total_consumed_amount == 75.0  # consumed exactly once
    assert grant.reserved_amount == 0.0


# ---------------------------------------------------------------------------
# 9. Application restart and recovery
# ---------------------------------------------------------------------------
def test_application_restart_and_recovery(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["RESTART-BATCH"] = "PROCESSING"
    service = _make_service(fake_provider)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="RESTART-BATCH",
        amount=100.0,
    )
    db.commit()

    now = datetime.now(timezone.utc)

    # First "process instance": reconciles once, schedules retry.
    worker_a = _make_worker(service)
    worker_a._reconcile_cycle()
    db.refresh(payout)
    assert payout.reconciliation_attempts == 1
    assert payout.status == "processing"

    # Simulate crash/restart: a brand-new worker instance picks up the same
    # database state after the retry interval elapses.
    payout.next_retry_at = now
    db.commit()

    worker_b = _make_worker(service)
    worker_b._reconcile_cycle()
    db.refresh(payout)
    assert payout.reconciliation_attempts == 2  # recovery continued from state

    # Resolve on the third "restart".
    payout.next_retry_at = now
    fake_provider.batches["RESTART-BATCH"] = "SUCCESS"
    db.commit()

    worker_c = _make_worker(service)
    worker_c._reconcile_cycle()
    db.refresh(payout)
    assert payout.status == "completed"
    assert payout.reconciliation_attempts == 3


# ---------------------------------------------------------------------------
# 10. Reservation correctness
# ---------------------------------------------------------------------------
def test_reservation_correctness(db, seed_merchant):
    # SUCCESS consumes reservation exactly once.
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["RES-SUCCESS"] = "SUCCESS"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    grant = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=200.0)
    _payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="RES-SUCCESS",
        amount=200.0,
    )
    db.commit()

    worker._reconcile_cycle()
    db.refresh(grant)
    assert grant.total_consumed_amount == 200.0
    assert grant.reserved_amount == 0.0

    # FAILED releases reservation exactly once.
    fake_provider.batches["RES-FAIL"] = "FAILED"
    grant2 = _make_grant(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, reserved_amount=150.0)
    decision2 = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    _payout2 = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision2.decision_id,
        status="pending",
        provider_batch_id="RES-FAIL",
        amount=150.0,
    )
    db.commit()

    worker._reconcile_cycle()
    db.refresh(grant2)
    assert grant2.reserved_amount == 0.0
    assert grant2.total_consumed_amount == 0.0


# ---------------------------------------------------------------------------
# 11. Cross-merchant isolation
# ---------------------------------------------------------------------------
def test_cross_merchant_isolation(db, seed_merchant):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["ISO-M1"] = "SUCCESS"
    fake_provider.batches["ISO-M2"] = "SUCCESS"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _m1 = seed_merchant["merchant"]
    _u1 = seed_merchant["user"]
    _m2 = seed_merchant["other"]
    _u2 = seed_merchant["user_2"]

    _s1 = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    _s2 = _make_session(db, OTHER_SESSION_ID, OTHER_MERCHANT_ID, TEST_USER_2_ID)
    d1 = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    d2 = _make_decision(db, OTHER_SESSION_ID, OTHER_MERCHANT_ID)

    payout_m1 = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=d1.decision_id,
        status="pending",
        provider_batch_id="ISO-M1",
        amount=100.0,
    )
    payout_m2 = _create_payout(
        db,
        merchant_id=OTHER_MERCHANT_ID,
        user_id=TEST_USER_2_ID,
        session_id=OTHER_SESSION_ID,
        decision_id=d2.decision_id,
        status="pending",
        provider_batch_id="ISO-M2",
        amount=100.0,
    )
    db.commit()

    worker._reconcile_cycle()

    db.refresh(payout_m1)
    db.refresh(payout_m2)
    assert payout_m1.status == "completed"
    assert payout_m2.status == "completed"

    # Reconciliation is merchant-scoped: a query for merchant 1 must not
    # return merchant 2's payouts.
    repo = ReconciliationRepository(db)
    items, total = repo.list_for_merchant(TEST_MERCHANT_ID)
    assert all(i.merchant_id == TEST_MERCHANT_ID for i in items)
    assert payout_m2.payout_id not in {i.payout_id for i in items}

    # The provider was invoked once per payout (both merchants reconciled).
    assert fake_provider.invocation_count == 2


# ---------------------------------------------------------------------------
# 12. Graceful shutdown
# ---------------------------------------------------------------------------
def test_graceful_shutdown():
    service = _make_service(FakeReconciliationProvider())
    worker = _make_worker(service, interval=1.0)

    import asyncio

    async def _go():
        await worker.start()
        assert worker._task is not None and not worker._task.done()
        await worker.stop()
        assert worker._task is None

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# Stuck payout alert (> 30 minutes unresolved)
# ---------------------------------------------------------------------------
def test_stuck_payout_alert(db, seed_merchant, caplog):
    fake_provider = FakeReconciliationProvider()
    fake_provider.batches["STUCK-BATCH"] = "PROCESSING"
    service = _make_service(fake_provider)
    worker = _make_worker(service)

    _merchant = seed_merchant["merchant"]
    _user = seed_merchant["user"]
    _session = _make_session(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID, TEST_USER_ID)
    decision = _make_decision(db, NORMAL_SESSION_ID, TEST_MERCHANT_ID)
    payout = _create_payout(
        db,
        merchant_id=TEST_MERCHANT_ID,
        user_id=TEST_USER_ID,
        session_id=NORMAL_SESSION_ID,
        decision_id=decision.decision_id,
        status="pending",
        provider_batch_id="STUCK-BATCH",
        amount=100.0,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=45),
    )
    db.commit()

    with caplog.at_level("ERROR", logger="identitytwin.reconciliation"):
        worker._reconcile_cycle()

    assert any("stuck_payout" in rec.getMessage() for rec in caplog.records)
    db.refresh(payout)
    assert payout.status == "processing"  # still unresolved
