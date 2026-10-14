from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from starlette import status
from starlette.responses import JSONResponse

from app.adapters.base import Adapters
from app.api.dependencies.stubs import dependency_adapters, dependency_session_factory

router = APIRouter(tags=["Health"])


@router.get(path="/health")
async def health(
    adapters: Annotated[Adapters, Depends(dependency_adapters)],
    session_factory: Annotated[sessionmaker, Depends(dependency_session_factory)],
) -> JSONResponse:
    """Readiness probe для docker healthcheck: отвечают ли Postgres и RabbitMQ. Без API-ключа."""
    db_ok = True
    db_error: str | None = None

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)

    rabbit_ok = await adapters.broker.ping(timeout=2)

    payload = {
        "status": "ok" if db_ok and rabbit_ok else "degraded",
        "db": "ok" if db_ok else f"error: {db_error}",
        "rabbitmq": "ok" if rabbit_ok else "error: no connection",
    }
    code = status.HTTP_200_OK if db_ok and rabbit_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(content=payload, status_code=code)
