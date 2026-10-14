import uuid
from decimal import Decimal

from app.db.models import OutboxEvent, Payment


async def create_payment(session_factory, **kwargs) -> Payment:
    payment_id = uuid.uuid4()
    payment = Payment(
        id=payment_id,
        amount=Decimal("100.00"),
        currency="RUB",
        description="test",
        metadata_={"k": "v"},
        idempotency_key=str(payment_id),
        request_hash="0" * 64,
        webhook_url="https://example.com/hook",
        **kwargs,
    )
    event = OutboxEvent(event_type="payments.new", aggregate_id=payment_id, payload={"payment_id": str(payment_id)})

    async with session_factory() as session:
        session.add_all([payment, event])
        await session.commit()

    return payment
