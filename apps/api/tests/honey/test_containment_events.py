import uuid

from sqlalchemy import select

from app.models.domain_event import DomainEvent, DomainEventCursor
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord


def test_domain_events_are_ordered_and_rollback_with_business_changes(db_session):
    merchant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    cursor_before = db_session.scalar(
        select(DomainEventCursor.last_event_id).where(
            DomainEventCursor.merchant_id == merchant_id
        )
    )
    cursor_before = cursor_before or 0

    session_record = db_session.get(SessionRecord, session_id)
    session_record.risk_score = 17.0
    db_session.add(
        RiskDecisionRecord(
            session_id=session_id,
            merchant_id=merchant_id,
            risk_score=17.0,
            trust_level="NORMAL",
            action="ALLOW",
            routing_destination="PROVIDER_MOCK",
            reason_codes=[],
            risk_signals={},
        )
    )
    db_session.commit()

    committed = (
        db_session.query(DomainEvent)
        .filter(
            DomainEvent.merchant_id == merchant_id,
            DomainEvent.event_id > cursor_before,
        )
        .order_by(DomainEvent.event_id.asc())
        .all()
    )
    assert [event.event_type for event in committed] == [
        "risk.decision",
        "session.changed",
    ]

    committed_cursor = committed[-1].event_id
    session_record.risk_score = 18.0
    db_session.flush()
    assert (
        db_session.scalar(
            select(DomainEventCursor.last_event_id).where(
                DomainEventCursor.merchant_id == merchant_id
            )
        )
        == committed_cursor + 1
    )
    db_session.rollback()
    db_session.expire_all()

    assert (
        db_session.scalar(
            select(DomainEventCursor.last_event_id).where(
                DomainEventCursor.merchant_id == merchant_id
            )
        )
        == committed_cursor
    )


def test_authenticated_stream_replays_ordered_events_only_for_merchant(
    client, merchant_auth_headers, db_session
):
    session_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    session_record = db_session.get(SessionRecord, session_id)
    session_record.risk_score = 13.0
    db_session.commit()

    own_event = (
        db_session.query(DomainEvent)
        .filter_by(merchant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"))
        .order_by(DomainEvent.event_id.desc())
        .first()
    )
    assert own_event is not None
    other_merchant = uuid.UUID("00000000-0000-0000-0000-000000000099")
    other_cursor = db_session.get(DomainEventCursor, other_merchant)
    if other_cursor is None:
        db_session.add(DomainEventCursor(merchant_id=other_merchant, last_event_id=1))
    else:
        other_cursor.last_event_id += 1
    other_event_id = other_cursor.last_event_id if other_cursor else 1
    other_event = DomainEvent(
        merchant_id=other_merchant,
        event_id=other_event_id,
        event_type="incident.changed",
        entity_type="incidents",
        entity_id=str(uuid.uuid4()),
        operation="created",
        payload={"entity_id": str(uuid.uuid4())},
    )
    db_session.add(other_event)
    db_session.commit()

    with client.stream(
        "GET",
        f"/v1/events/stream?after_event_id={own_event.event_id - 1}",
        headers=merchant_auth_headers,
    ) as response:
        assert response.status_code == 200
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if f"id: {own_event.event_id}" in "".join(chunks):
                break

    body = "".join(chunks)
    assert f"id: {own_event.event_id}" in body
    assert "event: session.changed" in body
    assert str(session_id) in body
    assert str(other_event.entity_id) not in body


def test_reconnect_replays_committed_event_from_database(client, merchant_auth_headers, db_session):
    session_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    session_record = db_session.get(SessionRecord, session_id)
    previous_score = session_record.risk_score
    session_record.risk_score = previous_score + 1.0
    db_session.commit()
    event = (
        db_session.query(DomainEvent)
        .filter_by(
            merchant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            event_type="session.changed",
        )
        .order_by(DomainEvent.event_id.desc())
        .first()
    )
    assert event is not None

    with client.stream(
        "GET",
        "/v1/events/stream",
        headers={**merchant_auth_headers, "Last-Event-ID": str(event.event_id - 1)},
    ) as response:
        assert response.status_code == 200
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if f"id: {event.event_id}" in "".join(chunks):
                break

    assert f"id: {event.event_id}" in "".join(chunks)
    assert "event: session.changed" in "".join(chunks)


def test_domain_event_stream_requires_authentication(client):
    response = client.get("/v1/events/stream")

    assert response.status_code == 401


def test_domain_event_stream_rejects_non_decimal_cursor(client, merchant_auth_headers):
    response = client.get(
        "/v1/events/stream?after_event_id=1.5",
        headers=merchant_auth_headers,
    )

    assert response.status_code == 400
