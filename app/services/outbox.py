import asyncio
import traceback
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.broker.topology import PAYMENTS_EXCHANGE
from app.config.constants import BROKER_PUBLISH_TIMEOUT, HEADER_ATTEMPT
from app.services.base.base import BaseService

logger = structlog.stdlib.get_logger()


class OutboxService(BaseService):
    def __init__(self, adapters: Adapters, session_factory: sessionmaker, session: AsyncSession = None):
        super().__init__(session_factory=session_factory, adapters=adapters, session=session)

        self.repo = self.repos.outbox

    async def publish_pending(self) -> int:
        """Отправляет в RabbitMQ одну пачку событий из outbox. Возвращает число отправленных.

        Исключение из правила «не держать транзакцию во время сетевого вызова»: строки outbox
        остаются под FOR UPDATE SKIP LOCKED, пока брокер не подтвердит приём (publisher confirms),
        иначе параллельный relay взял бы то же событие. Публикация с подтверждением — миллисекунды.

        Гарантия at-least-once: если упадём между подтверждением брокера и коммитом, событие уйдёт
        ещё раз — consumer к этому готов (идемпотентен по статусу платежа).
        """
        async with self.repo.transaction() as t:
            events = await self.repo.get_unpublished_events_for_update(
                limit=self.adapters.config.outbox.OUTBOX_BATCH_SIZE,
            )
            published_ids = []

            for event in events:
                try:
                    await self.adapters.broker.publish(
                        event.payload,
                        exchange=PAYMENTS_EXCHANGE,
                        routing_key=event.event_type,
                        persist=True,
                        mandatory=True,
                        timeout=BROKER_PUBLISH_TIMEOUT,
                        message_id=str(event.id),
                        correlation_id=str(event.aggregate_id),
                        headers={HEADER_ATTEMPT: 1},
                    )
                except Exception as e:
                    # Порядок важен меньше, чем прогресс, но при недоступном брокере остальные
                    # тоже не уйдут — прерываем пачку, событие останется в outbox до следующего цикла
                    logger.warning(
                        "Outbox publish failed",
                        outbox_event_id=event.id,
                        exception=traceback.format_exception(e),
                    )
                    await self.repo.mark_event_failed(event_id=event.id, error=f"{type(e).__name__}: {e}")
                    break

                published_ids.append(event.id)

            if published_ids:
                await self.repo.mark_events_published(
                    event_ids=published_ids,
                    published_at=datetime.now(tz=timezone.utc),
                )

            await t.commit()

        if published_ids:
            logger.info("Outbox events published", count=len(published_ids))

        return len(published_ids)


class OutboxRelay:
    """Фоновый цикл: пока в outbox есть события — отправляет пачками, иначе спит poll interval."""

    def __init__(self, adapters: Adapters, session_factory: sessionmaker):
        self.adapters = adapters
        self.session_factory = session_factory

    async def run(self) -> None:
        logger.info("Outbox relay started")
        interval = self.adapters.config.outbox.OUTBOX_POLL_INTERVAL

        while True:
            try:
                service = OutboxService(adapters=self.adapters, session_factory=self.session_factory)
                published = await service.publish_pending()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Outbox relay iteration failed", exception=traceback.format_exception(e))
                published = 0

            if published < self.adapters.config.outbox.OUTBOX_BATCH_SIZE:
                await asyncio.sleep(interval)
