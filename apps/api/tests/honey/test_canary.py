import uuid

from app.honey.canary import CanaryRegistryService


def test_canary_issue_and_hit(db_session):
    reg = CanaryRegistryService(db_session)
    sid = str(uuid.uuid4())
    issued = reg.issue(sid)
    assert len(issued) == 5
    canary = issued[0]
    hit = reg.check(
        {"body": {"client_secret": canary["secret_value"]}, "session_id": sid, "matched_in": "test"}
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
    hit2 = reg.check({"body": {"client_secret": canary["secret_value"]}, "session_id": sid})
    assert hit2 is None


def test_canary_cross_session(db_session):
    reg = CanaryRegistryService(db_session)
    sid1 = str(uuid.uuid4())
    sid2 = str(uuid.uuid4())
    issued = reg.issue(sid1)
    canary = issued[0]
    hit = reg.check(
        {
            "body": {"client_secret": canary["secret_value"]},
            "session_id": sid2,
            "matched_in": "other",
        }
    )
    assert hit is not None
    assert hit["cross_session_reuse"] is True
