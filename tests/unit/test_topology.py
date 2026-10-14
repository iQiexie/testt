from app.broker.topology import PAYMENTS_EXCHANGE, PAYMENTS_NEW_ROUTING_KEY, retry_delay, retry_queue
from app.config.config import ConsumerConfig


def test_retry_delay_is_exponential():
    assert [retry_delay(attempt=n, base_delay=2.0) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]


def test_retry_queue_dead_letters_back_to_main_queue():
    config = ConsumerConfig(CONSUMER_RETRY_BASE_DELAY=2.0)

    first = retry_queue(attempt=1, config=config)
    second = retry_queue(attempt=2, config=config)

    assert first.name == "payments.new.retry.2000ms"
    assert second.name == "payments.new.retry.4000ms"
    assert first.arguments["x-message-ttl"] == 2000
    assert second.arguments["x-message-ttl"] == 4000
    assert first.arguments["x-dead-letter-exchange"] == PAYMENTS_EXCHANGE.name
    assert first.arguments["x-dead-letter-routing-key"] == PAYMENTS_NEW_ROUTING_KEY
