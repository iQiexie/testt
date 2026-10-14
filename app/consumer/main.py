import asyncio

from faststream import FastStream

from app.adapters.base import Adapters
from app.broker.topology import declare_topology
from app.config.config import get_config
from app.consumer.handlers import register_handlers
from app.init.db import get_session_factory
from app.init.logs import setup_logs


def get_app() -> FastStream:
    config = get_config()
    setup_logs(config=config.logs)

    session_factory, engine = get_session_factory(config=config.postgres)
    adapters = Adapters(config=config)
    broker = adapters.broker

    register_handlers(broker=broker, adapters=adapters, session_factory=session_factory)
    app = FastStream(broker)

    @app.on_startup
    async def declare() -> None:
        # Очереди ожидания и DLQ без подписчиков — FastStream сам их не объявит
        await broker.connect()
        await declare_topology(broker=broker, config=config.consumer)

    @app.after_shutdown
    async def dispose_engine() -> None:
        await engine.dispose()

    return app


if __name__ == "__main__":
    asyncio.run(get_app().run())
