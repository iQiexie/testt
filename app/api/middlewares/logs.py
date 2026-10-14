import json
import re
import time
import traceback
import uuid
from json import JSONDecodeError
from typing import Any, Dict

import structlog
from fastapi import FastAPI
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config.config import Config
from app.config.constants import (
    LOGGING_DISABLED_ENDPOINTS,
    LOGGING_SENSITIVE_FIELDS,
    LOGGING_SENSITIVE_REPLACEMENT,
)
from app.utils import struct_log

logger = structlog.stdlib.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, config: Config):
        BaseHTTPMiddleware.__init__(self, app=app, dispatch=self.dispatch)
        self.config = config

        # Matches `"<key containing a sensitive word>": "<value>"` in the JSON body and keeps the
        # key while replacing the value. Compiled once — this runs on every request.
        regex_str = r'("[^"]*?(?={keywords})[^"]*":\s*")[^"]*"'
        regex_with_keys = regex_str.format(keywords="|".join(LOGGING_SENSITIVE_FIELDS))
        self.regex_pattern = re.compile(regex_with_keys, flags=re.IGNORECASE)
        self.substitution = rf'\1{LOGGING_SENSITIVE_REPLACEMENT}"'

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.time()
        request_dict = await self._get_request_dict(request=request)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**request_dict)

        try:
            exception = None
            response = await call_next(request)
            response.headers["X-Error-Trace"] = request_dict["key"]
        except Exception as ex:
            exception = ex
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"message": "Server Error. Please try again later"},
            )
            response.headers["X-Error-Trace"] = request_dict["key"]

        total_time = time.time() - start
        duration = f"{total_time:.3f}"
        event = f"{response.status_code} | {duration} s"

        if (exception is None) and (request.url.path not in LOGGING_DISABLED_ENDPOINTS):
            logger.info(event=event, status_code=response.status_code, duration=duration)

        if exception:
            if self.config.logs.LOGS_IS_JSON:
                formatted_exception = traceback.format_exception(exception)
            else:
                formatted_exception = str(traceback.format_exception(exception))

            logger.error(
                event="A server error has occurred",
                exception=formatted_exception,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                duration=duration,
            )

        return response

    async def _get_request_dict(self, request: Request) -> Dict[str, Any]:
        content_type = request.headers.get("Content-Type", "")
        client_ip = request.headers.get("x-real-ip") or request.client.host

        try:
            body_bytes = await request.body()
        except Exception:  # noqa
            body_bytes = b""

        return {
            "method": str(request.method),
            "url": str(request.url),
            "query": json.dumps(dict(request.query_params.items()), ensure_ascii=False),
            "body": self._format_body_for_logs(body=body_bytes, content_type=content_type),
            "client_ip": client_ip,
            "idempotency_key": request.headers.get("Idempotency-Key", ""),
            "key": str(uuid.uuid4()),
        }

    def _format_body_for_logs(self, body: bytes, content_type: str) -> str:
        if not body:
            return ""

        decoded_body = body.decode("utf-8", errors="replace")
        if content_type.startswith("application/json"):
            try:
                decoded_body = json.dumps(json.loads(decoded_body), ensure_ascii=False)
                decoded_body = self._protect_body(body=decoded_body)
            except JSONDecodeError:
                pass

        return decoded_body

    def _protect_body(self, body: str) -> str:
        try:
            return re.sub(
                self.regex_pattern,
                repl=self.substitution,
                string=body,
            )
        except Exception as e:  # noqa: BLE001
            struct_log(event="Failed to protect string", exception=traceback.format_exception(e))
            return body
