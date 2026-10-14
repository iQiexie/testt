from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent
from app.db.repos.base.base import BaseRepo


class OutboxRepo(BaseRepo):
    def __init__(self, session: AsyncSession):
        super().__init__(session=session)

    async def create_event(self, **kwargs) -> OutboxEvent:
        model = OutboxEvent(**kwargs)
        self.session.add(model)
        return model

    async def get_unpublished_events_for_update(self, limit: int) -> list[OutboxEvent]:
        """Пачка неотправленных событий под блокировкой.

        SKIP LOCKED: несколько relay (воркеры API, реплики) разбирают outbox параллельно и не
        берут одно и то же событие дважды, а не стоят в очереди друг за другом.
        """
        stmt = select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id)
        stmt = stmt.limit(limit).with_for_update(skip_locked=True)

        query = await self.session.execute(stmt)
        return list(query.scalars().all())

    async def mark_events_published(self, event_ids: list[int], published_at: datetime) -> None:
        stmt = update(OutboxEvent).where(OutboxEvent.id.in_(event_ids)).values(published_at=published_at)
        stmt = stmt.values(attempts=OutboxEvent.attempts + 1)
        await self.session.execute(stmt)

    async def mark_event_failed(self, event_id: int, error: str) -> None:
        stmt = update(OutboxEvent).where(OutboxEvent.id == event_id)
        stmt = stmt.values(attempts=OutboxEvent.attempts + 1, last_error=error)
        await self.session.execute(stmt)
