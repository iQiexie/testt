"""Сквозные тесты против запущенного `docker compose up`: API -> outbox -> RabbitMQ -> consumer -> webhook.

Webhook-приёмник поднимается прямо в тесте на хосте; consumer достаёт до него через
host.docker.internal (extra_hosts в docker-compose.yml).
"""

import json
import os
import threading
import time
import uuid
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config.config import get_config

pytestmark = pytest.mark.e2e

API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
WEBHOOK_HOST = os.environ.get("E2E_WEBHOOK_HOST", "host.docker.internal")
RABBITMQ_MANAGEMENT_URL = os.environ.get("E2E_RABBITMQ_MANAGEMENT_URL", "http://localhost:15672")

# Шлюз отвечает за 2-5 сек, ретраи ждут 2 + 4 сек — с запасом
PROCESSING_TIMEOUT = 30


class WebhookReceiver:
    """Принимает webhook-и; `?fail=N` в URL — первые N запросов на этот путь получат HTTP 500."""

    def __init__(self):
        self.calls: dict[str, list[tuple[float, dict]]] = defaultdict(list)
        self.lock = threading.Lock()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                url = urlparse(self.path)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fail = int(parse_qs(url.query).get("fail", ["0"])[0])

                with receiver.lock:
                    receiver.calls[url.path].append((time.monotonic(), body))
                    attempt = len(receiver.calls[url.path])

                self.send_response(500 if attempt <= fail else 200)
                self.end_headers()

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str, fail: int = 0) -> str:
        return f"http://{WEBHOOK_HOST}:{self.port}{path}?fail={fail}"

    def wait_calls(self, path: str, count: int, timeout: float = PROCESSING_TIMEOUT) -> list[tuple[float, dict]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if len(self.calls[path]) >= count:
                    return list(self.calls[path])
            time.sleep(0.2)
        raise AssertionError(f"Expected {count} webhook calls on {path}, got {len(self.calls[path])}")


@pytest.fixture(scope="module")
def config():
    return get_config()


@pytest.fixture(scope="module")
def api(config):
    client = httpx.Client(base_url=API_URL, headers={"X-API-Key": config.auth.AUTH_API_KEY}, timeout=10)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError as e:
        pytest.skip(f"Стек не запущен ({e}): docker compose up -d --build")
    yield client
    client.close()


@pytest.fixture(scope="module")
def receiver():
    receiver = WebhookReceiver()
    yield receiver
    receiver.server.shutdown()


@pytest.fixture(scope="module")
def rabbit(config):
    return httpx.Client(
        base_url=RABBITMQ_MANAGEMENT_URL,
        auth=(config.rabbit.RABBITMQ_USER, config.rabbit.RABBITMQ_PASSWORD),
        timeout=10,
    )


def create_payment(api, webhook_url: str, key: str | None = None) -> dict:
    response = api.post(
        "/api/v1/payments",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
        json={
            "amount": "250.00",
            "currency": "EUR",
            "description": "e2e",
            "metadata": {"test": True},
            "webhook_url": webhook_url,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def dlq_payment_ids(rabbit) -> list[str]:
    response = rabbit.post(
        "/api/queues/%2F/payments.new.dlq/get",
        json={"count": 1000, "ackmode": "ack_requeue_true", "encoding": "auto"},
    )
    response.raise_for_status()
    return [json.loads(message["payload"])["payment_id"] for message in response.json()]


def test_payment_is_processed_and_webhook_delivered(api, receiver):
    path = f"/ok/{uuid.uuid4()}"
    created = create_payment(api, webhook_url=receiver.url(path))

    [(_, webhook)] = receiver.wait_calls(path, count=1)

    assert webhook["payment_id"] == created["payment_id"]
    assert webhook["status"] in {"succeeded", "failed"}
    assert webhook["amount"] == "250.00"
    assert webhook["metadata"] == {"test": True}

    payment = api.get(f"/api/v1/payments/{created['payment_id']}").json()
    assert payment["status"] == webhook["status"]
    assert payment["processed_at"] is not None

    # Ни ретраев, ни дублей
    time.sleep(3)
    assert len(receiver.calls[path]) == 1


def test_webhook_retried_with_exponential_backoff(api, receiver, rabbit):
    path = f"/flaky/{uuid.uuid4()}"
    created = create_payment(api, webhook_url=receiver.url(path, fail=1))

    calls = receiver.wait_calls(path, count=2)

    assert [body["payment_id"] for _, body in calls] == [created["payment_id"]] * 2
    assert 1.5 <= calls[1][0] - calls[0][0] < 4
    assert created["payment_id"] not in dlq_payment_ids(rabbit)


def test_message_goes_to_dlq_after_three_attempts(api, receiver, rabbit):
    path = f"/broken/{uuid.uuid4()}"
    created = create_payment(api, webhook_url=receiver.url(path, fail=100))

    calls = receiver.wait_calls(path, count=3)
    first, second, third = (moment for moment, _ in calls)

    # Задержки 2s и 4s (TTL очередей ожидания) плюс накладные расходы
    assert 1.5 <= second - first < 4
    assert 3.5 <= third - second < 6.5

    deadline = time.monotonic() + 10
    while created["payment_id"] not in dlq_payment_ids(rabbit):
        assert time.monotonic() < deadline, "message did not reach DLQ"
        time.sleep(0.5)

    # Четвёртой попытки нет
    time.sleep(5)
    assert len(receiver.calls[path]) == 3

    # Сам платёж при этом проведён: ретраились только уведомления
    payment = api.get(f"/api/v1/payments/{created['payment_id']}").json()
    assert payment["status"] in {"succeeded", "failed"}


def test_concurrent_duplicates_produce_one_payment_and_one_webhook(api, receiver):
    path = f"/dup/{uuid.uuid4()}"
    key = str(uuid.uuid4())
    results = []

    def send():
        results.append(create_payment(api, webhook_url=receiver.url(path), key=key))

    threads = [threading.Thread(target=send) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({result["payment_id"] for result in results}) == 1

    receiver.wait_calls(path, count=1)
    time.sleep(3)
    assert len(receiver.calls[path]) == 1
