import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from starlette import status

from app.api.dependencies.auth import auth_api_key
from app.api.dto.payment.request import CreatePaymentRequest
from app.api.dto.payment.response import PaymentCreatedResponse, PaymentResponse
from app.db.models import Payment
from app.services.payment import PaymentService

router = APIRouter(tags=["Payments"], dependencies=[Depends(auth_api_key)])


@router.post(
    path="/payments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreatedResponse,
)
async def create_payment(
    data: CreatePaymentRequest,
    response: Response,
    service: Annotated[PaymentService, Depends()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> Payment:
    """Принимает платёж в обработку. Результат придёт на webhook_url, статус — через GET.

    Повтор с тем же Idempotency-Key и тем же телом вернёт тот же платёж (заголовок
    `Idempotent-Replayed: true`); тот же ключ с другим телом — 422.
    """
    payment, created = await service.create_payment(data=data, idempotency_key=idempotency_key)

    if not created:
        response.headers["Idempotent-Replayed"] = "true"

    return payment


@router.get(
    path="/payments/{payment_id}",
    status_code=status.HTTP_200_OK,
    response_model=PaymentResponse,
)
async def get_payment(
    payment_id: uuid.UUID,
    service: Annotated[PaymentService, Depends()],
) -> Payment:
    return await service.get_payment(payment_id=payment_id)
