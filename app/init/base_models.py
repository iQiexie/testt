import uuid
from datetime import datetime, timezone
from decimal import Decimal
from json import JSONEncoder
from typing import Any

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict


class DecimalEncoder(JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.astimezone(timezone.utc).isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)

        return super(DecimalEncoder, self).default(o)


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
