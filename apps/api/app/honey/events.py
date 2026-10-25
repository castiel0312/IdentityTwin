import asyncio
import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from time import time_ns
from uuid import UUID

from starlette.requests import Request


@dataclass(frozen=True)
class ContainmentEvent:
    event_id: int
    merchant_id: UUID
    incident_id: UUID
    session_id: UUID
    severity: str
    status: str

    def as_sse(self) -> str:
        data = json.dumps(
            {
                "incident_id": str(self.incident_id),
                "session_id": str(self.session_id),
                "severity": self.severity,
                "status": self.status,
            },
            separators=(",", ":"),
        )
        return f"id: {self.event_id}\nevent: incident.contained\ndata: {data}\n\n"


@dataclass(eq=False)
class EventSubscriber:
    loop: asyncio.AbstractEventLoop
    events: asyncio.Queue[ContainmentEvent]
    last_event_id: int


class ContainmentEventBus:
    """Best-effort in-process SSE fan-out; evidence and incidents remain durable."""

    def __init__(self, history_size: int = 100, subscriber_queue_size: int = 100):
        self._lock = threading.Lock()
        self._next_id = time_ns()
        self._history: deque[ContainmentEvent] = deque(maxlen=history_size)
        self._subscribers: dict[UUID, set[EventSubscriber]] = defaultdict(set)
        self._subscriber_queue_size = subscriber_queue_size

    def publish(
        self,
        merchant_id: UUID,
        incident_id: UUID,
        session_id: UUID,
        severity: str,
        status: str,
    ) -> ContainmentEvent:
        with self._lock:
            event = ContainmentEvent(
                event_id=self._next_id,
                merchant_id=merchant_id,
                incident_id=incident_id,
                session_id=session_id,
                severity=severity,
                status=status,
            )
            self._next_id += 1
            self._history.append(event)
            for subscriber in self._subscribers.get(merchant_id, ()):
                subscriber.loop.call_soon_threadsafe(self._enqueue, subscriber, event)
            return event

    def subscribe(
        self,
        merchant_id: UUID,
        after_event_id: int,
        loop: asyncio.AbstractEventLoop,
    ) -> EventSubscriber:
        subscriber = EventSubscriber(
            loop=loop,
            events=asyncio.Queue(maxsize=self._subscriber_queue_size),
            last_event_id=after_event_id,
        )
        with self._lock:
            replay = [
                event
                for event in self._history
                if event.merchant_id == merchant_id and event.event_id > after_event_id
            ]
            for event in replay:
                self._enqueue(subscriber, event)
            self._subscribers[merchant_id].add(subscriber)
        return subscriber

    def unsubscribe(self, merchant_id: UUID, subscriber: EventSubscriber) -> None:
        with self._lock:
            subscribers = self._subscribers.get(merchant_id)
            if subscribers is None:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(merchant_id, None)

    @staticmethod
    def _enqueue(subscriber: EventSubscriber, event: ContainmentEvent) -> None:
        if event.event_id <= subscriber.last_event_id:
            return
        try:
            subscriber.events.put_nowait(event)
        except asyncio.QueueFull:
            try:
                subscriber.events.get_nowait()
            except asyncio.QueueEmpty:
                pass
            subscriber.events.put_nowait(event)
        subscriber.last_event_id = event.event_id


containment_event_bus = ContainmentEventBus()


async def stream_containment_events(request: Request, merchant_id: UUID, after_event_id: int):
    subscriber = containment_event_bus.subscribe(
        merchant_id, after_event_id, asyncio.get_running_loop()
    )
    try:
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(subscriber.events.get(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"
            else:
                yield event.as_sse()
    finally:
        containment_event_bus.unsubscribe(merchant_id, subscriber)
