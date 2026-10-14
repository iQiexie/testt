import traceback

import structlog
from faststream import AckPolicy
from faststream.exceptions import RejectMessage
from faststream.rabbit import Channel, RabbitBroker, RabbitMessage
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.broker.topology import PAYMENTS_EXCHANGE, PAYMENTS_NEW_QUEUE, RETRY_EXCHANGE, retry_delay, retry_queue
from app.config.constants import BROKER_PUBLISH_TIMEOUT, HEADER_ATTEMPT, HEADER_LAST_ERROR
from app.services.dto.payment import PaymentNewEvent
from app.services.processing import PaymentProcessingService

logger = structlog.stdlib.get_logger()


def register_handlers(broker: RabbitBroker, adapters: Adapters, session_factory: sessionmaker) -> None:
    config = adapters.config.consumer

    # REJECT_ON_ERROR: необработанное исключение (в том числе невалидное тело, которое не прошло
    # PaymentNewEvent) — reject без requeue, и очередь сама перекладывает сообщение в DLQ через DLX
    @broker.subscriber(
        queue=PAYMENTS_NEW_QUEUE,
        exchange=PAYMENTS_EXCHANGE,
        channel=Channel(prefetch_count=config.CONSUMER_PREFETCH_COUNT),
        ack_policy=AckPolicy.REJECT_ON_ERROR,
    )
    async def handle_payment_new(event: PaymentNewEvent, message: RabbitMessage) -> None:
        attempt = int(message.headers.get(HEADER_ATTEMPT, 1))
        log = logger.bind(payment_id=str(event.payment_id), attempt=attempt, message_id=message.message_id)

        service = PaymentProcessingService(adapters=adapters, session_factory=session_factory)

        try:
            await service.process(payment_id=event.payment_id)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

            if attempt >= config.CONSUMER_MAX_ATTEMPTS:
                log.error(
                    "Payment message failed, moving to DLQ",
                    error=error,
                    exception=traceback.format_exception(e),
                )
                raise RejectMessage()

            delay = retry_delay(attempt=attempt, base_delay=config.CONSUMER_RETRY_BASE_DELAY)
            log.warning("Payment message failed, scheduling retry", error=error, retry_in_seconds=delay)

            # Сначала публикуем копию в очередь ожидания (с подтверждением брокера), потом ack оригинала.
            # Падение между ними даст дубль, а не потерю — consumer идемпотентен.
            await broker.publish(
                message.body,
                exchange=RETRY_EXCHANGE,
                routing_key=retry_queue(attempt=attempt, config=config).routing_key,
                persist=True,
                mandatory=True,
                timeout=BROKER_PUBLISH_TIMEOUT,
                message_id=message.message_id,
                correlation_id=message.correlation_id,
                content_type=message.content_type,
                headers={**message.headers, HEADER_ATTEMPT: attempt + 1, HEADER_LAST_ERROR: error[:500]},
            )
            return

        log.info("Payment message processed")
