from io import BytesIO
from urllib.parse import quote

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, File, Depends, Body, Path, UploadFile
from fastapi.security import HTTPBearer
from fastapi_keycloak_middleware import get_user
from starlette import status
from typing_extensions import Annotated, List
from starlette.responses import StreamingResponse

from agent_lab.core.container import Container
from agent_lab.domain.exceptions.base import FileToLargeError
from agent_lab.infrastructure.auth.schema import User
from agent_lab.infrastructure.auth.user import get_schema
from agent_lab.interface.api.attachments.schema import Attachment, EmbeddingsRequest
from agent_lab.services.attachments import AttachmentService

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.get(
    path="/list",
    dependencies=[Depends(bearer_scheme)],
    response_model=List[Attachment],
    operation_id="get_attachment_list",
    summary="List all attachments",
    description="""
    Returns all active attachments belonging to the authenticated user.

    Each attachment includes its metadata: file name, creation timestamp,
    parsed text content, and the associated embeddings collection (if any).

    This endpoint is useful for browsing uploaded files before downloading,
    deleting, or generating embeddings for them.

    The response excludes raw binary content for performance. Use the
    `/download/{attachment_id}` endpoint to retrieve the actual file.
    """,
    response_description="List of all active attachments for the current user",
    responses={
        200: {
            "description": "Attachments retrieved successfully",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "att_123456789",
                            "is_active": True,
                            "created_at": "2024-01-15T10:30:00Z",
                            "file_name": "document.pdf",
                            "parsed_content": "Extracted text content...",
                            "embeddings_collection": "my_documents",
                        },
                        {
                            "id": "att_987654321",
                            "is_active": True,
                            "created_at": "2024-01-16T14:00:00Z",
                            "file_name": "notes.txt",
                            "parsed_content": "Meeting notes from...",
                            "embeddings_collection": None,
                        },
                    ]
                }
            },
        },
    },
)
@inject
async def get_list(
    attachment_service: Annotated[
        AttachmentService, Depends(Provide[Container.attachment_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    attachments = attachment_service.get_attachments(schema)
    return [Attachment.model_validate(attachment) for attachment in attachments]


@router.post(
    "/upload",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_201_CREATED,
    response_model=Attachment,
    summary="Upload a file attachment",
    description="""
    Uploads a file to the system for later use with agents.

    The file is processed, its content is extracted and stored as metadata.
    Maximum upload size is 10 MB per file.

    Supported file types include documents (PDF, DOC, DOCX, TXT),
    images (JPG, PNG), and audio files (MP3, WAV, OGG, WEBM).

    Parameters (multipart form):
    - `file`: The file to upload.
    """,
    response_description="The uploaded attachment with metadata",
    responses={
        201: {
            "description": "Attachment successfully uploaded",
            "content": {
                "application/json": {
                    "example": {
                        "id": "att_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "file_name": "document.pdf",
                        "parsed_content": "Extracted text content from the document...",
                        "embeddings_collection": None,
                    }
                }
            },
        },
        413: {
            "description": "File too large",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "File size 15728640 exceeds the maximum allowed size of 10485760 bytes"
                    }
                }
            },
        },
        422: {
            "description": "Validation or file processing error",
            "content": {
                "application/json": {"example": {"detail": "No file provided"}}
            },
        },
    },
)
@inject
async def upload_attachment(
    file: Annotated[
        UploadFile,
        File(..., description="The file to upload.", examples=["document.pdf"]),
    ],
    attachment_service: Annotated[
        AttachmentService, Depends(Provide[Container.attachment_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    # validate file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    max_size = 10 * 1024 * 1024  # 10 MB
    if file_size > max_size:
        raise FileToLargeError(file_size, max_size)
    file.file.seek(0)

    attachment = await attachment_service.create_attachment_with_file(
        file=file, schema=schema
    )
    return Attachment.model_validate(attachment)


@router.get(
    "/download/{attachment_id}",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_200_OK,
    response_class=StreamingResponse,
    summary="Download an attachment",
    description="""
    Downloads a previously uploaded attachment by its ID.

    The file is streamed with its original filename and content type preserved
    in the response headers.

    Parameters:
    - `attachment_id` (path): The unique identifier of the attachment to download.
    """,
    response_description="File content streamed as attachment",
    responses={
        200: {
            "description": "File successfully downloaded",
            "content": {"application/octet-stream": {"example": "Binary file content"}},
            "headers": {
                "Content-Disposition": {
                    "description": "Attachment filename",
                    "schema": {
                        "type": "string",
                        "example": "attachment; filename=document.pdf",
                    },
                }
            },
        },
        404: {
            "description": "Attachment not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Attachment with ID 'att_123456789' not found"
                    }
                }
            },
        },
    },
)
@inject
async def download_attachment(
    attachment_id: Annotated[
        str,
        Path(
            ...,
            description="Unique identifier of the attachment to download",
            examples=["att_123456789"],
            min_length=1,
            max_length=50,
        ),
    ],
    attachment_service: Annotated[
        AttachmentService, Depends(Provide[Container.attachment_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    attachment = attachment_service.get_attachment_by_id(attachment_id, schema)
    response = StreamingResponse(
        BytesIO(attachment.raw_content),
        media_type="application/octet-stream",
    )
    # Header values are latin-1: send an ASCII fallback plus the RFC 5987 UTF-8 name.
    name = attachment.file_name
    fallback = "".join(
        c if c.isascii() and c.isprintable() and c not in '"\\' else "?" for c in name
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
    )
    return response


@router.post(
    "/embeddings",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_201_CREATED,
    response_model=Attachment,
    summary="Generate embeddings for an attachment",
    description="""
    Generates vector embeddings from the content of a previously uploaded attachment.

    The text is extracted, split into chunks, and embedded using the specified language model.
    Embeddings are stored in the given collection for later similarity search by RAG agents.

    Parameters (JSON body):
    - `attachment_id`: ID of the attachment to generate embeddings for.
    - `language_model_id`: ID of the language model to use for embedding generation.
    - `collection_name`: Name of the vector collection to store embeddings in.
    """,
    response_description="Attachment updated with embedding collection reference",
    responses={
        201: {
            "description": "Embeddings successfully generated",
            "content": {
                "application/json": {
                    "example": {
                        "id": "att_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "file_name": "document.pdf",
                        "parsed_content": "Extracted text content from the document...",
                        "embeddings_collection": "my_documents",
                    }
                }
            },
        },
        404: {
            "description": "Attachment or language model not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Attachment with ID 'att_123456789' not found"
                    }
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid language model ID or collection name"
                    }
                }
            },
        },
    },
)
@inject
async def create_embeddings(
    embeddings: Annotated[
        EmbeddingsRequest,
        Body(
            ...,
            description="Configuration for embedding generation",
            examples=[
                {
                    "attachment_id": "att_123456789",
                    "language_model_id": "lm_abc123",
                    "collection_name": "my_documents",
                }
            ],
        ),
    ],
    attachment_service: Annotated[
        AttachmentService, Depends(Provide[Container.attachment_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    attachment = await attachment_service.create_embeddings(
        attachment_id=embeddings.attachment_id,
        language_model_id=embeddings.language_model_id,
        collection_name=embeddings.collection_name,
        schema=schema,
    )
    return Attachment.model_validate(attachment)
