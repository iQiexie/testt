from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.dto.payment.request import CreatePaymentRequest
from app.services.payment import request_fingerprint

VALID = {
    "amount": "100.50",
    "currency": "RUB",
    "description": "Заказ",
    "metadata": {"order_id": 1},
    "webhook_url": "https://example.com/hook",
}


def test_valid_request():
    data = CreatePaymentRequest(**VALID)
    assert data.amount == Decimal("100.50")
    assert data.metadata == {"order_id": 1}


def test_metadata_is_optional():
    payload = {key: value for key, value in VALID.items() if key != "metadata"}
    assert CreatePaymentRequest(**payload).metadata == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0"),
        ("amount", "-1"),
        ("amount", "1.001"),
        ("currency", "GBP"),
        ("description", ""),
        ("webhook_url", "not-a-url"),
        ("metadata", "string"),
    ],
)
def test_invalid_request(field, value):
    with pytest.raises(ValidationError):
        CreatePaymentRequest(**{**VALID, field: value})


def test_fingerprint_ignores_amount_notation_and_key_order():
    a = CreatePaymentRequest(**{**VALID, "amount": "100.5", "metadata": {"a": 1, "b": 2}})
    b = CreatePaymentRequest(**{**VALID, "amount": "100.50", "metadata": {"b": 2, "a": 1}})
    assert request_fingerprint(data=a) == request_fingerprint(data=b)


def test_fingerprint_differs_for_different_body():
    a = CreatePaymentRequest(**VALID)
    b = CreatePaymentRequest(**{**VALID, "description": "Другой заказ"})
    assert request_fingerprint(data=a) != request_fingerprint(data=b)
