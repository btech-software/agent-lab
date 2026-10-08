import os
from uuid import uuid4
from IPython.display import Image, display
import requests
from langchain_core.runnables.graph import MermaidDrawMethod

from agent_lab.app_factory import DEFAULT_SCAN_PACKAGES, bind_agent_registry
from agent_lab.core.config import default_config_source, load_config
from agent_lab.core.container import Container
from agent_lab.services.agent_types import discovery

DEFAULT_AGENT_LAB_ENDPOINT = "http://localhost:18000"
REQUEST_TIMEOUT_SECONDS = 300

# embeddings model served by the local openai-compatible server (e.g. ollama)
DEFAULT_EMBEDDINGS_TAG = "embeddinggemma-2"
DEFAULT_RAG_COLLECTION = "static_document_data_ollama_embeddings"
RAG_AGENT_TYPES = {"adaptive_rag", "react_rag", "coordinator_planner_supervisor"}


def bootstrap_container(modules, scan_packages=DEFAULT_SCAN_PACKAGES):
    # mirrors create_app()'s composition root for use outside the app factory;
    # config-*.yml paths are relative, so call this after chdir to the repo root
    discovery.scan_packages(scan_packages)
    discovery.load_entry_point_agents()
    container = Container()
    load_config(container, default_config_source())
    bind_agent_registry(container)
    container.init_resources()
    container.wire(modules=modules)
    return container


def print_graph(graph):
    display(
        Image(
            graph.get_graph(xray=True).draw_mermaid_png(
                draw_method=MermaidDrawMethod.API
            )
        )
    )


