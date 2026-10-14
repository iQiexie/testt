from decimal import Decimal
from typing import Any

from pydantic import Field, HttpUrl

from app.api.dto.base import BaseRequest
from app.db.models import CurrencyEnum


class CreatePaymentRequest(BaseRequest):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2, examples=["1500.00"])
    currency: CurrencyEnum
    description: str = Field(min_length=1, max_length=1000, examples=["Заказ #42"])
    metadata: dict[str, Any] = Field(default_factory=dict, examples=[{"order_id": 42}])
    webhook_url: HttpUrl = Field(max_length=2048, examples=["https://example.com/webhooks/payments"])
