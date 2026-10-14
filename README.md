# Payments Service

Микросервис асинхронной обработки платежей. Принимает запрос на оплату, проводит его через
эмуляцию внешнего платёжного шлюза и уведомляет клиента о результате через webhook.

**Стек:** FastAPI + Pydantic v2, SQLAlchemy 2.0 (async, asyncpg), PostgreSQL, RabbitMQ (FastStream),
Alembic, Docker + docker-compose. Python 3.12.

---

## Быстрый старт

```bash
cp .env.example .env
docker compose up -d --build
```

Поднимутся четыре контейнера:

| Сервис | Что делает | Порт на хосте |
|---|---|---|
| `postgres` | PostgreSQL 18 | `5433` |
| `rabbitmq` | RabbitMQ 4.1 + management UI (`payments` / `payments`) | `5672`, `15672` |
| `api` | FastAPI: накатывает миграции, отдаёт API и отправляет события из outbox | `8000` |
| `consumer` | FastStream: обрабатывает очередь `payments.new` | — |

Порты меняются в `.env` (`API_PORT`, `POSTGRES_PORT`, `RABBITMQ_PORT`, `RABBITMQ_MANAGEMENT_PORT`).

- Swagger: http://localhost:8000/api/v1/docs (кнопка **Authorize** → `X-API-Key`)
- Health: http://localhost:8000/health (Postgres + RabbitMQ)
- RabbitMQ UI: http://localhost:15672

## Примеры

API-ключ — значение `AUTH_API_KEY` из `.env` (в примере `change-me`).

**Создание платежа**

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H 'X-API-Key: change-me' \
  -H 'Idempotency-Key: order-42' \
  -H 'Content-Type: application/json' \
  -d '{
        "amount": "1500.00",
        "currency": "RUB",
        "description": "Заказ #42",
        "metadata": {"order_id": 42},
        "webhook_url": "https://webhook.site/your-id"
      }'
```

```http
HTTP/1.1 202 Accepted

{"payment_id": "6efab372-ec15-4c36-bf7b-327cbee33c58", "status": "pending", "created_at": "2026-10-14T18:52:24.211796Z"}
```

**Получение платежа**

```bash
curl http://localhost:8000/api/v1/payments/6efab372-ec15-4c36-bf7b-327cbee33c58 -H 'X-API-Key: change-me'
```

```json
{
  "id": "6efab372-ec15-4c36-bf7b-327cbee33c58",
  "amount": "1500.00",
  "currency": "RUB",
  "description": "Заказ #42",
  "metadata": {"order_id": 42},
  "status": "succeeded",
  "idempotency_key": "order-42",
  "webhook_url": "https://webhook.site/your-id",
  "created_at": "2026-10-14T18:52:24.211796Z",
  "processed_at": "2026-10-14T18:52:26.773370Z"
}
```

**Webhook**, который получит клиент (POST на `webhook_url`, заголовки `X-Payment-Id` и `X-Event-Id`):

```json
{
  "payment_id": "6efab372-ec15-4c36-bf7b-327cbee33c58",
  "status": "succeeded",
  "amount": "1500.00",
  "currency": "RUB",
  "description": "Заказ #42",
  "metadata": {"order_id": 42},
  "created_at": "2026-10-14T18:52:24.211796Z",
  "processed_at": "2026-10-14T18:52:26.773370Z"
}
```

Webhook принимается только при ответе 2xx. Чтобы принять его локально, поднимите любой HTTP-сервер на
хосте и укажите `http://host.docker.internal:<порт>/...`: этот адрес consumer видит через `extra_hosts`.

**Ответы с ошибками**

| Ситуация | Код |
|---|---|
| нет или неверный `X-API-Key` | `401` |
| нет `Idempotency-Key`, невалидное тело (сумма ≤ 0, больше 2 знаков после запятой, валюта не из RUB/USD/EUR, кривой URL) | `422` |
| тот же `Idempotency-Key` с **другим** телом | `422` |
| платёж не найден | `404` |

Суммы передаются и возвращаются строкой (`"1500.00"`), чтобы не терять точность на float.

---

## Как это работает

