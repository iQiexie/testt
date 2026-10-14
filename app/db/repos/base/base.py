import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Type, TypeVar

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.constants import POSTGRES_TIMEOUT
from app.db.models import Base

logger = structlog.stdlib.get_logger()
Model = TypeVar("Model", Base, Base)


class BaseRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def transaction(self, timeout: int | None = None) -> AsyncContextManager[AsyncSession]:
        @asynccontextmanager
        async def wrapped() -> AsyncContextManager[AsyncSession]:
            async with self.session as session:
                try:
                    async with asyncio.timeout(timeout or POSTGRES_TIMEOUT):
                        yield session
                except Exception as ex:
                    await session.rollback()
                    logger.info(f"Transaction exception: {ex=}, {type(ex)=}")
                    raise ex
                finally:
                    await session.close()

        return wrapped()

    async def update(self, model: Type[Model], *args: Any, **kwargs: Any) -> Model:
        stmt = update(model).where(*args).values(**kwargs).returning(model)
        # populate_existing=True is required: without it the RETURNING row does NOT refresh an
        # instance already present in the identity map, so the returned object keeps its stale
        # pre-update attributes while the DB row is updated.
        stmt = (
            select(model).from_statement(stmt).execution_options(synchronize_session="fetch", populate_existing=True)
        )

        query = await self.session.execute(stmt)
        return query.scalar_one()
