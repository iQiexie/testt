import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, PaymentStatusEnum
from app.db.repos.base.base import BaseRepo


class PaymentRepo(BaseRepo):
    def __init__(self, session: AsyncSession):
        super().__init__(session=session)

    async def maybe_create_payment(self, **kwargs) -> Payment | None:
        """INSERT ... ON CONFLICT (idempotency_key) DO NOTHING.

        None — платёж с таким ключом уже есть (в том числе вставлен параллельным запросом прямо
        сейчас: Postgres дождётся его коммита и только потом вернёт конфликт).
        """
        stmt = (
            insert(Payment)
            .values(**kwargs)
            .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
            .returning(Payment)
        )
        stmt = select(Payment).from_statement(stmt).execution_options(populate_existing=True)

        query = await self.session.execute(stmt)
        return query.scalar_one_or_none()

    async def get_payment_by_idempotency_key(self, idempotency_key: str) -> Payment:
        stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
        query = await self.session.execute(stmt)
        return query.scalar_one()

    async def maybe_get_payment(self, payment_id: uuid.UUID) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        query = await self.session.execute(stmt)
        return query.scalar_one_or_none()

    async def get_payment(self, payment_id: uuid.UUID) -> Payment:
        stmt = select(Payment).where(Payment.id == payment_id)
        query = await self.session.execute(stmt)
        return query.scalar_one()

    async def maybe_finish_pending_payment(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatusEnum,
        processed_at: datetime,
    ) -> Payment | None:
        """Переводит платёж из pending в финальный статус. None — его уже завершил кто-то другой.

        Условие на status в самом UPDATE: две параллельные доставки одного сообщения не перезапишут
        результат друг друга — победит первая, вторая получит None.
        """
        stmt = update(Payment).where(Payment.id == payment_id, Payment.status == PaymentStatusEnum.pending.value)
        stmt = stmt.values(status=status.value, processed_at=processed_at).returning(Payment)
        stmt = select(Payment).from_statement(stmt).execution_options(populate_existing=True)

        query = await self.session.execute(stmt)
        return query.scalar_one_or_none()

    async def update_payment(self, payment_id: uuid.UUID, **kwargs) -> Payment:
        return await self.update(Payment, Payment.id == payment_id, **kwargs)
