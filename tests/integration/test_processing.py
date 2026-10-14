import uuid

import pytest
from sqlalchemy.exc import NoResultFound

from app.external.webhook import WebhookDeliveryError
from app.services.processing import PaymentProcessingService
from tests.integration.helpers import create_payment

pytestmark = pytest.mark.integration


class FakeGateway:
    def __init__(self, succeeded: bool = True):
        self.succeeded = succeeded
        self.calls = 0

    async def charge(self, **_) -> bool:
        self.calls += 1
        return self.succeeded


class FakeWebhook:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = []

    async def send(self, payload: dict, **_) -> None:
        self.calls.append(payload)
        if len(self.calls) <= self.fail_times:
            raise WebhookDeliveryError("HTTP 500")


@pytest.fixture
def make_service(adapters, session_factory):
    def make(gateway: FakeGateway, webhook: FakeWebhook) -> PaymentProcessingService:
        adapters.gateway = gateway
        adapters.webhook = webhook
        return PaymentProcessingService(adapters=adapters, session_factory=session_factory)

    return make


@pytest.mark.parametrize(("succeeded", "status"), [(True, "succeeded"), (False, "failed")])
async def test_process_payment(make_service, session_factory, succeeded, status):
    payment = await create_payment(session_factory)
    gateway, webhook = FakeGateway(succeeded=succeeded), FakeWebhook()

    result = await make_service(gateway, webhook).process(payment_id=payment.id)

    assert result.status == status
    assert result.processed_at is not None
    assert result.webhook_delivered_at is not None
    assert gateway.calls == 1
    assert len(webhook.calls) == 1
    assert webhook.calls[0]["payment_id"] == str(payment.id)
    assert webhook.calls[0]["status"] == status
    assert webhook.calls[0]["amount"] == "100.00"
    assert webhook.calls[0]["metadata"] == {"k": "v"}


async def test_webhook_failure_keeps_result_and_retry_does_not_charge_again(make_service, session_factory):
    payment = await create_payment(session_factory)
    gateway, webhook = FakeGateway(), FakeWebhook(fail_times=1)
    service = make_service(gateway, webhook)

    with pytest.raises(WebhookDeliveryError):
        await service.process(payment_id=payment.id)

    # Результат шлюза сохранён, хотя уведомление не ушло
    after_failure = await service.services.payment.get_payment(payment_id=payment.id)
    assert after_failure.status == "succeeded"
    assert after_failure.webhook_delivered_at is None

    # Повтор (ретрай из очереди) только дошлёт webhook
    result = await service.process(payment_id=payment.id)

    assert gateway.calls == 1
    assert len(webhook.calls) == 2
    assert result.webhook_delivered_at is not None


async def test_duplicate_message_after_success_is_noop(make_service, session_factory):
    payment = await create_payment(session_factory)
    gateway, webhook = FakeGateway(), FakeWebhook()
    service = make_service(gateway, webhook)

    await service.process(payment_id=payment.id)
    await service.process(payment_id=payment.id)

    assert gateway.calls == 1
    assert len(webhook.calls) == 1


async def test_unknown_payment_raises(make_service):
    with pytest.raises(NoResultFound):
        await make_service(FakeGateway(), FakeWebhook()).process(payment_id=uuid.uuid4())
