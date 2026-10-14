from typing import Any

from starlette import status


class ClientError(Exception):
    def __init__(
        self,
        status_code: int | None = status.HTTP_400_BAD_REQUEST,
        message: str = "",
        raw_kwargs: dict[str, Any] = None,
        **kwargs,
    ):
        self.status_code = status_code
        self.message = message
        self.payload = {**kwargs}
        self.raw_kwargs = raw_kwargs

    def dict(self) -> dict:
        return dict(
            status_code=self.status_code,
            message=self.message,
            payload=self.payload,
        )

    def __str__(self) -> str:
        return (
            f"ClientError(status_code={self.status_code}, "
            f"message={self.message}, "
            f"payload={self.payload}, "
            f"status_code={self.status_code})"
        )

    def __repr__(self) -> str:
        return self.__str__()
