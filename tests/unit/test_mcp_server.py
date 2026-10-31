import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_lab.interface.mcp.coordinator_planner_supervisor_tool_registrar import (
    CoordinatorPlannerSupervisorToolRegistrar,
)
from agent_lab.interface.mcp.schema import (
    AgentItem,
    MessageItem,
    PostMessageResult,
    _get_mcp_schema,
)
from agent_lab.interface.mcp.server import _build_auth, build_mcp_server
from agent_lab.interface.mcp.registrar import McpRegistrar
from agent_lab.interface.mcp.default_tool_registrar import (
    DefaultToolRegistrar,
    get_agent_list,
    get_message_list,
    post_message,
)
from agent_lab.interface.mcp.prompt_registry import PromptRegistry
from agent_lab.interface.mcp.user_prompt_resolver import UserPromptResolver


class TestMcpModels:
    def test_agent_item(self):
        item = AgentItem(
            id="a1",
            agent_name="Test Agent",
            agent_type="test_echo",
            agent_summary="An echo agent",
            language_model_id="lm1",
            is_active=True,
        )
        assert item.id == "a1"
        assert item.agent_name == "Test Agent"
        assert item.agent_type == "test_echo"
        assert item.is_active is True

    def test_message_item(self):
        item = MessageItem(
            id="m1",
            message_role="human",
            message_content="Hello",
            agent_id="a1",
        )
        assert item.id == "m1"
        assert item.response_data is None
        assert item.replies_to is None

    def test_message_item_with_optional_fields(self):
        item = MessageItem(
            id="m1",
            message_role="assistant",
            message_content="Hi there",
            agent_id="a1",
            response_data='{"key": "value"}',
            replies_to="m0",
        )
        assert item.response_data == '{"key": "value"}'
        assert item.replies_to == "m0"

    def test_post_message_result(self):
        result = PostMessageResult(
            id="m2",
            message_content="Response text",
            agent_id="a1",
        )
        assert result.id == "m2"
        assert result.response_data is None

    def test_post_message_result_with_response_data(self):
        result = PostMessageResult(
            id="m2",
            message_content="Response text",
            agent_id="a1",
            response_data="data",
        )
        assert result.response_data == "data"


class TestBuildAuth:
    def test_build_auth_disabled(self):
        config = {"auth": {"enabled": False}}
        result = _build_auth(config)
        assert result is None

    @patch("key_value.aio.wrappers.encryption.FernetEncryptionWrapper")
    @patch("key_value.aio.stores.redis.RedisStore")
    @patch("fastmcp.server.auth.providers.jwt.JWTVerifier")
    @patch("fastmcp.server.auth.OAuthProxy")
    def test_build_auth_enabled(
        self, mock_oauth, mock_jwt, mock_redis_store, mock_fernet_wrapper
    ):
        config = {
            "auth": {
                "enabled": True,
                "url": "http://keycloak:8080",
                "realm": "test-realm",
                "client_id": "test-client",
                "client_secret": "test-secret",
            },
            "broker": {"url": "redis://localhost:6379"},
            "api_base_url": "http://localhost:8000",
        }

        _build_auth(config)

        mock_jwt.assert_called_once()
        mock_oauth.assert_called_once()
        mock_redis_store.assert_called_once_with(url="redis://localhost:6379")
        mock_fernet_wrapper.assert_called_once()
        wrapper_kwargs = mock_fernet_wrapper.call_args[1]
        assert wrapper_kwargs["key_value"] is mock_redis_store.return_value
        assert wrapper_kwargs["raise_on_decryption_error"] is False
        call_kwargs = mock_oauth.call_args[1]
        assert "test-realm" in call_kwargs["upstream_authorization_endpoint"]
        assert "test-realm" in call_kwargs["upstream_token_endpoint"]
        assert call_kwargs["upstream_client_id"] == "test-client"
        assert call_kwargs["base_url"] == "http://localhost:8000/mcp"
        assert call_kwargs["client_storage"] is mock_fernet_wrapper.return_value


