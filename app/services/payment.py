import hashlib
import json
import uuid
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from starlette import status

from app.adapters.base import Adapters
from app.api.dependencies.stubs import dependency_adapters, dependency_session_factory, placeholder
from app.api.dto.payment.request import CreatePaymentRequest
from app.api.exceptions import ClientError
from app.db.models import OutboxEventTypeEnum, Payment
from app.services.base.base import BaseService
from app.services.dto.payment import PaymentNewEvent

logger = structlog.stdlib.get_logger()


def request_fingerprint(data: CreatePaymentRequest) -> str:
    """sha256 канонического JSON тела: порядок ключей и запись суммы (100 / 100.0 / 100.00) не важны."""
    payload = data.model_dump(mode="json")
    payload["amount"] = str(data.amount.quantize(Decimal("0.01")))
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class PaymentService(BaseService):
    def __init__(
        self,
        adapters: Annotated[Adapters, Depends(dependency_adapters)],
        session_factory: Annotated[sessionmaker, Depends(dependency_session_factory)],
        session: Annotated[AsyncSession, Depends(placeholder)] = None,
    ):
        super().__init__(session_factory=session_factory, adapters=adapters, session=session)

        self.repo = self.repos.payment

    @BaseService.single_transaction
    async def create_payment(self, data: CreatePaymentRequest, idempotency_key: str) -> tuple[Payment, bool]:
        """Создаёт платёж и событие payments.new в outbox одной транзакцией.

        Возвращает (платёж, создан ли он сейчас). Повтор с тем же Idempotency-Key и тем же телом
        отдаёт уже существующий платёж и не порождает второго события; с другим телом — 422.
        """
        request_hash = request_fingerprint(data=data)

        payment = await self.repo.maybe_create_payment(
            id=uuid.uuid4(),
            amount=data.amount,
            currency=data.currency.value,
            description=data.description,
            metadata_=data.metadata,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            webhook_url=str(data.webhook_url),
        )

        if payment is None:
            payment = await self.repo.get_payment_by_idempotency_key(idempotency_key=idempotency_key)

            if payment.request_hash != request_hash:
                raise ClientError(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    message="Idempotency-Key was already used with a different request body",
                )

            logger.info("Idempotent replay", payment_id=str(payment.id))
            return payment, False

        event = PaymentNewEvent(payment_id=payment.id)
        await self.repos.outbox.create_event(
            event_type=OutboxEventTypeEnum.payment_new.value,
            aggregate_id=payment.id,
            payload=event.model_dump(mode="json"),
        )

        logger.info("Payment created", payment_id=str(payment.id))
        return payment, True

    @BaseService.single_transaction
    async def get_payment(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.repo.maybe_get_payment(payment_id=payment_id)

        if payment is None:
            raise ClientError(status_code=status.HTTP_404_NOT_FOUND, message="Not found")

        return payment
