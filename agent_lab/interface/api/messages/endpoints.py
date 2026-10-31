from dependency_injector.wiring import inject, Provide
from fastapi import APIRouter, Depends, Body, Response, status
from fastapi.security import HTTPBearer
from fastapi_keycloak_middleware import get_user
from typing_extensions import Annotated, List

from agent_lab.core.container import Container
from agent_lab.domain.exceptions.base import NotFoundError
from agent_lab.domain.models import Message as DomainMessage
from agent_lab.infrastructure.auth.schema import User
from agent_lab.infrastructure.auth.user import get_schema
from agent_lab.interface.api.attachments.schema import Attachment
from agent_lab.interface.api.messages.schema import (
    MessageListRequest,
    MessageExpanded,
    Message,
    MessageRequest,
)
from agent_lab.services.agent_types.base import run_agent
from agent_lab.services.agent_types.registry import AgentRegistry
from agent_lab.services.agents import AgentService
from agent_lab.services.attachments import AttachmentService
from agent_lab.services.messages import MessageService

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.post(
    "/list",
    dependencies=[Depends(bearer_scheme)],
    response_model=List[Message],
    operation_id="get_message_list",
    summary="List messages for an agent",
    description="""
    Returns all messages (human and assistant) associated with a specific agent.

    Use this to retrieve conversation history, reconstruct dialog threads,
    or provide context for follow-up interactions.

    Parameters (JSON body):
    - `agent_id`: The unique identifier of the agent whose messages to retrieve.
    """,
    response_description="List of messages for the agent",
    responses={
        200: {
            "description": "Successfully retrieved messages",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "msg_123",
                            "is_active": True,
                            "created_at": "2024-01-15T10:30:00Z",
                            "message_role": "human",
                            "message_content": "Hello, how can you help?",
                            "agent_id": "agent_456",
                            "response_data": None,
                            "replies_to": None,
                        },
                        {
                            "id": "msg_124",
                            "is_active": True,
                            "created_at": "2024-01-15T10:31:00Z",
                            "message_role": "assistant",
                            "message_content": "I can help you with document analysis.",
                            "agent_id": "agent_456",
                            "response_data": None,
                            "replies_to": "msg_123",
                        },
                    ]
                }
            },
        },
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_456' not found"}
                }
            },
        },
    },
)
@inject
async def get_list(
    message_data: Annotated[
        MessageListRequest,
        Body(
            ...,
            description="Request containing the agent ID to retrieve messages for",
            examples=[{"agent_id": "agent_456"}],
        ),
    ],
    message_service: Annotated[
        MessageService, Depends(Provide[Container.message_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    messages = message_service.get_messages(message_data.agent_id, schema)
    return [Message.model_validate(message) for message in messages]


@router.post(
    "/post",
    dependencies=[Depends(bearer_scheme)],
    response_model=Message,
    operation_id="post_message",
    summary="Send a message to an agent",
    description="""
    Sends a human message to an agent and returns the assistant's response.

    The message is routed to the appropriate agent processor based on agent type.
    Both the human message and the generated response are stored in the conversation history.

    Parameters (JSON body):
    - `agent_id`: The unique identifier of the target agent.
    - `message_role`: Must be "human".
    - `message_content`: The text content of the message.
    - `attachment_id` (optional): ID of a previously uploaded attachment to include.
    """,
    response_description="The assistant's response message",
    responses={
        200: {
            "description": "Message processed and response generated",
            "content": {
                "application/json": {
                    "example": {
                        "id": "msg_789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:31:00Z",
                        "message_role": "assistant",
                        "message_content": "I'd be happy to help you with that!",
                        "agent_id": "agent_456",
                        "response_data": None,
                        "replies_to": "msg_123",
                    }
                }
            },
        },
        400: {
            "description": "Invalid request data",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Field message_role is invalid, reason: not supported"
                    }
                }
            },
        },
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_456' not found"}
                }
            },
        },
        422: {"description": "Validation error"},
    },
)
@inject
async def post_message(
    message_data: Annotated[
        MessageRequest,
        Body(
            ...,
            description="The message to send to the agent",
            examples=[
                {
                    "agent_id": "agent_456",
                    "message_role": "human",
                    "message_content": "Can you help me write a Python function?",
                    "attachment_id": None,
                }
            ],
        ),
    ],
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    agent_registry: Annotated[
        AgentRegistry, Depends(Provide[Container.agent_registry])
    ],
    message_service: Annotated[
        MessageService, Depends(Provide[Container.message_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent = agent_service.get_agent_by_id(message_data.agent_id, schema)
    matching_agent = agent_registry.get_agent(agent.agent_type)

    # Store human message
    human_message = message_service.create_message(
        message_role=message_data.message_role,
        message_content=message_data.message_content,
        agent_id=message_data.agent_id,
        attachment_id=message_data.attachment_id,
        schema=schema,
    )

    # Process human message (synchronous agent run, kept off the event loop)
    processed_message = await run_agent(matching_agent, message_data, schema)

    # Store assistant message
    assistant_message = message_service.create_message(
        message_role="assistant",
        message_content=processed_message.message_content,
        response_data=processed_message.response_data,
        agent_id=processed_message.agent_id,
        replies_to=human_message,
        schema=schema,
    )

    return Message.model_validate(assistant_message)


@router.get(
    "/{message_id}",
    dependencies=[Depends(bearer_scheme)],
    response_model=MessageExpanded,
    summary="Get message details",
    description="""
    Returns an expanded view of an assistant message, including the original human
    message it replies to and any attachment from the human message.

    Parameters:
    - `message_id` (path): The unique identifier of the assistant message.
    """,
    response_description="Expanded message with conversation context",
    responses={
        200: {
            "description": "Successfully retrieved message details",
            "content": {
                "application/json": {
                    "example": {
                        "id": "msg_789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:31:00Z",
                        "message_role": "assistant",
                        "message_content": "Here's the Python function you requested...",
                        "agent_id": "agent_456",
                        "response_data": None,
                        "replies_to": {
                            "id": "msg_123",
                            "is_active": True,
                            "created_at": "2024-01-15T10:30:00Z",
                            "message_role": "human",
                            "message_content": "Can you help me write a Python function?",
                            "agent_id": "agent_456",
                            "response_data": None,
                            "replies_to": None,
                        },
                        "attachment": {
                            "id": "att_456",
                            "is_active": True,
                            "created_at": "2024-01-15T10:29:00Z",
                            "file_name": "requirements.txt",
                            "parsed_content": "fastapi==0.100.0\nlangchain==0.1.0",
                            "embeddings_collection": None,
                        },
                    }
                }
            },
        },
        404: {
            "description": "Message not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Message with ID 'msg_789' not found"}
                }
            },
        },
    },
)
@inject
async def get_by_id(
    message_id: str,
    message_service: Annotated[
        MessageService, Depends(Provide[Container.message_service])
    ],
    attachment_service: Annotated[
        AttachmentService, Depends(Provide[Container.attachment_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    assistant_message = message_service.get_message_by_id(message_id, schema)
    human_message = message_service.get_message_by_id(
        assistant_message.replies_to, schema
    )

    return _format_expanded_response(
        assistant_message, human_message, attachment_service, schema
    )


@router.delete(
    "/delete/{message_id}",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a message",
    description="""
    Permanently removes a message from the system.

    Deleting a message may break reply chains if other messages reference it.
    Related attachments are not affected.

    Parameters:
    - `message_id` (path): The unique identifier of the message to delete.
    """,
    response_description="Message successfully deleted",
    responses={
        204: {"description": "Message successfully deleted"},
        404: {
            "description": "Message not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Message with ID 'msg_789' not found"}
                }
            },
        },
    },
)
@inject
async def remove(
    message_id: str,
    message_service: Annotated[
        MessageService, Depends(Provide[Container.message_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    message_service.delete_message_by_id(message_id, schema)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _format_expanded_response(
    agent_message: DomainMessage,
    human_message: DomainMessage,
    attachment_service: AttachmentService,
    schema: str,
) -> MessageExpanded:
    attachment_response = None

    if human_message.attachment_id is not None:
        try:
            attachment = attachment_service.get_attachment_by_id(
                human_message.attachment_id, schema
            )
            attachment_response = Attachment.model_validate(attachment)
        except NotFoundError:
            # Attachment was deleted or corrupted, continue without it
            pass

    response = MessageExpanded(
        id=agent_message.id,
        is_active=agent_message.is_active,
        created_at=agent_message.created_at,
        agent_id=agent_message.agent_id,
        message_role=agent_message.message_role,
        message_content=agent_message.message_content,
        response_data=agent_message.response_data,
        replies_to=Message.model_validate(human_message),
        attachment=attachment_response,
    )

    return response
