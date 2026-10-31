import asyncio
import json

from dependency_injector.wiring import Provide, inject
from fastapi import (
    APIRouter,
    Body,
    Depends,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.security import HTTPBearer
from fastapi_keycloak_middleware import get_user
from typing_extensions import List, Annotated

from agent_lab.core.container import Container
from agent_lab.domain.exceptions.base import NotFoundError
from agent_lab.domain.models import Agent as DomainAgent
from agent_lab.infrastructure.auth.schema import User
from agent_lab.infrastructure.auth.user import get_schema
from agent_lab.interface.api.agents.schema import (
    AgentCreateRequest,
    AgentExpanded,
    Agent,
    AgentSetting,
    AgentSettingUpdateRequest,
    AgentUpdateRequest,
)
from agent_lab.services.agent_settings import AgentSettingService
from agent_lab.services.agent_types.registry import AgentRegistry
from agent_lab.services.agents import AgentService
from agent_lab.services.tasks import TaskNotificationService

router = APIRouter()
bearer_scheme = HTTPBearer()


@router.get(
    path="/list",
    dependencies=[Depends(bearer_scheme)],
    response_model=List[Agent],
    operation_id="get_agent_list",
    summary="List all agents",
    description="""
    Returns all agents registered in the platform.

    Each agent entry includes its ID, name, type, summary, linked language model, and creation timestamp.
    Use this to discover available agents and their capabilities.
    """,
    response_description="List of all agents",
    responses={
        200: {
            "description": "Successfully retrieved agents list",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "agent_123456789",
                            "is_active": True,
                            "created_at": "2024-01-15T10:30:00Z",
                            "agent_name": "image-analyzer",
                            "agent_type": "vision_document",
                            "agent_summary": "Analyzes images and extracts information",
                            "language_model_id": "lm_abc123",
                        },
                        {
                            "id": "agent_987654321",
                            "is_active": True,
                            "created_at": "2024-01-14T15:20:00Z",
                            "agent_name": "support-bot",
                            "agent_type": "react_rag",
                            "agent_summary": "Handles customer inquiries using RAG",
                            "language_model_id": "lm_def456",
                        },
                    ]
                }
            },
        }
    },
)
@inject
async def get_list(
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agents = agent_service.get_agents(schema)
    return [Agent.model_validate(agent) for agent in agents]


@router.get(
    path="/types",
    dependencies=[Depends(bearer_scheme)],
    response_model=List[str],
    operation_id="get_agent_types",
    summary="List available agent types",
    description="""
    Returns the agent types registered in this deployment.

    Agent types self-register at startup via @discoverable_agent discovery, so the
    list reflects both built-in and application-specific agents.
    """,
    response_description="List of registered agent types",
)
@inject
async def get_types(
    agent_registry: Annotated[
        AgentRegistry, Depends(Provide[Container.agent_registry])
    ],
):
    return agent_registry.get_agent_types()


@router.get(
    path="/{agent_id}",
    dependencies=[Depends(bearer_scheme)],
    response_model=AgentExpanded,
    summary="Get agent by ID",
    description="""
    Returns detailed information about a specific agent, including all its configuration settings.

    Parameters:
    - `agent_id` (path): The unique identifier of the agent.
    """,
    response_description="Agent details with settings",
    responses={
        200: {
            "description": "Successfully retrieved agent details",
            "content": {
                "application/json": {
                    "example": {
                        "id": "agent_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "agent_name": "content-analyzer",
                        "agent_type": "vision_document",
                        "agent_summary": "Analyzes documents and images",
                        "language_model_id": "lm_abc123",
                        "ag_settings": [
                            {
                                "setting_key": "temperature",
                                "setting_value": "0.7",
                            },
                            {
                                "setting_key": "max_tokens",
                                "setting_value": "2048",
                            },
                        ],
                    }
                }
            },
        },
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_123456789' not found"}
                }
            },
        },
    },
)
@inject
async def get_by_id(
    agent_id: str,
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    agent_setting_service: Annotated[
        AgentSettingService, Depends(Provide[Container.agent_setting_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent = agent_service.get_agent_by_id(agent_id, schema)
    return _format_expanded_response(agent, agent_setting_service, schema)


@router.post(
    path="/create",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_201_CREATED,
    response_model=Agent,
    summary="Create a new agent",
    description="""
    Creates a new agent linked to a language model. Initializes default settings based on the agent type.

    Available agent types are discovered at startup; list them with `GET /agents/types`.

    Typical workflow:
    1. Create an integration (API provider connection).
    2. Create a language model linked to the integration.
    3. Create an agent with this endpoint, specifying the language model and agent type.
    4. Send messages to the agent using `post_message`.

    Parameters (JSON body):
    - `agent_name`: Alphanumeric name with hyphens or underscores.
    - `agent_type`: One of the available agent types listed above.
    - `language_model_id`: ID of an existing language model.
    """,
    response_description="The newly created agent",
    responses={
        201: {
            "description": "Agent successfully created",
            "content": {
                "application/json": {
                    "example": {
                        "id": "agent_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "agent_name": "content-analyzer",
                        "agent_type": "vision_document",
                        "agent_summary": "",
                        "language_model_id": "lm_abc123",
                    }
                }
            },
        },
        400: {
            "description": "Invalid agent configuration",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Field agent_type is invalid, reason: not supported"
                    }
                }
            },
        },
        404: {
            "description": "Language model not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Language model with ID 'lm_abc123' not found"
                    }
                }
            },
        },
        422: {
            "description": "Validation error",
        },
    },
)
@inject
async def add(
    agent_data: Annotated[AgentCreateRequest, Body(...)],
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    agent_registry: Annotated[
        AgentRegistry, Depends(Provide[Container.agent_registry])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent = agent_service.create_agent(
        language_model_id=agent_data.language_model_id,
        agent_name=agent_data.agent_name,
        agent_type=agent_data.agent_type,
        schema=schema,
    )
    agent_registry.get_agent(agent_data.agent_type).create_default_settings(
        agent.id, schema
    )
    return Agent.model_validate(agent)


@router.delete(
    path="/delete/{agent_id}",
    dependencies=[Depends(bearer_scheme)],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
    description="""
    Permanently removes an agent and its associated settings from the system.

    Parameters:
    - `agent_id` (path): The unique identifier of the agent to delete.
    """,
    response_description="Agent successfully deleted",
    responses={
        204: {"description": "Agent successfully deleted"},
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_123456789' not found"}
                }
            },
        },
    },
)
@inject
async def remove(
    agent_id: str,
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent_service.delete_agent_by_id(agent_id, schema)


@router.post(
    path="/update",
    dependencies=[Depends(bearer_scheme)],
    response_model=Agent,
    summary="Update an agent",
    description="""
    Updates an agent's name, linked language model, or summary.

    Parameters (JSON body):
    - `agent_id`: The unique identifier of the agent to update.
    - `agent_name`: New alphanumeric name with hyphens or underscores.
    - `language_model_id`: ID of the new language model to link.
    - `agent_summary` (optional): Updated description of the agent.
    """,
    response_description="Updated agent",
    responses={
        200: {
            "description": "Agent successfully updated",
            "content": {
                "application/json": {
                    "example": {
                        "id": "agent_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "agent_name": "updated-analyzer",
                        "agent_type": "vision_document",
                        "agent_summary": "Updated document analyzer",
                        "language_model_id": "lm_def456",
                    }
                }
            },
        },
        404: {
            "description": "Agent or language model not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_123456789' not found"}
                }
            },
        },
        400: {
            "description": "Invalid agent name",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Field agent_name is invalid, reason: contains invalid characters"
                    }
                }
            },
        },
        422: {"description": "Validation error"},
    },
)
@inject
async def update(
    agent_data: Annotated[AgentUpdateRequest, Body(...)],
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent = agent_service.update_agent(
        agent_id=agent_data.agent_id,
        agent_name=agent_data.agent_name,
        language_model_id=agent_data.language_model_id,
        agent_summary=agent_data.agent_summary,
        schema=schema,
    )
    return Agent.model_validate(agent)


@router.post(
    path="/update_setting",
    dependencies=[Depends(bearer_scheme)],
    response_model=AgentExpanded,
    summary="Update an agent setting",
    description="""
    Updates a single configuration setting for an agent by key.
    Returns the full agent with all current settings after the update.

    Parameters (JSON body):
    - `agent_id`: The unique identifier of the agent.
    - `setting_key`: The setting key to update (e.g. "temperature", "max_tokens").
    - `setting_value`: The new value for the setting.
    """,
    response_description="Updated agent with all settings",
    responses={
        200: {
            "description": "Setting successfully updated",
            "content": {
                "application/json": {
                    "example": {
                        "id": "agent_123456789",
                        "is_active": True,
                        "created_at": "2024-01-15T10:30:00Z",
                        "agent_name": "content-analyzer",
                        "agent_type": "vision_document",
                        "agent_summary": "Analyzes documents and images",
                        "language_model_id": "lm_abc123",
                        "ag_settings": [
                            {
                                "setting_key": "temperature",
                                "setting_value": "0.5",
                            },
                            {
                                "setting_key": "max_tokens",
                                "setting_value": "4096",
                            },
                        ],
                    }
                }
            },
        },
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_123456789' not found"}
                }
            },
        },
        400: {
            "description": "Invalid setting key or value",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Field setting_value is invalid, reason: contains invalid characters"
                    }
                }
            },
        },
        422: {"description": "Validation error"},
    },
)
@inject
async def update_setting(
    agent_data: Annotated[AgentSettingUpdateRequest, Body(...)],
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    agent_setting_service: Annotated[
        AgentSettingService, Depends(Provide[Container.agent_setting_service])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent_setting_service.update_by_key(
        agent_id=agent_data.agent_id,
        setting_key=agent_data.setting_key,
        setting_value=agent_data.setting_value,
        schema=schema,
    )

    agent = agent_service.get_agent_by_id(agent_data.agent_id, schema)
    return _format_expanded_response(agent, agent_setting_service, schema)


@router.post(
    path="/{agent_id}/reset_settings",
    dependencies=[Depends(bearer_scheme)],
    response_model=AgentExpanded,
    summary="Reset agent settings to factory defaults",
    description="""
    Deletes all current settings for the agent and re-seeds the factory defaults
    defined by the agent's type (same defaults that are applied at agent creation).

    Parameters:
    - `agent_id` (path): The unique identifier of the agent.
    """,
    response_description="Agent with freshly seeded default settings",
    responses={
        200: {"description": "Settings successfully reset"},
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "example": {"detail": "Agent with ID 'agent_123456789' not found"}
                }
            },
        },
    },
)
@inject
async def reset_settings(
    agent_id: str,
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
    agent_setting_service: Annotated[
        AgentSettingService, Depends(Provide[Container.agent_setting_service])
    ],
    agent_registry: Annotated[
        AgentRegistry, Depends(Provide[Container.agent_registry])
    ],
    user: Annotated[User, Depends(get_user)],
):
    schema = get_schema(user.id if user is not None else None)
    agent = agent_service.get_agent_by_id(agent_id, schema)
    agent_setting_service.delete_by_agent_id(agent.id, schema)
    agent_registry.get_agent(agent.agent_type).create_default_settings(agent.id, schema)
    return _format_expanded_response(agent, agent_setting_service, schema)


