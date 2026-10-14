from pydantic import ConfigDict

from app.init.base_models import BaseModel


class BaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class BaseResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