```
POST /payments ─┐  одна транзакция
                ├─> payments (pending)
                └─> outbox (payments.new)
                            │ outbox relay (в процессе api): FOR UPDATE SKIP LOCKED + publisher confirms
                            v
        [payments] ──payments.new──> (payments.new) ──> consumer ── шлюз (2-5 сек, 90% успех)
                                       │    ^                    ├─> UPDATE status, processed_at
                                       │    │                    └─> POST webhook_url
                 ошибка, попытка < 3   │    │ TTL истёк
                                       v    │
        [payments.retry] ──> (payments.new.retry.2000ms) / (payments.new.retry.4000ms)

        3-я попытка упала: reject ──> [payments.dlx] ──> (payments.new.dlq)
```

### Outbox pattern

`POST /payments` в **одной транзакции** пишет платёж и событие в таблицу `outbox`. Ответ 202 значит,
что оба изменения закоммичены. Сообщение не потеряется, даже если RabbitMQ в этот момент лежит.

Outbox relay — фоновая задача в процессе `api` (`app/services/outbox.py`):

- раз в `OUTBOX_POLL_INTERVAL` берёт пачку неотправленных событий через `SELECT ... FOR UPDATE SKIP LOCKED`.
  Несколько воркеров или реплик API разбирают outbox параллельно и не отправляют одно событие дважды;
- публикует с `persist=True` и **publisher confirms** и только после подтверждения брокера ставит
  `published_at`;
- если брокер недоступен, событие остаётся в outbox (`attempts` и `last_error` обновляются) и уходит
  после восстановления связи. Это проверено: остановленный RabbitMQ → платёж принят → брокер поднят →
  webhook пришёл.

Гарантия at-least-once: при падении между подтверждением брокера и коммитом событие уйдёт повторно.
Поэтому consumer идемпотентен (см. ниже).

### Идемпотентность

- **API.** `Idempotency-Key` обязателен и уникален в БД. Вставка идёт через
  `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`, поэтому даже параллельные запросы с одним
  ключом создают ровно один платёж и одно событие. Повтор возвращает тот же платёж с `202` и заголовком
  `Idempotent-Replayed: true`. Вместе с платежом хранится sha256 тела запроса: тот же ключ с другим
  телом даёт `422`, а не молча старый платёж.
- **Consumer.** Повторная доставка сообщения безопасна:
  - платёж уже не `pending` — шлюз второй раз не вызывается;
  - финальный статус пишется через `UPDATE ... WHERE status = 'pending'`, поэтому две параллельные
    доставки не перезапишут результат друг друга;
  - после успешного webhook ставится `webhook_delivered_at`, и повторно он не шлётся.

### Retry и Dead Letter Queue

Ретраи сделаны средствами RabbitMQ, а не `sleep` внутри обработчика. Consumer не блокируется,
а ожидающие сообщения переживают его рестарт.

1. Обработка упала (webhook ответил не 2xx или по таймауту, недоступна БД и т.п.).
2. Если это попытка 1 или 2, consumer публикует копию сообщения в `payments.retry` с увеличенным
   заголовком `x-attempt` и текстом ошибки в `x-last-error`, а потом подтверждает оригинал.
3. Сообщение ждёт в очереди с `x-message-ttl`: **2 с после первой неудачи, 4 с после второй**
   (`CONSUMER_RETRY_BASE_DELAY * 2^(n-1)`). По истечении TTL оно через dead-letter возвращается
   в `payments.new`.
4. Третья попытка упала — `reject` без requeue. Очередь `payments.new` объявлена с
   `x-dead-letter-exchange=payments.dlx`, и RabbitMQ перекладывает сообщение в **`payments.new.dlq`**.
   Туда же сразу попадают «ядовитые» сообщения с невалидным телом.

На каждую задержку своя очередь: при per-message TTL в одной очереди короткая задержка застревала бы
за длинной. Задержка зашита в имя очереди, потому что TTL существующей очереди поменять нельзя.

Ретраится вся обработка, но благодаря идемпотентности повтор после упавшего webhook не проводит
платёж заново, а только переотправляет уведомление.

Отказ шлюза (10% платежей) — это не ошибка обработки, а бизнес-результат: платёж получает статус
`failed`, клиент получает webhook.

---

## Структура

