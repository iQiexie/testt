from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters

if TYPE_CHECKING:
    from app.services.outbox import OutboxService
    from app.services.payment import PaymentService
    from app.services.processing import PaymentProcessingService


class Services:
    def __init__(
        self,
        session_factory: sessionmaker,
        adapters: Adapters,
        session: AsyncSession | None = None,
    ):
        self._session = session
        self.adapters = adapters
        self.session_factory = session_factory

    @property
    def session(self) -> AsyncSession:
        if self._session:
            return self._session

        self._session = self.session_factory()
        return self._session

    @property
    def payment(self) -> "PaymentService":
        from app.services.payment import PaymentService

        return PaymentService(session_factory=self.session_factory, adapters=self.adapters, session=self.session)

    @property
    def outbox(self) -> "OutboxService":
        from app.services.outbox import OutboxService

        return OutboxService(session_factory=self.session_factory, adapters=self.adapters, session=self.session)

    @property
    def processing(self) -> "PaymentProcessingService":
        from app.services.processing import PaymentProcessingService

        return PaymentProcessingService(
            session_factory=self.session_factory,
            adapters=self.adapters,
            session=self.session,
        )