class TestBuildMcpServer:
    def test_server_icon_points_at_branding_logo(self):
        container = MagicMock()
        container.config.return_value = {
            "auth": {"enabled": False},
            "api_base_url": "http://localhost:8000",
        }

        mcp = build_mcp_server(container, [])

        assert mcp.icons[0].src == "http://localhost:8000/static/logo.svg"
        assert mcp.icons[0].mime_type == "image/svg+xml"


class TestGetMcpSchema:
    @patch("agent_lab.interface.mcp.schema.get_access_token", return_value=None)
    def test_get_mcp_schema_no_token(self, mock_token):
        result = _get_mcp_schema()
        assert result == "public"

    @patch("agent_lab.interface.mcp.schema.get_access_token")
    def test_get_mcp_schema_with_token(self, mock_token):
        mock_token.return_value = MagicMock(claims={"sub": "abc-def-123"})
        result = _get_mcp_schema()
        assert result == "id_abc_def_123"

    @patch("agent_lab.interface.mcp.schema.get_access_token")
    def test_get_mcp_schema_token_no_sub(self, mock_token):
        mock_token.return_value = MagicMock(claims={})
        result = _get_mcp_schema()
        assert result == "public"


class TestMcpRegistrar:
    def test_base_registrar_no_ops(self):
        class NoOpRegistrar(McpRegistrar):
            pass

        registrar = NoOpRegistrar()
        mcp = MagicMock()
        container = MagicMock()
        registrar.register_tools(mcp, container)
        registrar.register_prompts(mcp)
        registrar.register_resources(mcp)

    def test_default_tool_registrar_is_mcp_registrar(self):
        assert issubclass(DefaultToolRegistrar, McpRegistrar)

    def test_default_tool_registrar_registers_tools(self):
        registrar = DefaultToolRegistrar(prompt_registry=PromptRegistry())
        mcp = MagicMock()
        container = MagicMock()
        registrar.register_tools(mcp, container)
        tool_names = sorted(call[1]["name"] for call in mcp.tool.call_args_list)
        assert tool_names == ["read_prompt_mcp"]

    def test_custom_registrar_overrides(self):
        class CustomRegistrar(McpRegistrar):
            def register_prompts(self, mcp):
                mcp.prompt(name="test_prompt")(lambda: "test")

        registrar = CustomRegistrar()
        mcp = MagicMock()
        container = MagicMock()
        registrar.register_prompts(mcp)
        mcp.prompt.assert_called_once_with(name="test_prompt")
        registrar.register_tools(mcp, container)
        registrar.register_resources(mcp)


def _read_prompt_mcp_fn(container, prompt_registry=None):
    """Register DefaultToolRegistrar's tools against a mock FastMCP and return
    the captured read_prompt_mcp coroutine."""
    mcp = MagicMock()
    DefaultToolRegistrar(
        prompt_registry=prompt_registry or PromptRegistry()
    ).register_tools(mcp, container)
    return mcp.tool.return_value.call_args.args[0]


