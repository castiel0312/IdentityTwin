import json
import uuid

from app.core.security import DEV_MERCHANT_ID
from app.honey.events import containment_event_bus


def test_authenticated_stream_replays_only_merchant_scoped_containment_events(
    client, merchant_auth_headers
):
    incident_id = uuid.uuid4()
    session_id = uuid.uuid4()
    event = containment_event_bus.publish(
        merchant_id=DEV_MERCHANT_ID,
        incident_id=incident_id,
        session_id=session_id,
        severity="CRITICAL",
        status="OPEN",
    )
    other_event = containment_event_bus.publish(
        merchant_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        severity="CRITICAL",
        status="OPEN",
    )

    with client.stream(
        "GET",
        f"/v1/events/stream?after_event_id={event.event_id - 1}",
        headers=merchant_auth_headers,
    ) as response:
        assert response.status_code == 200
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if "incident.contained" in "".join(chunks):
                break

    body = "".join(chunks)
    assert f"id: {event.event_id}" in body
    assert "event: incident.contained" in body
    assert str(incident_id) in body
    assert str(session_id) in body
    assert str(other_event.incident_id) not in body
    data_line = next(line[6:] for line in body.splitlines() if line.startswith("data: "))
    assert json.loads(data_line)["severity"] == "CRITICAL"


def test_containment_event_stream_requires_authentication(client):
    response = client.get("/v1/events/stream")

    assert response.status_code == 401
