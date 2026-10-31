from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

from agent_lab.interface.mcp.prompt_registry import PromptRegistry
from agent_lab.interface.mcp.registrar import McpRegistrar
from agent_lab.interface.mcp.registrar_registration import discoverable_mcp_registrar
from agent_lab.services.agent_types.base import run_agent
from agent_lab.interface.mcp.schema import (
    AgentItem,
    MessageItem,
    PostMessageResult,
    _get_mcp_schema,
)
from agent_lab.interface.mcp.tool_registration import discoverable_mcp_tool

if TYPE_CHECKING:
    from agent_lab.core.container import Container


# The leading ``container`` parameter is injected by DecoratedToolRegistrar and
# hidden from the client-facing schema; it is intentionally left unannotated so
# fastmcp's get_type_hints never tries to resolve the TYPE_CHECKING-only import.
@discoverable_mcp_tool(
    name="get_agent_list",
    description="List all AI agents registered on the Agent-Lab platform. "
    "Returns each agent's ID, name, type, capabilities summary, "
    "and linked language model. Use this to discover what agents "
    "are available and what they can do.",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def get_agent_list(container) -> list[AgentItem]:
    schema = _get_mcp_schema()
    agent_service = container.agent_service()
    agents = agent_service.get_agents(schema)
    return [
        AgentItem(
            id=a.id,
            agent_name=a.agent_name,
            agent_type=a.agent_type,
            agent_summary=a.agent_summary,
            language_model_id=a.language_model_id,
            is_active=a.is_active,
        )
        for a in agents
    ]


@discoverable_mcp_tool(
    name="get_message_list",
    description="Retrieve conversation history for a specific agent. "
    "Returns all messages (human and assistant) in chronological order. "
    "Use this to review past interactions or provide context.",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def get_message_list(
    container,
    agent_id: Annotated[
        str,
        Field(
            description="The unique identifier of the agent whose messages to retrieve"
        ),
    ],
) -> list[MessageItem]:
    schema = _get_mcp_schema()
    message_service = container.message_service()
    messages = message_service.get_messages(agent_id, schema)
    return [
        MessageItem(
            id=m.id,
            message_role=m.message_role,
            message_content=m.message_content,
            agent_id=m.agent_id,
            response_data=m.response_data,
            replies_to=m.replies_to,
        )
        for m in messages
    ]


@discoverable_mcp_tool(
    name="post_message",
    description="Send a message to an agent and receive the assistant's response. "
    "The message is routed to the appropriate agent processor based on agent type. "
    "Both the human message and the generated response are stored in conversation history.",
    annotations={"readOnlyHint": False, "openWorldHint": False},
)
async def post_message(
    container,
    agent_id: Annotated[
        str,
        Field(description="The unique identifier of the target agent"),
    ],
    message_content: Annotated[
        str,
        Field(description="The text content of the message to send"),
    ],
    attachment_id: Annotated[
        Optional[str],
        Field(description="Optional ID of a previously uploaded attachment to include"),
    ] = None,
) -> PostMessageResult:
    from agent_lab.interface.api.messages.schema import MessageRequest

    schema = _get_mcp_schema()
    agent_service = container.agent_service()
    agent_registry = container.agent_registry()
    message_service = container.message_service()

    agent = agent_service.get_agent_by_id(agent_id, schema)
    matching_agent = agent_registry.get_agent(agent.agent_type)

    message_request = MessageRequest(
        agent_id=agent_id,
        message_role="human",
        message_content=message_content,
        attachment_id=attachment_id,
    )

    human_message = message_service.create_message(
        message_role="human",
        message_content=message_content,
        agent_id=agent_id,
        attachment_id=attachment_id,
        schema=schema,
    )

    # the agent run is synchronous: keep it off the event loop
    processed_message = await run_agent(matching_agent, message_request, schema)

    assistant_message = message_service.create_message(
        message_role="assistant",
        message_content=processed_message.message_content,
        response_data=processed_message.response_data,
        agent_id=processed_message.agent_id,
        replies_to=human_message,
        schema=schema,
    )

    return PostMessageResult(
        id=assistant_message.id,
        message_content=assistant_message.message_content,
        agent_id=assistant_message.agent_id,
        response_data=assistant_message.response_data,
    )


@discoverable_mcp_registrar(extra_deps=("prompt_registry",))
class DefaultToolRegistrar(McpRegistrar):
    """Registers the ``read_prompt_mcp`` tool and the ``prompt://`` resource.

    The platform's stateless CRUD tools (``get_agent_list``,
    ``get_message_list``, ``post_message``) are ``@discoverable_mcp_tool`` functions
    above; this registrar covers the two surfaces that need the shared
    ``PromptRegistry`` — the tool-based prompt reader and its resource-flavored
    equivalent.
    """

    def __init__(self, prompt_registry: PromptRegistry) -> None:
        self._prompt_registry = prompt_registry

    def register_tools(self, mcp: FastMCP, container: Container) -> None:
        registry = self._prompt_registry
        available = ", ".join(registry.names()) or "<none currently registered>"

        @mcp.tool(
            name="read_prompt_mcp",
            description="Load an Agent-Lab workflow system prompt by name. "
            "Tool-based equivalent of reading the MCP resource at "
            "prompt://<name> or calling prompts/get for the same name — use "
            "whichever path your runtime exposes. Returns the prompt text "
            "with any per-tenant override applied when available; optional "
            "parameters are rendered into the template server-side. "
            f"Available prompt names: {available}.",
            annotations={"readOnlyHint": True, "openWorldHint": False},
        )
        async def read_prompt_mcp(
            name: Annotated[
                str,
                Field(
                    description="Prompt identifier, matching the name segment "
                    "of the corresponding prompt:// resource URI."
                ),
            ],
            parameters: Annotated[
                Optional[dict[str, str]],
                Field(
                    description="Optional template parameters rendered "
                    "server-side (e.g. {'deep_search_mode': 'true'}); the "
                    "prompt's advertised arguments list which keys apply."
                ),
            ] = None,
        ) -> str:
            try:
                return registry.resolve(name, **(parameters or {}))
            except KeyError as exc:
                raise ValueError(str(exc)) from exc

    def register_resources(self, mcp: FastMCP) -> None:
        registry = self._prompt_registry

        @mcp.resource(
            uri="prompt://{name}{?parameters}",
            name="read_prompt",
            description="Read any registered workflow system prompt by name — "
            "the resource-flavored alternative to the read_prompt_mcp tool. "
            "Per-tenant overrides apply. The optional 'parameters' query "
            "argument is a JSON object of template parameters rendered "
            "server-side.",
            mime_type="text/plain",
        )
        def read_prompt(name: str, parameters: str = "") -> str:
            params = json.loads(parameters) if parameters else {}
            try:
                return registry.resolve(name, **params)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
