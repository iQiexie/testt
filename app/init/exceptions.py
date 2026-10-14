import functools
import traceback

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from pydantic import ValidationError
from pydantic_core import to_json
from sqlalchemy.exc import IntegrityError, NoResultFound
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.exceptions import ClientError
from app.utils import struct_log


class _JSONResponse(JSONResponse):
    def render(self, content: dict) -> bytes:
        return to_json(value=content, indent=None, serialize_unknown=True)


logger = structlog.stdlib.get_logger()


def client_error_handler(_: Request, exc: ClientError) -> _JSONResponse:
    logger.warning(exc.message)
    if exc.raw_kwargs:
        content = exc.raw_kwargs
    else:
        content = {"text": exc.message, "errors": exc.payload}
    return _JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


def validation_error_handler(_: Request, exc: ValidationError | RequestValidationError) -> _JSONResponse:
    struct_log(
        event="Validation Error",
        model=exc.title if hasattr(exc, "title") else "",
        exc=exc,
        exc_errors=exc.errors(),
        special_logger=functools.partial(
            logger.error,
            exception=traceback.format_exception(exc),
        ),
    )

    return _JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "Unprocessable Entity",
            "payload": exc.errors(),
        },
    )


def integrity_error_handler(_: Request, exc: IntegrityError | NoResultFound) -> _JSONResponse:

    if isinstance(exc, NoResultFound):
        exc_errors = "No result found"
    else:
        try:
            exc_errors = exc.orig.args[0].split("\n")[1]
        except (KeyError, IndexError):
            exc_errors = str(exc)

    struct_log(
        event="Integrity Error",
        model=exc.code,
        exc=exc,
        exc_errors=exc_errors,
        special_logger=functools.partial(
            logger.error,
            exception=traceback.format_exception(exc),
        ),
    )

    return _JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Integrity Error",
            "payload": exc_errors,
        },
    )


def setup_exceptions(app: FastAPI) -> FastAPI:
    app.add_exception_handler(exc_class_or_status_code=ClientError, handler=client_error_handler)
    app.add_exception_handler(exc_class_or_status_code=ValidationError, handler=validation_error_handler)
    app.add_exception_handler(exc_class_or_status_code=RequestValidationError, handler=validation_error_handler)
    app.add_exception_handler(exc_class_or_status_code=ResponseValidationError, handler=validation_error_handler)
    app.add_exception_handler(exc_class_or_status_code=IntegrityError, handler=integrity_error_handler)
    app.add_exception_handler(exc_class_or_status_code=NoResultFound, handler=integrity_error_handler)

    return app
