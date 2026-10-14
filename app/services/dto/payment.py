import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field

from app.db.models import CurrencyEnum, PaymentStatusEnum
from app.init.base_models import BaseModel


class PaymentNewEvent(BaseModel):
    """Тело сообщения в очереди payments.new. Только id: актуальное состояние consumer читает из БД."""

    payment_id: uuid.UUID


class PaymentWebhook(BaseModel):
    """Тело webhook-уведомления клиенту о результате обработки."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: uuid.UUID = Field(validation_alias="id")
    status: PaymentStatusEnum
    amount: Decimal
    currency: CurrencyEnum
    description: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    processed_at: datetime | None
