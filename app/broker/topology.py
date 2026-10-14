"""Топология RabbitMQ. Объявляется и API (перед публикацией из outbox), и consumer-ом — декларации идемпотентны.

outbox relay ──> [payments] ──payments.new──> (payments.new) ──> consumer
                                                 │   ^
                   ошибка, попытки ещё есть      │   │ TTL истёк -> dead-letter обратно в [payments]
                                                 v   │
               [payments.retry] ──> (payments.new.retry.2000ms) / (payments.new.retry.4000ms)

попытки кончились: reject ──> (payments.new) dead-letter ──> [payments.dlx] ──> (payments.new.dlq)
"""

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config.config import ConsumerConfig
from app.db.models import OutboxEventTypeEnum

PAYMENTS_NEW_ROUTING_KEY = OutboxEventTypeEnum.payment_new.value
PAYMENTS_DLQ_ROUTING_KEY = f"{PAYMENTS_NEW_ROUTING_KEY}.dlq"

PAYMENTS_EXCHANGE = RabbitExchange("payments", type=ExchangeType.DIRECT, durable=True)
RETRY_EXCHANGE = RabbitExchange("payments.retry", type=ExchangeType.DIRECT, durable=True)
DEAD_LETTER_EXCHANGE = RabbitExchange("payments.dlx", type=ExchangeType.DIRECT, durable=True)

PAYMENTS_NEW_QUEUE = RabbitQueue(
    PAYMENTS_NEW_ROUTING_KEY,
    durable=True,
    routing_key=PAYMENTS_NEW_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE.name,
        "x-dead-letter-routing-key": PAYMENTS_DLQ_ROUTING_KEY,
    },
)

PAYMENTS_DLQ = RabbitQueue(PAYMENTS_DLQ_ROUTING_KEY, durable=True, routing_key=PAYMENTS_DLQ_ROUTING_KEY)


def retry_delay(attempt: int, base_delay: float) -> float:
    """Задержка перед следующей попыткой после неудачной попытки номер `attempt` (1-based)."""
    return base_delay * 2 ** (attempt - 1)


def retry_queue(attempt: int, config: ConsumerConfig) -> RabbitQueue:
    """Очередь ожидания после неудачной попытки `attempt`.

    Своя очередь на каждую задержку, а не per-message TTL в одной: RabbitMQ выбрасывает
    просроченные сообщения только с головы очереди, и короткая задержка застряла бы за длинной.
    Задержка — в имени очереди: x-message-ttl нельзя поменять у существующей очереди, а так
    новая настройка просто создаёт новую очередь.
    """
    delay_ms = int(retry_delay(attempt=attempt, base_delay=config.CONSUMER_RETRY_BASE_DELAY) * 1000)
    name = f"{PAYMENTS_NEW_ROUTING_KEY}.retry.{delay_ms}ms"

    return RabbitQueue(
        name,
        durable=True,
        routing_key=name,
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE.name,
            "x-dead-letter-routing-key": PAYMENTS_NEW_ROUTING_KEY,
        },
    )


async def declare_topology(broker: RabbitBroker, config: ConsumerConfig) -> None:
    payments_exchange = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    retry_exchange = await broker.declare_exchange(RETRY_EXCHANGE)
    dead_letter_exchange = await broker.declare_exchange(DEAD_LETTER_EXCHANGE)

    queue = await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    await queue.bind(exchange=payments_exchange, routing_key=PAYMENTS_NEW_ROUTING_KEY)

    dlq = await broker.declare_queue(PAYMENTS_DLQ)
    await dlq.bind(exchange=dead_letter_exchange, routing_key=PAYMENTS_DLQ_ROUTING_KEY)

    for attempt in range(1, config.CONSUMER_MAX_ATTEMPTS):
        retry = retry_queue(attempt=attempt, config=config)
        declared = await broker.declare_queue(retry)
        await declared.bind(exchange=retry_exchange, routing_key=retry.routing_key)
