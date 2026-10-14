from typing import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.db.repos.base.repos import Repos
from app.services.base.services import Services

logger = structlog.stdlib.get_logger()


class BaseService:
    def __init__(self, adapters: Adapters, session_factory: sessionmaker, session: AsyncSession = None):
        if session:
            self.session = session
        else:
            self.session = session_factory()

        self.adapters = adapters
        self.repos = Repos(session=self.session)
        self.services = Services(session=self.session, adapters=self.adapters, session_factory=session_factory)
        self.session_factory = session_factory

    @staticmethod
    def single_transaction(f: Callable) -> Callable:
        async def wrapper(*args, **kwargs):  # noqa: ANN202
            async with args[0].repo.transaction() as t:
                result = await f(*args, **kwargs)
                await t.commit()

            return result

        return wrapper
