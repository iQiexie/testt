import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import APIKeyHeader
from starlette import status

from app.adapters.base import Adapters
from app.api.dependencies.stubs import dependency_adapters
from app.api.exceptions import ClientError

# auto_error=False: на отсутствующий ключ отвечаем тем же 401, что и на неверный
ApiKeyHeader = APIKeyHeader(name="X-API-Key", scheme_name="ApiKey", auto_error=False)


def auth_api_key(
    adapters: Annotated[Adapters, Depends(dependency_adapters)],
    api_key: Annotated[str | None, Depends(ApiKeyHeader)],
) -> None:
    if not api_key or not secrets.compare_digest(api_key, adapters.config.auth.AUTH_API_KEY):
        raise ClientError(status_code=status.HTTP_401_UNAUTHORIZED, message="Invalid API key")