@router.websocket("/ws/task_updates/{agent_id}")
@inject
async def task_updates_endpoint(
    websocket: WebSocket,
    agent_id: str,
    task_notification_service: Annotated[
        TaskNotificationService, Depends(Provide[Container.task_notification_service])
    ],
    agent_service: Annotated[AgentService, Depends(Provide[Container.agent_service])],
):
    # stream only updates of agents that exist in the caller's own tenant
    user: User | None = websocket.scope.get("user")
    schema = get_schema(user.id if user is not None else None)
    try:
        agent_service.get_agent_by_id(agent_id, schema)
    except NotFoundError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    task_notification_service.subscribe()
    loop = asyncio.get_event_loop()

    def get_next_message():
        return next(task_notification_service.listen())

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    loop.run_in_executor(None, get_next_message), timeout=30
                )
            except asyncio.TimeoutError:
                break

            data = _parse_agent_task_message(message, agent_id)
            if data is not None:
                await websocket.send_json(data)
                break
    except WebSocketDisconnect:
        pass
    finally:
        task_notification_service.close()


def _parse_agent_task_message(message: dict, agent_id: str) -> dict | None:
    if message.get("type") != "message":
        return None
    try:
        data = json.loads(message["data"])
    except (ValueError, TypeError):
        return None
    if data.get("agent_id") != agent_id:
        return None
    return data


def _format_expanded_response(
    agent: DomainAgent, agent_setting_service: AgentSettingService, schema: str
) -> AgentExpanded:
    settings = agent_setting_service.get_agent_settings(agent.id, schema)
    response = AgentExpanded.model_validate(agent)
    response.ag_settings = [
        AgentSetting.model_validate(setting) for setting in settings
    ]
    return response
