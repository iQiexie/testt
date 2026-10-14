import json
from typing import Callable

import structlog

logger = structlog.stdlib.get_logger()


def struct_log(event: str, special_logger: Callable = None, **kwargs) -> None:
    payload = dict(event=event, payload=kwargs)

    try:
        log = json.dumps(payload, ensure_ascii=False)
    except TypeError:
        log = payload

    if special_logger:
        special_logger(log)
    else:
        logger.info(log)
