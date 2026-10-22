import os
import uuid
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set test environment
TEST_DB_PATH = "./identitytwin_test.db"
os.environ["ENVIRONMENT"] = "development"
os.environ["ALLOW_DEV_AUTH"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.db.base import Base
from app.db.session import get_db
from app.gateway.provider import mock_provider_instance
from app.main import app
from app.models.incident import IncidentRecord
from app.models.principal import Merchant, User
from app.models.session import SessionRecord
from app.models.twin import BehavioralTwin, SessionRiskStateRecord
from app.schemas.incidents import IncidentSeverity, IncidentStatus
from app.schemas.sessions import SessionStatus, TrustLevel

# Test Engine backed by file for persistent cross-session testing
test_engine = create_engine(
    f"sqlite:///{TEST_DB_PATH}",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

TEST_MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TEST_ANALYST_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

NORMAL_SESSION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
RESTRICTED_SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
DECOY_SESSION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
ISOLATED_SESSION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
TEST_INCIDENT_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass
    Base.metadata.create_all(bind=test_engine)

    # Seed permanent base records for the test session
    seed_db = TestingSessionLocal()
    m1 = Merchant(merchant_id=TEST_MERCHANT_ID, name="Test Merchant 1", slug="test-m1")
    m2 = Merchant(merchant_id=OTHER_MERCHANT_ID, name="Other Merchant", slug="test-m2")
    u1 = User(
        user_id=TEST_USER_ID,
        merchant_id=TEST_MERCHANT_ID,
        email="merchant@test.com",
        role="merchant",
    )
    u_analyst = User(
        user_id=TEST_ANALYST_ID,
        merchant_id=TEST_MERCHANT_ID,
        email="analyst@test.com",
        role="analyst",
    )
    seed_db.add_all([m1, m2, u1, u_analyst])
    seed_db.commit()
    seed_db.close()

    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    now = datetime.now(timezone.utc)

    # Upsert or ensure base sessions exist
    for s_id, t_level, r_score in [
        (NORMAL_SESSION_ID, TrustLevel.NORMAL.value, 0.0),
        (RESTRICTED_SESSION_ID, TrustLevel.RESTRICTED.value, 45.0),
        (DECOY_SESSION_ID, TrustLevel.DECOY.value, 75.0),
        (ISOLATED_SESSION_ID, TrustLevel.ISOLATED.value, 95.0),
    ]:
        existing = session.query(SessionRecord).filter_by(session_id=s_id).first()
        if not existing:
            sess = SessionRecord(
                session_id=s_id,
                user_id=TEST_USER_ID,
                merchant_id=TEST_MERCHANT_ID,
                trust_level=t_level,
                risk_score=r_score,
                status=SessionStatus.ACTIVE.value,
                last_activity_at=now,
            )
            session.add(sess)
        else:
            existing.trust_level = t_level
            existing.risk_score = r_score
            existing.status = SessionStatus.ACTIVE.value
            existing.last_activity_at = now

    existing_inc = session.query(IncidentRecord).filter_by(incident_id=TEST_INCIDENT_ID).first()
    if not existing_inc:
        inc = IncidentRecord(
            incident_id=TEST_INCIDENT_ID,
            merchant_id=TEST_MERCHANT_ID,
            session_id=RESTRICTED_SESSION_ID,
            title="Test Anomaly Incident",
            description="Test incident for analyst approval",
            severity=IncidentSeverity.HIGH.value,
            status=IncidentStatus.OPEN.value,
            risk_score=80.0,
            trigger_reason="TEST_ANOMALY",
            evidence_summary={"sample": 123},
        )
        session.add(inc)

    session.commit()

    yield session

    session.close()


@pytest.fixture(autouse=True)
def reset_behavioral_state(db_session: Session) -> Generator[None, None, None]:
    """Person 2: every test starts from a clean behavioural twin baseline.

    The behavioural twin and the session risk ledger are persistent state that
    is shared per identity. Resetting them between tests keeps the existing
    Person 1 suite deterministic and independent of execution order.
    """
    db_session.query(BehavioralTwin).delete()
    db_session.query(SessionRiskStateRecord).delete()
    db_session.commit()
    yield


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    mock_provider_instance.reset()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def merchant_auth_headers() -> dict:
    return {
        "Authorization": "Bearer dev-merchant-token",
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_USER_ID),
    }


@pytest.fixture
def analyst_auth_headers() -> dict:
    return {
        "Authorization": "Bearer dev-analyst-token",
        "X-Dev-Role": "analyst",
        "X-Dev-Merchant-Id": str(TEST_MERCHANT_ID),
        "X-Dev-User-Id": str(TEST_ANALYST_ID),
    }


@pytest.fixture
def other_merchant_auth_headers() -> dict:
    return {
        "Authorization": "Bearer dev-other-merchant-token",
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": str(OTHER_MERCHANT_ID),
        "X-Dev-User-Id": str(uuid.uuid4()),
    }
