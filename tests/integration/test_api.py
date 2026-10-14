import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import OutboxEvent, Payment
from app.main import get_app

pytestmark = pytest.mark.integration

BODY = {
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Заказ #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://example.com/webhook",
}


@pytest.fixture
async def client(config):
    # ASGITransport не запускает lifespan — outbox relay в этих тестах не работает, события остаются в БД
    transport = httpx.ASGITransport(app=get_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": config.auth.AUTH_API_KEY},
    ) as client:
        yield client


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        query = await session.execute(select(func.count()).select_from(model))
        return query.scalar_one()


async def test_create_payment(client, session_factory):
    response = await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-1"})

    assert response.status_code == 202
    data = response.json()
    assert set(data) == {"payment_id", "status", "created_at"}
    assert data["status"] == "pending"
    assert "idempotent-replayed" not in response.headers

    # Платёж и событие — в одной транзакции
    async with session_factory() as session:
        payment = (await session.execute(select(Payment))).scalar_one()
        event = (await session.execute(select(OutboxEvent))).scalar_one()

    assert str(payment.id) == data["payment_id"]
    assert event.event_type == "payments.new"
    assert event.aggregate_id == payment.id
    assert event.payload == {"payment_id": data["payment_id"]}
    assert event.published_at is None


async def test_get_payment(client):
    created = (await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-1"})).json()

    response = await client.get(f"/api/v1/payments/{created['payment_id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == created["payment_id"]
    assert data["amount"] == "1500.00"
    assert data["currency"] == "RUB"
    assert data["description"] == BODY["description"]
    assert data["metadata"] == BODY["metadata"]
    assert data["status"] == "pending"
    assert data["idempotency_key"] == "key-1"
    assert data["webhook_url"] == BODY["webhook_url"]
    assert data["created_at"] == created["created_at"]
    assert data["processed_at"] is None


async def test_get_unknown_payment(client):
    response = await client.get(f"/api/v1/payments/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_invalid_payment_id(client):
    response = await client.get("/api/v1/payments/not-a-uuid")
    assert response.status_code == 422


async def test_idempotent_replay(client, session_factory):
    first = await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-1"})
    second = await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-1"})

    assert second.status_code == 202
    assert second.json() == first.json()
    assert second.headers["idempotent-replayed"] == "true"
    assert await count(session_factory, Payment) == 1
    assert await count(session_factory, OutboxEvent) == 1


async def test_same_key_different_body(client, session_factory):
    await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-1"})
    response = await client.post(
        "/api/v1/payments",
        json={**BODY, "amount": "1.00"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 422
    assert await count(session_factory, Payment) == 1


async def test_concurrent_requests_with_same_key(client, session_factory):
    responses = await asyncio.gather(
        *[client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "race"}) for _ in range(10)]
    )

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["payment_id"] for r in responses}) == 1
    assert await count(session_factory, Payment) == 1
    assert await count(session_factory, OutboxEvent) == 1


async def test_different_keys_create_different_payments(client, session_factory):
    a = await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-a"})
    b = await client.post("/api/v1/payments", json=BODY, headers={"Idempotency-Key": "key-b"})

    assert a.json()["payment_id"] != b.json()["payment_id"]
    assert await count(session_factory, OutboxEvent) == 2


async def test_idempotency_key_is_required(client):
    response = await client.post("/api/v1/payments", json=BODY)
    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
@pytest.mark.parametrize("method", ["post", "get"])
async def test_api_key_is_required(client, headers, method):
    client.headers.pop("X-API-Key")
    url = "/api/v1/payments" if method == "post" else f"/api/v1/payments/{uuid.uuid4()}"
    kwargs = {"json": BODY} if method == "post" else {}

    response = await getattr(client, method)(url, headers={"Idempotency-Key": "key-1", **headers}, **kwargs)

    assert response.status_code == 401


async def test_invalid_body(client):
    response = await client.post(
        "/api/v1/payments",
        json={**BODY, "currency": "GBP"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422