Слои: route → service → repo, внешние клиенты собраны в `Adapters`.

```
app/
  api/routes/        тонкий транспорт: payments (X-API-Key), health, docs
  api/dto/           request/response модели
  services/          бизнес-логика и транзакции
    payment.py         создание (платёж + outbox) и получение
    outbox.py          outbox relay
    processing.py      обработка платежа consumer-ом
  db/models.py       таблицы payments и outbox
  db/repos/          только SQL
  db/migrations/     alembic
  broker/topology.py exchanges, очереди, retry и DLQ
  consumer/          FastStream-приложение и обработчик payments.new
  external/          эмулятор шлюза, webhook-клиент
  adapters/          сборка внешних клиентов (RabbitBroker, шлюз, webhook)
  main.py            FastAPI-приложение (+ outbox relay в lifespan)
tests/
  unit/              DTO, отпечаток запроса, топология
  integration/       API, consumer-логика, outbox на реальном Postgres
  e2e/               весь docker-стек: webhook, ретраи с задержками, DLQ, дубли
```

### Таблицы

**payments**: `id` (uuid), `amount` numeric(18,2), `currency`, `description`, `metadata` (jsonb),
`status` (`pending` / `succeeded` / `failed`), `idempotency_key` (unique), `request_hash`,
`webhook_url`, `webhook_delivered_at`, `created_at`, `updated_at`, `processed_at`.
На сумму, валюту и статус стоят CHECK-ограничения.

**outbox**: `id`, `event_type` (= routing key), `aggregate_id`, `payload` (jsonb), `created_at`,
`published_at`, `attempts`, `last_error`. Частичный индекс по неотправленным событиям.

Статусы и валюты хранятся строками (`VARCHAR`), а не нативным postgres `ENUM`.

---

## Тесты

```bash
poetry install                              # Python 3.12
docker compose up -d --build                # integration-тестам нужен postgres, e2e — весь стек
poetry run pytest                           # всё
poetry run pytest tests/unit                # без инфраструктуры
poetry run pytest tests/integration         # отдельная БД payments_test, создаётся сама
poetry run pytest tests/e2e                 # против запущенного стека, ~40 с
poetry run ruff check .
```

Integration-тесты работают в отдельной базе `payments_test`: данные запущенного стека не трогаются.
E2E-тесты поднимают webhook-приёмник на хосте и проверяют:

- доставку webhook;
- ретрай с задержкой ~2 с;
- три попытки с задержками ~2 с и ~4 с и попадание сообщения в DLQ;
- что параллельные дубли дают один платёж и один webhook.

Если стек не поднят, integration- и e2e-тесты пропускаются (skip).

## Локальная разработка без докера для приложения

```bash
cp .env.example .env
docker compose up -d postgres rabbitmq
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:get_app --factory --reload   # API + outbox relay
poetry run python -m app.consumer.main                   # consumer
```

Новая миграция: `alembic revision --autogenerate -m "..."`. Номера ревизий сквозные: `0001`, `0002`, …

## Конфигурация

Всё задаётся через `.env`, полный список с умолчаниями — в `.env.example`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `AUTH_API_KEY` | — | статический ключ для `X-API-Key` |
| `CONSUMER_MAX_ATTEMPTS` | `3` | попыток до DLQ |
| `CONSUMER_RETRY_BASE_DELAY` | `2.0` | база экспоненциальной задержки, сек |
| `CONSUMER_PREFETCH_COUNT` | `10` | сколько сообщений consumer обрабатывает параллельно |
| `OUTBOX_POLL_INTERVAL` | `0.5` | период опроса outbox, сек |
| `OUTBOX_BATCH_SIZE` | `100` | событий за проход relay |
| `GATEWAY_MIN_DELAY` / `GATEWAY_MAX_DELAY` | `2` / `5` | время ответа эмулятора шлюза, сек |
| `GATEWAY_SUCCESS_RATE` | `0.9` | доля успешных платежей |
| `WEBHOOK_TIMEOUT` | `10` | таймаут отправки webhook, сек |

`/health` и Swagger открыты без ключа: health нужен docker healthcheck-у, а в Swagger ключ вводится
через Authorize. Оба эндпоинта бизнес-ручками не являются.
