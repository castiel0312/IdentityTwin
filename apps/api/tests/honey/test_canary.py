from app.honey.canary import CanaryRegistryService
from app.models.canary import CanaryRecord
from tests.conftest import (
    NORMAL_SESSION_ID,
    RESTRICTED_SESSION_ID,
    TEST_MERCHANT_ID,
    TEST_USER_ID,
)


def test_canary_issue_and_hit(db_session):
    reg = CanaryRegistryService(db_session)
    sid = str(NORMAL_SESSION_ID)
    issued = reg.issue(sid, str(TEST_USER_ID), str(TEST_MERCHANT_ID))
    assert len(issued) == 5
    canary = issued[0]
    hit = reg.check(
        {
            "body": {"client_secret": canary["secret_value"]},
            "session_id": sid,
            "identity_id": str(TEST_USER_ID),
            "merchant_id": str(TEST_MERCHANT_ID),
            "matched_in": "test",
        }
    )
    assert hit is not None
    assert hit["hit"] is True
    assert hit["kind"] in [
        "api_credential",
        "customer_record",
        "invoice_export",
        "honey_endpoint",
        "honey_account",
    ]
    # Second check should not hit (disarmed)
    hit2 = reg.check(
        {
            "body": {"client_secret": canary["secret_value"]},
            "session_id": sid,
            "identity_id": str(TEST_USER_ID),
            "merchant_id": str(TEST_MERCHANT_ID),
        }
    )
    assert hit2 is None


def test_canary_cannot_be_used_across_sessions(db_session):
    reg = CanaryRegistryService(db_session)
    sid1 = str(NORMAL_SESSION_ID)
    sid2 = str(RESTRICTED_SESSION_ID)
    issued = reg.issue(sid1, str(TEST_USER_ID), str(TEST_MERCHANT_ID))
    canary = issued[0]
    hit = reg.check(
        {
            "body": {"client_secret": canary["secret_value"]},
            "session_id": sid2,
            "identity_id": str(TEST_USER_ID),
            "merchant_id": str(TEST_MERCHANT_ID),
            "matched_in": "other",
        }
    )
    assert hit is None
    canary_record = db_session.query(CanaryRecord).filter_by(tag=canary["tag"]).one()
    assert canary_record.armed is True
