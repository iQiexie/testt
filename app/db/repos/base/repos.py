from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.outbox import OutboxRepo
from app.db.repos.payment import PaymentRepo


class Repos:
    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def payment(self) -> PaymentRepo:
        return PaymentRepo(session=self.session)

    @property
    def outbox(self) -> OutboxRepo:
        return OutboxRepo(session=self.session)
