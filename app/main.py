import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from app.adapters.base import Adapters
from app.api.dependencies.base import setup_dependencies
from app.broker.topology import declare_topology
from app.config.config import get_config
from app.init.db import get_session_factory
from app.init.exceptions import setup_exceptions
from app.init.logs import setup_logs
from app.init.middlewares import setup_middlewares
from app.init.openapi import setup_openapi
from app.init.routes import setup_routes
from app.services.outbox import OutboxRelay


def get_app() -> FastAPI:
    config = get_config()
    setup_logs(config=config.logs)

    session_factory, engine = get_session_factory(config=config.postgres)
    adapters = Adapters(config=config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Outbox relay живёт в процессе API: события рождаются здесь же. Несколько воркеров/реплик
        # безопасны — строки outbox разбираются через FOR UPDATE SKIP LOCKED.
        await adapters.broker.connect()
        await declare_topology(broker=adapters.broker, config=config.consumer)
        relay_task = asyncio.create_task(OutboxRelay(adapters=adapters, session_factory=session_factory).run())

        yield

        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task
        await adapters.broker.stop()
        await engine.dispose()

    fastapi = FastAPI(
        title="Payments Service",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    fastapi = setup_routes(app=fastapi)
    fastapi = setup_dependencies(app=fastapi, session_factory=session_factory, adapters=adapters)
    fastapi = setup_exceptions(app=fastapi)
    fastapi = setup_openapi(app=fastapi)
    fastapi = setup_middlewares(app=fastapi, config=config)
    return fastapi


if __name__ == "__main__":
    uvicorn.run(
        "app.main:get_app",
        reload=False,
        port=8000,
        factory=True,
    )
