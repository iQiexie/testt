import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.api.dto.base import BaseResponse
from app.db.models import CurrencyEnum, PaymentStatusEnum


class PaymentCreatedResponse(BaseResponse):
    payment_id: uuid.UUID = Field(validation_alias="id")
    status: PaymentStatusEnum
    created_at: datetime


class PaymentResponse(BaseResponse):
    id: uuid.UUID
    amount: Decimal
    currency: CurrencyEnum
    description: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    status: PaymentStatusEnum
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
