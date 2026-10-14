from fastapi import FastAPI

from app.api.middlewares.logs import LoggingMiddleware
from app.config.config import Config


def setup_middlewares(app: FastAPI, config: Config) -> FastAPI:
    if config.logs.LOGS_IS_ENABLED:
        app.add_middleware(LoggingMiddleware, config=config)

    return app