@patch(
    "agent_lab.interface.mcp.default_tool_registrar._get_mcp_schema",
    return_value="test",
)
class TestDefaultTools:
    @pytest.mark.asyncio
    async def test_get_agent_list(self, _schema):
        container = MagicMock()
        container.agent_service.return_value.get_agents.return_value = [
            MagicMock(
                id="a1",
                agent_name="Echo",
                agent_type="test_echo",
                agent_summary="echoes",
                language_model_id="lm1",
                is_active=True,
            )
        ]

        result = await get_agent_list(container)

        assert len(result) == 1
        assert result[0].id == "a1"
        assert result[0].agent_type == "test_echo"
        container.agent_service.return_value.get_agents.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_get_message_list(self, _schema):
        container = MagicMock()
        container.message_service.return_value.get_messages.return_value = [
            MagicMock(
                id="m1",
                message_role="human",
                message_content="hi",
                agent_id="a1",
                response_data=None,
                replies_to=None,
            )
        ]

        result = await get_message_list(container, "a1")

        assert len(result) == 1
        assert result[0].message_content == "hi"
        container.message_service.return_value.get_messages.assert_called_once_with(
            "a1", "test"
        )

    @pytest.mark.asyncio
    async def test_post_message(self, _schema):
        container = MagicMock()
        agent = MagicMock(agent_type="test_echo")
        container.agent_service.return_value.get_agent_by_id.return_value = agent
        matching_agent = container.agent_registry.return_value.get_agent.return_value
        matching_agent.process_message.return_value = MagicMock(
            message_content="echo: hi", response_data=None, agent_id="a1"
        )
        human_message = MagicMock(id="m1")
        assistant_message = MagicMock(
            id="m2", message_content="echo: hi", agent_id="a1", response_data=None
        )
        message_service = container.message_service.return_value
        message_service.create_message.side_effect = [human_message, assistant_message]

        result = await post_message(container, "a1", "hi")

        assert result.id == "m2"
        assert result.message_content == "echo: hi"
        assert message_service.create_message.call_count == 2
        assert (
            message_service.create_message.call_args_list[1].kwargs["replies_to"]
            is human_message
        )
        matching_agent.process_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_message_runs_agent_off_the_event_loop(self, _schema):
        import threading

        container = MagicMock()
        container.agent_service.return_value.get_agent_by_id.return_value = MagicMock(
            agent_type="test_echo"
        )
        matching_agent = container.agent_registry.return_value.get_agent.return_value
        threads = []

        def process_message(*_args):
            threads.append(threading.current_thread())
            return MagicMock(message_content="ok", response_data=None, agent_id="a1")

        matching_agent.process_message.side_effect = process_message
        container.message_service.return_value.create_message.side_effect = [
            MagicMock(id="m1"),
            MagicMock(id="m2", message_content="ok", agent_id="a1", response_data=None),
        ]

        await post_message(container, "a1", "hi")

        assert threads and threads[0] is not threading.current_thread()


class TestReadPromptMcp:
    @pytest.mark.asyncio
    async def test_resolves_registered_prompt(self):
        registry = PromptRegistry()
        registry.register("sample_prompt", lambda: "PROMPT_TEXT")

        result = await _read_prompt_mcp_fn(MagicMock(), registry)("sample_prompt")

        assert result == "PROMPT_TEXT"

    @pytest.mark.asyncio
    async def test_unknown_prompt_raises_value_error_with_available_names(self):
        registry = PromptRegistry()
        registry.register("known_prompt", lambda: "")

        with pytest.raises(ValueError, match="known_prompt"):
            await _read_prompt_mcp_fn(MagicMock(), registry)("unknown_prompt")

    def test_description_lists_registered_prompt_names(self):
        registry = PromptRegistry()
        registry.register("alpha_prompt", lambda: "")
        mcp = MagicMock()

        DefaultToolRegistrar(prompt_registry=registry).register_tools(mcp, MagicMock())

        read_prompt_call = next(
            call
            for call in mcp.tool.call_args_list
            if call.kwargs["name"] == "read_prompt_mcp"
        )
        assert "alpha_prompt" in read_prompt_call.kwargs["description"]

    def test_description_with_empty_registry(self):
        mcp = MagicMock()

        DefaultToolRegistrar(prompt_registry=PromptRegistry()).register_tools(
            mcp, MagicMock()
        )

        read_prompt_call = next(
            call
            for call in mcp.tool.call_args_list
            if call.kwargs["name"] == "read_prompt_mcp"
        )
        assert "<none currently registered>" in read_prompt_call.kwargs["description"]

    @pytest.mark.asyncio
    async def test_parameters_are_forwarded_to_resolver(self):
        registry = PromptRegistry()
        captured: dict = {}

        def resolver(**params):
            captured.update(params)
            return "ok"

        registry.register("sample_prompt", resolver)

        result = await _read_prompt_mcp_fn(MagicMock(), registry)(
            "sample_prompt", parameters={"deep_search_mode": "true"}
        )

        assert result == "ok"
        assert captured == {"deep_search_mode": "true"}


