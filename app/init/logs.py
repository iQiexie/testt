import logging
from functools import partial
from typing import Iterable

import rapidjson
import structlog

from app.config.config import LogsConfig

_HANDLER_NAME = "structlog"


def _stringify_exception_field(
    _logger: logging.Logger,
    _info: str,
    event_dict: dict[str],
) -> dict[str]:
    """Flatten the `exception` field into a single string.

    Callers pass `traceback.format_exception(e)`, which is a list of lines. Left alone it lands in
    the JSON log as an array and every log viewer renders it as one unreadable blob per element.
    """
    exception = event_dict.get("exception")

    if isinstance(exception, list):
        event_dict["exception"] = "".join(str(item) for item in exception)
    elif isinstance(exception, BaseException):
        event_dict["exception"] = repr(exception)

    return event_dict


def setup_logs(config: LogsConfig) -> None:
    if not config.LOGS_IS_ENABLED:
        return

    time_stamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")

    shared_processors = [
        time_stamper,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.contextvars.merge_contextvars,
        _stringify_exception_field,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.PATHNAME,
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.THREAD,
                structlog.processors.CallsiteParameter.THREAD_NAME,
                structlog.processors.CallsiteParameter.PROCESS,
                structlog.processors.CallsiteParameter.PROCESS_NAME,
            }
        ),
        structlog.stdlib.ExtraAdder(),
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,  # noqa
        cache_logger_on_first_use=True,
    )

    logs_render = (
        structlog.processors.JSONRenderer(
            serializer=partial(
                rapidjson.dumps,
                ensure_ascii=False,
            )
        )
        if config.LOGS_IS_JSON
        else structlog.dev.ConsoleRenderer(
            colors=True,
        )
    )

    _configure_default_logging_by_custom(
        shared_processors=shared_processors,
        logs_render=logs_render,
        config=config,
    )


def _configure_default_logging_by_custom(
    shared_processors: Iterable[structlog.typing.Processor] | None,
    logs_render: structlog.dev.ConsoleRenderer | structlog.processors.JSONRenderer,
    config: LogsConfig,
) -> None:
    handler = logging.StreamHandler()

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _extract_from_record,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            logs_render,
        ],
    )

    handler.setFormatter(formatter)
    handler.set_name(_HANDLER_NAME)
    root_uvicorn_logger = logging.getLogger()
    # get_app() может вызываться несколько раз в одном процессе (тесты) — не плодим дубли логов
    for existing in [h for h in root_uvicorn_logger.handlers if h.get_name() == _HANDLER_NAME]:
        root_uvicorn_logger.removeHandler(existing)
    root_uvicorn_logger.addHandler(handler)
    root_uvicorn_logger.setLevel(config.LOGS_LEVEL)


def _extract_from_record(
    _logger: logging.Logger,
    _info: str,
    event_dict: dict[str],
) -> dict[str]:
    record = event_dict["_record"]
    event_dict["thread_name"] = record.threadName
    event_dict["process_name"] = record.processName
    return event_dict
