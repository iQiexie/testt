import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.db.models import Payment, PaymentStatusEnum
from app.services.base.base import BaseService
from app.services.dto.payment import PaymentWebhook

logger = structlog.stdlib.get_logger()


class PaymentProcessingService(BaseService):
    """Логика consumer-а payments.new: провести платёж через шлюз и уведомить клиента."""

    def __init__(self, adapters: Adapters, session_factory: sessionmaker, session: AsyncSession = None):
        super().__init__(session_factory=session_factory, adapters=adapters, session=session)

        self.repo = self.repos.payment

    async def process(self, payment_id: uuid.UUID) -> Payment:
        """Идемпотентно: сообщение может прийти повторно (ретрай, дубль из outbox, редоставка).

        - платёж ещё pending — проводим через шлюз и фиксируем результат;
        - уже в финальном статусе — шлюз второй раз не дёргаем;
        - webhook уже доставлен — второй раз не шлём.

        Любое исключение (webhook не принят, БД недоступна) уходит наверх — ретраи решает consumer.
        """
        payment = await self._get_payment(payment_id=payment_id)

        if payment.status == PaymentStatusEnum.pending.value:
            payment = await self._charge(payment=payment)

        if payment.webhook_delivered_at is None:
            payment = await self._notify(payment=payment)

        return payment

    async def _charge(self, payment: Payment) -> Payment:
        # Вызов шлюза — вне транзакции: 2-5 секунд держать соединение с БД незачем
        succeeded = await self.adapters.gateway.charge(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
        )
        status = PaymentStatusEnum.succeeded if succeeded else PaymentStatusEnum.failed

        async with self.repo.transaction() as t:
            finished = await self.repo.maybe_finish_pending_payment(
                payment_id=payment.id,
                status=status,
                processed_at=datetime.now(tz=timezone.utc),
            )

            if finished is None:
                # Параллельная доставка того же сообщения успела раньше — её результат и считаем верным
                logger.warning("Payment already finished concurrently", payment_id=str(payment.id))
                finished = await self.repo.get_payment(payment_id=payment.id)

            await t.commit()

        logger.info("Payment processed", payment_id=str(finished.id), status=finished.status)
        return finished

    async def _notify(self, payment: Payment) -> Payment:
        payload = PaymentWebhook.model_validate(payment).model_dump(mode="json")
        await self.adapters.webhook.send(url=payment.webhook_url, payload=payload, payment_id=payment.id)

        async with self.repo.transaction() as t:
            payment = await self.repo.update_payment(
                payment_id=payment.id,
                webhook_delivered_at=datetime.now(tz=timezone.utc),
            )
            await t.commit()

        return payment

    @BaseService.single_transaction
    async def _get_payment(self, payment_id: uuid.UUID) -> Payment:
        return await self.repo.get_payment(payment_id=payment_id)
