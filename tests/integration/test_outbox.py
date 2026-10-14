import asyncio

import pytest
from sqlalchemy import select

from app.db.models import OutboxEvent
from app.services.outbox import OutboxService
from tests.integration.helpers import create_payment

pytestmark = pytest.mark.integration


class FakeBroker:
    def __init__(self, fail: bool = False, delay: float = 0):
        self.fail = fail
        self.delay = delay
        self.published = []

    async def publish(self, message, **kwargs) -> None:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("broker is down")
        self.published.append((message, kwargs))


async def get_events(session_factory) -> list[OutboxEvent]:
    async with session_factory() as session:
        query = await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))
        return list(query.scalars().all())


async def test_publish_pending_events(adapters, session_factory):
    payments = [await create_payment(session_factory) for _ in range(3)]
    adapters.broker = FakeBroker()

    published = await OutboxService(adapters=adapters, session_factory=session_factory).publish_pending()

    assert published == 3
    messages = [message for message, _ in adapters.broker.published]
    assert messages == [{"payment_id": str(p.id)} for p in payments]

    _, kwargs = adapters.broker.published[0]
    assert kwargs["routing_key"] == "payments.new"
    assert kwargs["exchange"].name == "payments"
    assert kwargs["persist"] is True
    assert kwargs["headers"] == {"x-attempt": 1}

    events = await get_events(session_factory)
    assert all(event.published_at is not None for event in events)

    # Повторный проход ничего не отправляет
    assert await OutboxService(adapters=adapters, session_factory=session_factory).publish_pending() == 0
    assert len(adapters.broker.published) == 3


async def test_broker_failure_keeps_event_in_outbox(adapters, session_factory):
    await create_payment(session_factory)
    adapters.broker = FakeBroker(fail=True)

    published = await OutboxService(adapters=adapters, session_factory=session_factory).publish_pending()

    assert published == 0
    [event] = await get_events(session_factory)
    assert event.published_at is None
    assert event.attempts == 1
    assert "broker is down" in event.last_error

    # Брокер ожил — событие уходит
    adapters.broker = FakeBroker()
    assert await OutboxService(adapters=adapters, session_factory=session_factory).publish_pending() == 1


async def test_parallel_relays_publish_each_event_once(adapters, session_factory):
    for _ in range(20):
        await create_payment(session_factory)

    adapters.broker = FakeBroker(delay=0.01)
    adapters.config.outbox.OUTBOX_BATCH_SIZE = 5

    async def relay() -> None:
        service = OutboxService(adapters=adapters, session_factory=session_factory)
        while await service.publish_pending():
            pass

    await asyncio.gather(*[relay() for _ in range(4)])

    ids = [message["payment_id"] for message, _ in adapters.broker.published]
    assert len(ids) == 20
    assert len(set(ids)) == 20