class TestGlobalPromptResource:
    def _resource_fn(self, registry):
        mcp = MagicMock()
        DefaultToolRegistrar(prompt_registry=registry).register_resources(mcp)
        call = mcp.resource.call_args
        assert call.kwargs["uri"] == "prompt://{name}{?parameters}"
        assert call.kwargs["mime_type"] == "text/plain"
        return mcp.resource.return_value.call_args.args[0]

    def test_resolves_prompt_with_json_parameters(self):
        registry = PromptRegistry()
        captured: dict = {}

        def resolver(**params):
            captured.update(params)
            return "resolved-text"

        registry.register("sample_prompt", resolver)
        read_prompt = self._resource_fn(registry)

        result = read_prompt(
            "sample_prompt", parameters=json.dumps({"current_time": "T"})
        )

        assert result == "resolved-text"
        assert captured == {"current_time": "T"}

    def test_resolves_prompt_without_parameters(self):
        registry = PromptRegistry()
        registry.register("sample_prompt", lambda **_: "default-text")
        read_prompt = self._resource_fn(registry)
        assert read_prompt("sample_prompt") == "default-text"

    def test_unknown_name_raises_value_error(self):
        registry = PromptRegistry()
        registry.register("known_prompt", lambda **_: "")
        read_prompt = self._resource_fn(registry)
        with pytest.raises(ValueError, match="known_prompt"):
            read_prompt("unknown_prompt")


class TestPromptTenancy:
    """End-to-end tenancy through the real UserPromptResolver: the access
    token's schema decides between the tenant's stored override and the
    packaged default template, on every prompt surface."""

    def _registry(self, agents=None, settings=None):
        agent_service = MagicMock()
        setting_service = MagicMock()
        agent_service.get_agents.return_value = agents or []
        setting_service.get_agent_settings.return_value = settings or []
        registry = PromptRegistry()
        CoordinatorPlannerSupervisorToolRegistrar(
            user_prompt_resolver=UserPromptResolver(agent_service, setting_service),
            prompt_registry=registry,
        )
        return registry

    @patch(
        "agent_lab.interface.mcp.user_prompt_resolver._get_mcp_schema",
        return_value="public",
    )
    def test_public_schema_serves_rendered_default(self, _schema):
        registry = self._registry()
        rendered = registry.resolve("coordinator_planner_supervisor_coordinator")
        assert rendered
        assert "{{" not in rendered

    @patch(
        "agent_lab.interface.mcp.user_prompt_resolver._get_mcp_schema",
        return_value="id_tenant",
    )
    def test_tenant_override_is_served_and_rendered(self, _schema):
        agent = SimpleNamespace(
            id="a1", agent_type="coordinator_planner_supervisor", is_active=True
        )
        setting = SimpleNamespace(
            setting_key="coordinator_system_prompt",
            setting_value="TENANT OVERRIDE {{ CURRENT_TIME }}",
        )
        registry = self._registry(agents=[agent], settings=[setting])
        rendered = registry.resolve("coordinator_planner_supervisor_coordinator")
        assert rendered.startswith("TENANT OVERRIDE ")
        assert "{{" not in rendered

    @patch(
        "agent_lab.interface.mcp.user_prompt_resolver._get_mcp_schema",
        return_value="id_tenant",
    )
    def test_tenant_override_honors_client_parameters(self, _schema):
        agent = SimpleNamespace(
            id="a1", agent_type="coordinator_planner_supervisor", is_active=True
        )
        setting = SimpleNamespace(
            setting_key="coordinator_system_prompt",
            setting_value="TENANT {{ CURRENT_TIME }}",
        )
        registry = self._registry(agents=[agent], settings=[setting])
        rendered = registry.resolve(
            "coordinator_planner_supervisor_coordinator",
            current_time="Mon Jan 05 2026 09:00:00",
        )
        assert rendered == "TENANT Mon Jan 05 2026 09:00:00"
