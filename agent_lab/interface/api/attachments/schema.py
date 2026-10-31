from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator
from typing_extensions import Optional

from agent_lab.domain.exceptions.base import InvalidFieldError


class EmbeddingsRequest(BaseModel):
    attachment_id: str
    language_model_id: str
    collection_name: str

    @field_validator("collection_name")
    def validate_collection_name(cls, v):
        if not v.strip():
            raise InvalidFieldError("collection_name", "must not be blank")
        return v


class Attachment(BaseModel):
    id: str
    is_active: bool
    created_at: datetime
    file_name: str
    parsed_content: str
    embeddings_collection: Optional[str]

    model_config = ConfigDict(from_attributes=True)