def _post(path: str, agent_lab_endpoint: str, **kwargs) -> dict:
    response = requests.post(
        f"{agent_lab_endpoint}{path}",
        headers={"Authorization": f"Bearer {os.getenv('ACCESS_TOKEN', 'x')}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def create_llm_with_integration(
    llm_tag: str,
    integration_params: dict,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    embeddings_tag: str | None = None,
) -> dict:
    # pin embeddings to the model served by EMBEDDINGS_ENDPOINT (openai_api_v1
    # integrations default to text-embedding-3-large, which Ollama lacks)
    if embeddings_tag is None and os.getenv("EMBEDDINGS_ENDPOINT"):
        embeddings_tag = DEFAULT_EMBEDDINGS_TAG

    integration = _post(
        "/integrations/create", agent_lab_endpoint, json=integration_params
    )
    llm = _post(
        "/llms/create",
        agent_lab_endpoint,
        json={"integration_id": integration["id"], "language_model_tag": llm_tag},
    )

    if embeddings_tag is not None:
        _post(
            "/llms/update_setting",
            agent_lab_endpoint,
            json={
                "language_model_id": llm["id"],
                "setting_key": "embeddings",
                "setting_value": embeddings_tag,
            },
        )

    return llm


def create_agent_with_integration(
    llm_tag: str,
    agent_type: str,
    integration_params: dict,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    embeddings_tag: str | None = None,
    rag_collection: str = DEFAULT_RAG_COLLECTION,
) -> dict:
    llm = create_llm_with_integration(
        llm_tag=llm_tag,
        integration_params=integration_params,
        agent_lab_endpoint=agent_lab_endpoint,
        embeddings_tag=embeddings_tag,
    )
    agent = _post(
        "/agents/create",
        agent_lab_endpoint,
        json={
            "agent_name": f"agent_{uuid4()}",
            "agent_type": agent_type,
            "language_model_id": llm["id"],
        },
    )

    if agent_type in RAG_AGENT_TYPES:
        update_agent_setting(
            agent_id=agent["id"],
            setting_key="collection_name",
            setting_value=rag_collection,
            agent_lab_endpoint=agent_lab_endpoint,
        )

    return agent


def _create_hosted_agent(
    integration_type: str,
    api_endpoint: str,
    llm_tag: str,
    agent_type: str,
    agent_lab_endpoint: str,
    api_key: str,
) -> dict:
    return create_agent_with_integration(
        llm_tag,
        agent_type,
        {
            "integration_type": integration_type,
            "api_endpoint": api_endpoint,
            "api_key": api_key,
        },
        agent_lab_endpoint,
    )


def create_local_agent(
    llm_tag: str = "phi4-mini:latest",
    agent_type: str = "test_echo",
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    local_endpoint: str = "http://localhost:11434/v1",
) -> dict:
    # local openai-compatible server (e.g. ollama) mocking the openai api
    return create_agent_with_integration(
        llm_tag,
        agent_type,
        {
            "integration_type": "openai_api_v1",
            "api_endpoint": local_endpoint,
            "api_key": "ollama",
        },
        agent_lab_endpoint,
        embeddings_tag=DEFAULT_EMBEDDINGS_TAG,
    )


def create_openai_agent(
    llm_tag: str = "gpt-5-nano",
    agent_type: str = "test_echo",
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    api_key: str = "",
) -> dict:
    return _create_hosted_agent(
        "openai_api_v1",
        "https://api.openai.com/v1/",
        llm_tag,
        agent_type,
        agent_lab_endpoint,
        api_key,
    )


def create_xai_agent(
    llm_tag: str = "grok-4.5",
    agent_type: str = "test_echo",
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    api_key: str = "",
) -> dict:
    return _create_hosted_agent(
        "xai_api_v1",
        "https://api.x.ai/v1/",
        llm_tag,
        agent_type,
        agent_lab_endpoint,
        api_key,
    )


def create_anthropic_agent(
    llm_tag: str = "claude-haiku-4-5-20251001",
    agent_type: str = "test_echo",
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
    api_key: str = "",
) -> dict:
    return _create_hosted_agent(
        "anthropic_api_v1",
        "https://api.anthropic.com",
        llm_tag,
        agent_type,
        agent_lab_endpoint,
        api_key,
    )


def create_attachment(
    file_path: str,
    content_type: str,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
) -> str:
    with open(file_path, "rb") as file:
        attachment = _post(
            "/attachments/upload",
            agent_lab_endpoint,
            files={"file": (file_path, file, content_type)},
        )
    return attachment["id"]


def create_embeddings(
    attachment_id: str,
    language_model_id: str,
    collection_name: str,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
) -> dict:
    return _post(
        "/attachments/embeddings",
        agent_lab_endpoint,
        json={
            "attachment_id": attachment_id,
            "language_model_id": language_model_id,
            "collection_name": collection_name,
        },
    )


def update_agent_setting(
    agent_id: str,
    setting_key: str,
    setting_value: str,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
) -> dict:
    return _post(
        "/agents/update_setting",
        agent_lab_endpoint,
        json={
            "agent_id": agent_id,
            "setting_key": setting_key,
            "setting_value": setting_value,
        },
    )


def update_language_model_setting(
    language_model_id: str,
    setting_key: str,
    setting_value: str,
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
) -> dict:
    return _post(
        "/llms/update_setting",
        agent_lab_endpoint,
        json={
            "language_model_id": language_model_id,
            "setting_key": setting_key,
            "setting_value": setting_value,
        },
    )


def enable_jev(
    agent_id: str,
    api_key: str,
    api_endpoint: str = "https://api.typesafe.ai",
    agent_lab_endpoint: str = DEFAULT_AGENT_LAB_ENDPOINT,
) -> dict:
    # route the agent's grading decisions through a typesafe_api_v1 integration
    integration = _post(
        "/integrations/create",
        agent_lab_endpoint,
        json={
            "integration_type": "typesafe_api_v1",
            "api_endpoint": api_endpoint,
            "api_key": api_key,
        },
    )
    update_agent_setting(agent_id, "decision_engine", "jev", agent_lab_endpoint)
    update_agent_setting(
        agent_id, "jev_integration_id", integration["id"], agent_lab_endpoint
    )
    return integration


def openai_responses_api_mcp_tool_request(
    query: str,
    mcp_server: dict,
    model: str = "gpt-5-nano",
    reasoning: dict | None = None,
) -> dict:
    if reasoning is None:
        reasoning = {"effort": "low", "summary": "auto"}

    response = requests.post(
        url="https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "tools": [mcp_server],
            "reasoning": reasoning,
            "input": query,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
