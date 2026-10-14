import datetime
import uuid
from decimal import Decimal
from enum import Enum
from typing import Any, Dict

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, Integer, Numeric, String, Text, func, inspect
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CurrencyEnum(str, Enum):
    rub = "RUB"
    usd = "USD"
    eur = "EUR"


class PaymentStatusEnum(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class OutboxEventTypeEnum(str, Enum):
    # Значение совпадает с routing key и именем очереди в RabbitMQ
    payment_new = "payments.new"


class Base(DeclarativeBase):
    def object_as_dict(self) -> Dict[str, Any]:
        return {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}  # noqa


class _TimestampMixin(Base):
    __abstract__ = True

    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Payment(_TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_payments_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(String(1000))
    # `metadata` занято у DeclarativeBase, поэтому атрибут с подчёркиванием, колонка — как в ТЗ
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), server_default=PaymentStatusEnum.pending.value)

    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    # sha256 тела запроса: тот же ключ с другим телом — ошибка клиента, а не повтор
    request_hash: Mapped[str] = mapped_column(String(64))

    webhook_url: Mapped[str] = mapped_column(String(2048))
    # Проставляется после успешного webhook: повторная доставка сообщения не шлёт его второй раз
    webhook_delivered_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    processed_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class OutboxEvent(Base):
    """Transactional outbox: событие пишется в одной транзакции с платежом, в брокер его отправляет relay."""

    __tablename__ = "outbox"
    __table_args__ = (
        # relay ищет только неотправленные — частичный индекс остаётся маленьким
        Index("ix_outbox_unpublished", "id", postgresql_where="published_at IS NULL"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB)

    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    published_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
