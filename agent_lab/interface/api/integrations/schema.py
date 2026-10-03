from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator

from agent_lab.domain.exceptions.base import InvalidFieldError


integration_valid_types = [
    "anthropic_api_v1",
    "xai_api_v1",
    "openai_api_v1",
    "typesafe_api_v1",
]


class IntegrationCreateRequest(BaseModel):
    integration_type: str
    api_endpoint: str
    api_key: str

    @field_validator("api_endpoint")
    def validate_api_endpoint(cls, v):
        parsed = urlparse(v)
        if not all([parsed.scheme, parsed.netloc]):
            raise InvalidFieldError("api_endpoint", "invalid url format")
        return v

    @field_validator("integration_type")
    def validate_integration_type(cls, v):
        if v not in integration_valid_types:
            raise InvalidFieldError(
                "integration_type",
                f"Invalid integration type, please use one of: {integration_valid_types}",
            )
        return v


class Integration(BaseModel):
    id: str
    created_at: datetime
    is_active: bool
    integration_type: str

    model_config = ConfigDict(from_attributes=True)
