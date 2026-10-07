from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_xai import ChatXAI
from langgraph.constants import END
from openai import OpenAI

from agent_lab.domain.exceptions.base import ConfigurationError, ResourceNotFoundError
from agent_lab.interface.api.messages.schema import Message, MessageRequest
from agent_lab.services.agent_types.adaptive_rag.agent import AdaptiveRagAgent
from agent_lab.services.agent_types.azure import AzureEntraIdOrganizationWorkflowBase
from agent_lab.services.agent_types.base import (
    AgentUtils,
    ContactSupportAgentBase,
    WorkflowAgentBase,
    join_messages,
)
from agent_lab.services.agent_types.business.voice_memos.agent import (
    AzureEntraIdVoiceMemosAgent,
    FastVoiceMemosAgent,
    VoiceMemosAgent,
)
from agent_lab.services.agent_types.coordinator_planner_supervisor.agent import (
    CoordinatorPlannerSupervisorAgent,
)
from agent_lab.services.agent_types.react_rag.agent import ReactRagAgent
from agent_lab.services.agent_types.test_echo.test_echo_agent import (
    TestEchoAgent as EchoAgent,
)
from agent_lab.services.agent_types.vision_document.agent import VisionDocumentAgent


def _make_agent(integration_type: str) -> EchoAgent:
    agent = EchoAgent(agent_utils=MagicMock())
    agent.agent_service = MagicMock()
    integration = MagicMock()
    integration.integration_type = integration_type
    agent.get_language_model_integration = MagicMock(
        return_value=(MagicMock(), integration)
    )
    agent.get_integration_credentials = MagicMock(
        return_value=("https://example.com", "api-key")
    )
    return agent


def _setting(key: str, value: str) -> MagicMock:
    return MagicMock(setting_key=key, setting_value=value)


def _message_request(attachment_id=None) -> MessageRequest:
    return MessageRequest(
        message_role="human",
        message_content="what is the answer?",
        agent_id="agent-1",
        attachment_id=attachment_id,
    )


class TestGetChatModel:
    def test_openai_integration_returns_chat_openai(self):
        agent = _make_agent("openai_api_v1")

        chat_model = agent.get_chat_model("agent-1", "test", "gpt-4o")

        assert isinstance(chat_model, ChatOpenAI)

    def test_xai_integration_returns_chat_xai(self):
        agent = _make_agent("xai_api_v1")

        chat_model = agent.get_chat_model("agent-1", "test", "grok-2")

        assert isinstance(chat_model, ChatXAI)

    def test_anthropic_integration_returns_chat_anthropic(self):
        agent = _make_agent("anthropic_api_v1")

        chat_model = agent.get_chat_model("agent-1", "test", "claude-sonnet-5")

        assert isinstance(chat_model, ChatAnthropic)

    def test_default_tag_comes_from_language_model(self):
        agent = _make_agent("openai_api_v1")
        language_model = MagicMock()
        language_model.language_model_tag = "gpt-4o-mini"
        integration = MagicMock()
        integration.integration_type = "openai_api_v1"
        agent.get_language_model_integration = MagicMock(
            return_value=(language_model, integration)
        )

        chat_model = agent.get_chat_model("agent-1", "test")

        assert chat_model.model_name == "gpt-4o-mini"

    def test_guardrail_settings_applied(self):
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("max_tokens", "8192"),
            _setting("timeout", "600"),
        ]

        chat_model = agent.get_chat_model("agent-1", "test", "gpt-4o")

        assert chat_model.max_tokens == 8192
        assert chat_model.request_timeout == pytest.approx(600.0)

    @patch.object(ChatOpenAI, "with_structured_output")
    def test_structured_output_method_setting_applied(self, parent_method):
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("structured_output_method", "function_calling"),
        ]

        agent.get_chat_model("agent-1", "test", "gpt-oss:20b").with_structured_output(
            dict
        )

        parent_method.assert_called_once_with(dict, method="function_calling")

    @patch.object(ChatOpenAI, "with_structured_output")
    def test_structured_output_explicit_method_wins(self, parent_method):
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("structured_output_method", "function_calling"),
        ]

        agent.get_chat_model("agent-1", "test", "gpt-oss:20b").with_structured_output(
            dict, method="json_mode"
        )

        parent_method.assert_called_once_with(dict, method="json_mode")

    @patch.object(ChatOpenAI, "with_structured_output")
    def test_structured_output_default_setting_keeps_default(self, parent_method):
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("structured_output_method", "default"),
        ]

        agent.get_chat_model("agent-1", "test", "gpt-4o").with_structured_output(dict)

        parent_method.assert_called_once_with(dict)

    @patch.object(ChatOpenAI, "with_structured_output")
    def test_structured_output_without_setting_keeps_default(self, parent_method):
        agent = _make_agent("openai_api_v1")

        agent.get_chat_model("agent-1", "test", "gpt-4o").with_structured_output(dict)

        # no method passed: the library default applies
        parent_method.assert_called_once_with(dict)

    def test_unsupported_integration_type_raises(self):
        agent = _make_agent("ollama_api_v1")

        with pytest.raises(ConfigurationError):
            agent.get_chat_model("agent-1", "test", "some-model")


class TestDecisionPrimitives:
    JEV_STATE = {
        "agent_id": "agent-1",
        "schema": "test",
        "decision_engine": "jev",
        "jev_integration_id": "jev-int",
    }
    LLM_STATE = {"agent_id": "agent-1", "schema": "test", "decision_engine": "llm"}

    def _agent(self):
        agent = _make_agent("openai_api_v1")
        agent.integration_service = MagicMock()
        return agent

    @staticmethod
    def _jev_answer(client_cls, **fields):
        client = client_cls.return_value.__enter__.return_value
        client.system_one.return_value = MagicMock(
            answers={"decision": MagicMock(**fields)}
        )
        return client

    @pytest.mark.parametrize("noul, expected", [(0.5, True), (0.49, False)])
    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_is_yes_with_jev_uses_threshold(self, client_cls, noul, expected):
        agent = self._agent()
        client = self._jev_answer(client_cls, noul=noul)

        assert agent.is_yes(self.JEV_STATE, "grade", {"query": "q"}) is expected

        agent.integration_service.get_integration_by_id.assert_called_once_with(
            "jev-int", "test"
        )
        client_cls.assert_called_once_with(
            api_key="api-key", base_url="https://example.com"
        )
        call = client.system_one.call_args.kwargs
        assert call["state"] == {"query": "q"}
        assert call["questions"]["decision"].instructions == "grade"

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_is_yes_with_llm_engine_never_calls_jev(self, client_cls):
        agent = self._agent()
        agent._ask_llm = MagicMock(return_value={"binary_score": "yes"})

        assert agent.is_yes(self.LLM_STATE, "grade", {"query": "q"}) is True
        client_cls.assert_not_called()

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_jev_engine_without_integration_uses_llm_silently(self, client_cls):
        agent = self._agent()
        agent.logger = MagicMock()
        agent._ask_llm = MagicMock(return_value={"binary_score": "no"})
        state = {**self.JEV_STATE, "jev_integration_id": ""}

        assert agent.is_yes(state, "grade", {"query": "q"}) is False
        client_cls.assert_not_called()
        agent.logger.warning.assert_not_called()

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_jev_failure_falls_back_to_llm(self, client_cls):
        agent = self._agent()
        agent.logger = MagicMock()
        client_cls.return_value.__enter__.return_value.system_one.side_effect = (
            RuntimeError("jev unavailable")
        )
        agent._ask_llm = MagicMock(return_value={"binary_score": "yes"})

        assert agent.is_yes(self.JEV_STATE, "grade", {"query": "q"}) is True
        agent.logger.warning.assert_called_once()
        assert "JEV decision failed" in agent.logger.warning.call_args.args[0]

    def test_is_yes_llm_none_is_no(self):
        agent = self._agent()
        agent._ask_llm = MagicMock(return_value=None)

        assert agent.is_yes(self.LLM_STATE, "grade", {"query": "q"}) is False

    def test_ask_llm_renders_context_and_keeps_braces(self):
        agent = self._agent()
        captured = {}

        def fake_model(prompt_value):
            captured["messages"] = prompt_value.to_messages()
            return {"binary_score": "yes"}

        model = MagicMock()
        model.with_structured_output.return_value = RunnableLambda(fake_model)
        agent.get_chat_model = MagicMock(return_value=model)

        assert agent.is_yes(
            self.LLM_STATE,
            'reply as {"next": "x"}',
            {"document": "d", "query": "q"},
        )
        assert captured["messages"][0].content == 'reply as {"next": "x"}'
        assert (
            captured["messages"][1].content
            == "<document>d</document>\n<query>q</query>"
        )

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_choose_with_jev(self, client_cls):
        agent = self._agent()
        client = self._jev_answer(client_cls, choice="coder")
        options = {"researcher": "finds facts", "coder": "runs code"}

        result = agent.choose(self.JEV_STATE, "route", options, {"q": "x"}, "__end__")

        assert result == "coder"
        question = client.system_one.call_args.kwargs["questions"]["decision"]
        assert question.criteria == options
        assert question.instructions == "route"

    def test_choose_with_llm_constrains_labels(self):
        agent = self._agent()
        agent._ask_llm = MagicMock(return_value={"choice": "researcher"})
        options = {"researcher": "finds facts", "coder": "runs code"}

        result = agent.choose(self.LLM_STATE, "route", options, {"q": "x"}, "__end__")

        assert result == "researcher"
        output_schema = agent._ask_llm.call_args.args[3]
        assert output_schema["properties"]["choice"]["enum"] == ["researcher", "coder"]

    @pytest.mark.parametrize("llm_output", [None, {"choice": "painter"}])
    def test_choose_invalid_llm_label_returns_fallback(self, llm_output):
        agent = self._agent()
        agent.logger = MagicMock()
        agent._ask_llm = MagicMock(return_value=llm_output)

        result = agent.choose(
            self.LLM_STATE, "route", {"researcher": "finds facts"}, {}, "__end__"
        )

        assert result == "__end__"
        agent.logger.warning.assert_called_once()

    def test_get_decision_params_defaults(self):
        agent = self._agent()

        assert agent.get_decision_params({}) == {
            "decision_engine": "llm",
            "jev_integration_id": "",
        }
        assert agent.get_decision_params(
            {"decision_engine": "jev", "jev_integration_id": "i"}
        ) == {"decision_engine": "jev", "jev_integration_id": "i"}

    def test_create_decision_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_decision_settings("agent-1", "test")

        calls = agent.agent_setting_service.create_agent_setting.call_args_list
        assert [c.kwargs["setting_key"] for c in calls] == [
            "decision_engine",
            "jev_integration_id",
        ]
        assert calls[0].kwargs["setting_value"] == "llm"
        assert calls[1].kwargs["setting_value"] == ""


class TestJoinMessages:
    def test_join_lists_removes_duplicates(self):
        assert join_messages(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_join_wraps_scalars(self):
        assert join_messages("a", "b") == ["a", "b"]


class TestAgentUtils:
    def test_constructor_assigns_dependencies(self):
        deps = {
            name: MagicMock()
            for name in (
                "agent_service",
                "agent_setting_service",
                "attachment_service",
                "language_model_service",
                "language_model_setting_service",
                "integration_service",
                "vault_client",
                "graph_persistence_factory",
                "document_repository",
                "task_notification_service",
                "config",
            )
        }

        utils = AgentUtils(**deps)

        for name, dep in deps.items():
            assert getattr(utils, name) is dep


class TestAgentBaseHelpers:
    def test_format_response_returns_last_message_content(self):
        agent = _make_agent("openai_api_v1")
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}

        content, response_data = agent.format_response(state)

        assert content == "hello"
        assert len(response_data["messages"]) == 2

    def test_get_language_model_integration(self):
        agent = EchoAgent(agent_utils=MagicMock())
        language_model = MagicMock()
        language_model.integration_id = "int-1"
        agent.language_model_service.get_language_model_by_id.return_value = (
            language_model
        )
        integration = MagicMock()
        agent.integration_service.get_integration_by_id.return_value = integration
        agent_record = MagicMock()
        agent_record.language_model_id = "lm-1"

        result = agent.get_language_model_integration(agent_record, "test")

        assert result == (language_model, integration)
        agent.language_model_service.get_language_model_by_id.assert_called_once_with(
            "lm-1", "test"
        )
        agent.integration_service.get_integration_by_id.assert_called_once_with(
            "int-1", "test"
        )

    def test_get_integration_credentials_reads_vault(self):
        agent = EchoAgent(agent_utils=MagicMock())
        integration = MagicMock()
        integration.id = "int-1"
        agent.vault_client.secrets.kv.read_secret_version.return_value = {
            "data": {"data": {"api_endpoint": "http://e", "api_key": "k"}}
        }

        endpoint, key = agent.get_integration_credentials(integration)

        assert (endpoint, key) == ("http://e", "k")
        agent.vault_client.secrets.kv.read_secret_version.assert_called_once_with(
            path="integration_int-1", raise_on_deleted_version=False
        )

    def test_get_embeddings_model(self, monkeypatch):
        monkeypatch.setenv("EMBEDDINGS_ENDPOINT", "http://embeddings:1234/v1")
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("embeddings", "bge-m3")
        ]

        embeddings = agent.get_embeddings_model("agent-1", "test")

        assert isinstance(embeddings, OpenAIEmbeddings)
        assert embeddings.openai_api_base == "http://embeddings:1234/v1"

    def test_get_embeddings_model_without_env_override(self, monkeypatch):
        monkeypatch.delenv("EMBEDDINGS_ENDPOINT", raising=False)
        agent = _make_agent("openai_api_v1")
        agent.language_model_setting_service.get_language_model_settings.return_value = [
            _setting("embeddings", "bge-m3")
        ]

        embeddings = agent.get_embeddings_model("agent-1", "test")

        assert embeddings.openai_api_base == "https://example.com"

    def test_get_openai_client(self):
        agent = _make_agent("openai_api_v1")

        client = agent.get_openai_client("agent-1", "test")

        assert isinstance(client, OpenAI)
        assert client.api_key == "api-key"

    def test_read_file_content(self, tmp_path):
        agent = EchoAgent(agent_utils=MagicMock())
        file_path = tmp_path / "prompt.txt"
        file_path.write_text("  content  \n")

        assert agent.read_file_content(str(file_path)) == "content"

    def test_read_file_content_missing_raises(self):
        agent = EchoAgent(agent_utils=MagicMock())

        with pytest.raises(ResourceNotFoundError):
            agent.read_file_content("/nonexistent/file.txt")

    def test_parse_prompt_template(self):
        agent = EchoAgent(agent_utils=MagicMock())
        settings_dict = {"prompt": "Hello {{ NAME }}!"}

        rendered = agent.parse_prompt_template(settings_dict, "prompt", {"NAME": "Bob"})

        assert rendered == "Hello Bob!"


class _StubWorkflowAgent(WorkflowAgentBase):
    def create_default_settings(self, agent_id: str, schema: str):
        """Not needed for these tests."""

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        return {"messages": []}

    def get_workflow_builder(self, agent_id: str):
        """Not needed for these tests."""


class TestWorkflowAgentBase:
    def _agent(self) -> _StubWorkflowAgent:
        return _StubWorkflowAgent(agent_utils=MagicMock())

    def test_get_config(self):
        config = self._agent().get_config("agent-1")

        assert config["configurable"]["thread_id"] == "agent-1"
        assert config["recursion_limit"] == 30

    def test_create_thought_chain_without_llm(self):
        chain = self._agent().create_thought_chain(
            human_input="hi", ai_response="hello", connection="greeting"
        )

        assert "hi" in chain
        assert "hello" in chain
        assert "Connection: greeting" in chain

    def test_create_thought_chain_with_llm_summarizes(self):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="summary")

        chain = self._agent().create_thought_chain(
            human_input="hi", ai_response="a long response", llm=llm
        )

        assert "summary" in chain
        llm.invoke.assert_called_once()

    def test_process_message(self):
        agent = self._agent()
        workflow = MagicMock()
        workflow.invoke.return_value = {
            "messages": [HumanMessage(content="q"), AIMessage(content="answer")]
        }
        builder = MagicMock()
        builder.compile.return_value = workflow
        agent.get_workflow_builder = MagicMock(return_value=builder)

        message = agent.process_message(_message_request(), "test")

        assert isinstance(message, Message)
        assert message.message_content == "answer"
        assert message.agent_id == "agent-1"
        assert agent.task_notification_service.publish_update.call_count == 2
        agent.graph_persistence_factory.build_checkpoint_saver.assert_called_once()

    def test_get_image_analysis_chain(self):
        llm = RunnableLambda(lambda _: AIMessage(content="analysis"))

        chain = self._agent().get_image_analysis_chain(llm, "system", "image/png")
        result = chain.invoke({"query": "what is it?", "image_base64": "aWJhc2U="})

        assert result.content == "analysis"

    def test_get_last_interaction_messages(self):
        messages = [
            HumanMessage(content="first"),
            AIMessage(content="a"),
            HumanMessage(content="second"),
            AIMessage(content="b"),
        ]

        result = self._agent().get_last_interaction_messages(messages)

        assert result == messages[2:]

    def test_get_last_interaction_messages_no_human(self):
        assert (
            self._agent().get_last_interaction_messages([AIMessage(content="a")]) == []
        )


class TestShellAnalysis:
    def test_classify_shell_token(self):
        classify = WorkflowAgentBase._classify_shell_token
        ops = WorkflowAgentBase._REDIRECT_OPS
        assert classify("|", ops) == "pipe"
        assert classify(";", ops) == "separator"
        assert classify(">", ops) == "redirection"
        assert classify("VAR=1", ops) == "variable"
        assert classify("$(date)", ops) == "subshell"
        assert classify("ls", ops) == "command"
        assert classify("--flag=value", ops) == "command"

    def test_analyze_shell(self):
        result, error = WorkflowAgentBase._analyze_shell(
            "VAR=1 ls -la | grep foo > out.txt ; echo $(date)"
        )

        assert error is None
        assert result["pipes"] == 1
        assert result["redirections"] == [">"]
        assert result["variables"] == ["VAR"]
        assert result["subshells"] == 1
        assert len(result["commands"]) >= 2

    def test_analyze_shell_invalid(self):
        result, error = WorkflowAgentBase._analyze_shell('echo "unclosed')

        assert result is None
        assert error

    def test_bash_tool_valid_script(self):
        agent = _StubWorkflowAgent(agent_utils=MagicMock())
        tool = agent.get_bash_tool()

        output = tool.func("VAR=1 ls | grep foo > out.txt $(date)")

        assert "Syntax: valid" in output
        assert "Pipes: 1" in output
        assert "Redirections: >" in output
        assert "Variables: VAR" in output
        assert "Subshells: 1" in output

    def test_bash_tool_parse_error(self):
        agent = _StubWorkflowAgent(agent_utils=MagicMock())
        tool = agent.get_bash_tool()

        output = tool.func('echo "unclosed')

        assert "Parse error" in output

    def test_bash_tool_non_string_input(self):
        agent = _StubWorkflowAgent(agent_utils=MagicMock())
        tool = agent.get_bash_tool()

        output = tool.func(123)

        assert "Invalid input" in output


class _StubContactAgent(ContactSupportAgentBase):
    def create_default_settings(self, agent_id: str, schema: str):
        """Not needed for these tests."""

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        return {}

    def get_workflow_builder(self, agent_id: str):
        """Not needed for these tests."""

    def get_person_search_tool(self):
        """Not needed for these tests."""

    def get_person_details_tool(self):
        """Not needed for these tests."""


class TestIcalAttachmentTool:
    def test_creates_event_with_attendees(self):
        agent = _StubContactAgent(agent_utils=MagicMock())
        agent.base_url = "http://base"
        tool = agent.get_ical_attachment_tool()

        url = tool.func(
            event_name="Meeting",
            event_description="Sync",
            event_start_datetime=datetime(2026, 7, 13, 10, 0),
            event_duration_minutes=30,
            event_attendees=["Bob <bob@example.com>"],
        )

        assert url.startswith("http://base/attachments/download/")
        create_call = agent.attachment_service.create_attachment_with_content.call_args
        assert b"METHOD:REQUEST" in create_call.kwargs["raw_content"]
        assert "Meeting" in create_call.kwargs["parsed_content"]
        assert create_call.kwargs["schema"] == "public"

    def test_creates_event_without_attendees(self):
        agent = _StubContactAgent(agent_utils=MagicMock())
        agent.base_url = "http://base"
        tool = agent.get_ical_attachment_tool()

        tool.func(
            event_name="Solo",
            event_description="Focus",
            event_start_datetime=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
            event_duration_minutes=15,
            event_attendees=[],
        )

        create_call = agent.attachment_service.create_attachment_with_content.call_args
        assert b"METHOD:PUBLISH" in create_call.kwargs["raw_content"]


class TestWebAgentBase:
    def _agent(self, integration_type: str) -> AdaptiveRagAgent:
        agent = AdaptiveRagAgent(agent_utils=MagicMock())
        agent.agent_service = MagicMock()
        language_model = MagicMock()
        language_model.language_model_tag = "gpt-4o"
        integration = MagicMock()
        integration.integration_type = integration_type
        agent.get_language_model_integration = MagicMock(
            return_value=(language_model, integration)
        )
        agent.get_integration_credentials = MagicMock(
            return_value=("https://example.com", "api-key")
        )
        return agent

    def test_get_browser_chat_model_openai(self):
        chat_model = self._agent("openai_api_v1").get_browser_chat_model(
            "agent-1", "test"
        )

        assert chat_model.model == "gpt-4o"

    def test_get_browser_chat_model_anthropic(self):
        chat_model = self._agent("anthropic_api_v1").get_browser_chat_model(
            "agent-1", "test", "claude-sonnet-5"
        )

        assert chat_model.model == "claude-sonnet-5"

    def test_get_browser_chat_model_unsupported_raises(self):
        agent = self._agent("ollama_api_v1")
        with pytest.raises(ConfigurationError):
            agent.get_browser_chat_model("agent-1", "test")

    def test_get_web_browser_tool_returns_tool(self):
        agent = self._agent("openai_api_v1")
        agent.get_browser_chat_model = MagicMock()

        tool = agent.get_web_browser_tool("agent-1", "test")

        assert tool.name == "browser_tool"
        agent.get_browser_chat_model.assert_called_once_with("agent-1", "test")

    @patch("agent_lab.services.agent_types.base.MarkItDown")
    def test_get_web_crawl_tool(self, markitdown_cls):
        markitdown_cls.return_value.convert.return_value.text_content = "content"
        agent = self._agent("openai_api_v1")

        output = agent.get_web_crawl_tool().func(urls=["http://a"])

        assert '"content": "content"' in output

    @patch("agent_lab.services.agent_types.base.MarkItDown")
    def test_get_web_crawl_tool_error(self, markitdown_cls):
        markitdown_cls.return_value.convert.side_effect = Exception("boom")
        agent = self._agent("openai_api_v1")

        output = agent.get_web_crawl_tool().func(urls=["http://a"])

        assert '"error": "boom"' in output

    def test_get_web_search_tool(self):
        tool = self._agent("openai_api_v1").get_web_search_tool()

        assert tool.name == "web_search"


class TestSupervisedWorkflowChains:
    def _agent(self) -> CoordinatorPlannerSupervisorAgent:
        return CoordinatorPlannerSupervisorAgent(agent_utils=MagicMock())

    def test_default_tool_lists(self):
        agent = self._agent()

        assert agent.get_coordinator_tools() == []
        assert agent.get_reporter_tools() == []
        assert len(agent.get_planner_tools()) == 2

    def test_get_planner_chain_without_search_results(self):
        llm = RunnableLambda(lambda _: AIMessage(content="plan"))

        result = self._agent().get_planner_chain(llm, "system").invoke({"query": "q"})

        assert result.content == "plan"

    def test_get_planner_chain_with_search_results(self):
        llm = RunnableLambda(lambda _: AIMessage(content="plan"))

        chain = self._agent().get_planner_chain(llm, "system", search_results="found")
        result = chain.invoke({"query": "q", "search_results": "found"})

        assert result.content == "plan"


class TestCoordinatorPlannerSupervisorAgent:
    def _agent(self) -> CoordinatorPlannerSupervisorAgent:
        return CoordinatorPlannerSupervisorAgent(agent_utils=MagicMock())

    def _state(self, **overrides) -> dict:
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "query": "what?",
            "collection_name": "kb",
            "coordinator_system_prompt": "coordinator",
            "planner_system_prompt": "planner",
            "supervisor_system_prompt": "supervisor",
            "researcher_system_prompt": "researcher",
            "coder_system_prompt": "coder",
            "browser_system_prompt": "browser",
            "reporter_system_prompt": "reporter",
            "deep_search_mode": False,
            "execution_plan": {"thought": "t"},
            "messages": [HumanMessage(content="what?")],
        }
        state.update(overrides)
        return state

    def test_format_response(self):
        state = self._state(messages=[AIMessage(content="done")])

        content, response_data = self._agent().format_response(state)

        assert content == "done"
        assert response_data["agent_id"] == "agent-1"
        assert response_data["collection_name"] == "kb"

    def test_create_default_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_default_settings("agent-1", "test")

        assert agent.agent_setting_service.create_agent_setting.call_count == 11

    def test_get_workflow_builder(self):
        builder = self._agent().get_workflow_builder("agent-1")

        assert {
            "coordinator",
            "planner",
            "supervisor",
            "researcher",
            "coder",
            "browser",
            "reporter",
        } <= set(builder.nodes.keys())
        edges = [(e.source, e.target) for e in builder.compile().get_graph().edges]
        assert ("coordinator", "planner") in edges
        assert ("supervisor", "researcher") in edges

    @pytest.mark.parametrize("deep_search", ["True", "False"])
    def test_get_input_params(self, deep_search):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("coordinator_system_prompt", "coordinator"),
            _setting("planner_system_prompt", "planner"),
            _setting("supervisor_system_prompt", "supervisor"),
            _setting("researcher_system_prompt", "researcher"),
            _setting("coder_system_prompt", "coder"),
            _setting("browser_system_prompt", "browser"),
            _setting("reporter_system_prompt", "reporter"),
            _setting("collection_name", "kb"),
            _setting("deep_search_mode", deep_search),
        ]

        params = agent.get_input_params(_message_request(), "test")

        assert params["deep_search_mode"] is (deep_search == "True")
        assert params["collection_name"] == "kb"
        assert params["coordinator_system_prompt"] == "coordinator"
        # agents created before the decision settings existed default to jev
        assert params["decision_engine"] == "jev"
        assert params["jev_integration_id"] == ""

    def test_get_coordinator_accepts_to_planner(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)
        agent.get_chat_model = MagicMock()

        command = agent.get_coordinator(self._state())

        assert command.goto == "planner"
        agent.get_chat_model.assert_not_called()
        instructions = agent.is_yes.call_args.args[1]
        assert instructions.startswith("coordinator")
        assert agent.COORDINATOR_QUESTION in instructions
        assert agent.is_yes.call_args.args[2] == {"query": "what?"}

    def test_get_coordinator_denies_with_llm_reply(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=False)
        agent.get_chat_model = MagicMock(
            return_value=RunnableLambda(lambda _: AIMessage(content="Hello there!"))
        )

        command = agent.get_coordinator(self._state())

        assert command.goto == END
        reply = command.update["messages"][0]
        assert reply.content == "Hello there!"
        assert reply.name == "coordinator"

    def test_get_planner(self):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        chain = MagicMock()
        chain.invoke.return_value = {"thought": "think", "steps": []}
        agent.get_planner_chain = MagicMock(return_value=chain)

        command = agent.get_planner(self._state())

        assert command.goto == "supervisor"
        assert command.update["execution_plan"] == {"thought": "think", "steps": []}

    def test_get_planner_deep_search(self):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        search_tool = MagicMock()
        search_tool.invoke.return_value = [{"title": "t", "snippet": "s"}]
        agent.get_web_search_tool = MagicMock(return_value=search_tool)
        chain = MagicMock()
        chain.invoke.return_value = {"thought": "think", "steps": []}
        agent.get_planner_chain = MagicMock(return_value=chain)

        command = agent.get_planner(self._state(deep_search_mode=True))

        assert command.goto == "supervisor"
        assert agent.get_planner_chain.call_args.kwargs["search_results"] is not None

    def test_get_supervisor_ends_when_complete(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)
        agent.choose = MagicMock()

        command = agent.get_supervisor(self._state())

        assert command.goto == END
        assert command.update == {"next": END}
        agent.choose.assert_not_called()
        instructions, context = agent.is_yes.call_args.args[1:]
        assert agent.COMPLETION_QUESTION in instructions
        assert set(context) == {"query", "execution_plan", "latest_work"}

    def test_get_supervisor_routes_when_incomplete(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=False)
        agent.choose = MagicMock(return_value="researcher")

        command = agent.get_supervisor(self._state())

        assert command.goto == "researcher"
        assert command.update == {"next": "researcher"}
        _, instructions, options, _ = agent.choose.call_args.args
        assert agent.ROUTING_QUESTION in instructions
        assert list(options) == ["researcher", "coder", "browser", "reporter"]
        assert agent.choose.call_args.kwargs["fallback"] == END

    def test_get_supervisor_stringifies_list_content(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)
        state = self._state(
            messages=[
                HumanMessage(content="what?"),
                AIMessage(content=[{"type": "text", "text": "partial"}]),
            ]
        )

        agent.get_supervisor(state)

        assert "partial" in agent.is_yes.call_args.args[2]["latest_work"]

    def test_get_supervisor_ends_when_step_budget_exhausted(self):
        agent = self._agent()
        agent.is_yes = MagicMock()
        agent.choose = MagicMock()

        command = agent.get_supervisor(self._state(remaining_steps=2))

        assert command.goto == END
        assert command.update == {"next": END}
        agent.is_yes.assert_not_called()
        agent.choose.assert_not_called()

    def test_get_supervisor_normal_path_above_step_reserve(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)

        command = agent.get_supervisor(self._state(remaining_steps=3))

        assert command.goto == END
        agent.is_yes.assert_called_once()

    def test_get_coordinator_context_default(self):
        assert self._agent().get_coordinator_context(self._state()) == {
            "query": "what?"
        }

    def test_base_supervisor_requires_team_configuration(self):
        from agent_lab.services.agent_types.base import SupervisedWorkflowAgentBase

        with pytest.raises(NotImplementedError):
            SupervisedWorkflowAgentBase.get_supervised_agents_configuration(
                self._agent()
            )

    def test_get_research_knowledge_base_tool(self):
        agent = self._agent()
        agent.get_embeddings_model = MagicMock()
        agent.document_repository = MagicMock()
        agent.document_repository.search.return_value = [
            MagicMock(page_content="doc-1"),
            MagicMock(page_content="doc-2"),
        ]

        output = agent.get_research_knowledge_base_tool(self._state()).func()

        assert output == "doc-1\n\ndoc-2"

    @pytest.mark.parametrize("deep_search", [True, False])
    @patch(
        "agent_lab.services.agent_types.coordinator_planner_supervisor.agent.create_react_agent"
    )
    def test_get_researcher(self, create_react_agent_mock, deep_search):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="findings")]
        }

        command = agent.get_researcher(self._state(deep_search_mode=deep_search))

        assert command.goto == "supervisor"
        assert command.update["messages"][0].content == "findings"

    def test_analyze_ast(self):
        import ast

        tree = ast.parse(
            "import os\nfrom json import dumps\n"
            "def f(a, b):\n    return a\n"
            "class C(Exception):\n    pass\n"
        )

        result = CoordinatorPlannerSupervisorAgent._analyze_ast(tree)

        assert "os" in result["imports"][0]
        assert result["functions"] == ["f(a, b)"]
        assert result["classes"] == ["C(Exception)"]

    def test_python_tool_valid_code(self):
        tool = self._agent().get_python_tool()

        output = tool.func("import os\ndef f():\n    pass\n")

        assert "Syntax: valid" in output
        assert "Functions: f()" in output

    def test_python_tool_syntax_error(self):
        tool = self._agent().get_python_tool()

        output = tool.func("def f(:")

        assert "Syntax error" in output

    def test_python_tool_non_string_input(self):
        tool = self._agent().get_python_tool()

        output = tool.func(42)

        assert "Invalid input" in output

    @patch(
        "agent_lab.services.agent_types.coordinator_planner_supervisor.agent.create_react_agent"
    )
    def test_get_coder(self, create_react_agent_mock):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="code")]
        }

        command = agent.get_coder(self._state())

        assert command.goto == "supervisor"

    @patch(
        "agent_lab.services.agent_types.coordinator_planner_supervisor.agent.create_react_agent"
    )
    def test_get_browser(self, create_react_agent_mock):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        agent.get_web_browser_tool = MagicMock()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="browsed")]
        }

        command = agent.get_browser(self._state())

        assert command.goto == "supervisor"

    @patch(
        "agent_lab.services.agent_types.coordinator_planner_supervisor.agent.create_react_agent"
    )
    def test_get_reporter(self, create_react_agent_mock):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="report")]
        }

        command = agent.get_reporter(self._state())

        assert command.goto == "supervisor"


class TestAdaptiveRagAgent:
    def _agent(self) -> AdaptiveRagAgent:
        agent = AdaptiveRagAgent(agent_utils=MagicMock())
        agent.get_chat_model = MagicMock()
        return agent

    def _state(self, **overrides) -> dict:
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "query": "what?",
            "collection_name": "kb",
            "generation": "an answer",
            "documents": [MagicMock(page_content="doc-1")],
            "messages": ["m1"],
            "remaining_steps": 25,
            "execution_system_prompt": "execute",
            "query_rewriter_system_prompt": "rewrite",
            "answer_grader_system_prompt": "grade",
            "retrieval_grader_system_prompt": "grade docs",
        }
        state.update(overrides)
        return state

    def test_create_default_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_default_settings("agent-1", "test")

        assert agent.agent_setting_service.create_agent_setting.call_count == 7

    def test_format_response(self):
        content, response_data = self._agent().format_response(self._state())

        assert content == "an answer"
        assert response_data["documents"] == ["doc-1"]

    def test_get_query_rewriter(self):
        llm = RunnableLambda(lambda _: AIMessage(content="better query"))

        result = self._agent().get_query_rewriter(llm, "system").invoke({"query": "q"})

        assert result == "better query"

    def test_get_rag_chain(self):
        llm = MagicMock()
        llm.with_structured_output.return_value = RunnableLambda(
            lambda _: {"generation": "g", "connection": "c"}
        )

        result = (
            self._agent()
            .get_rag_chain(llm, "system")
            .invoke({"query": "q", "context": "ctx"})
        )

        assert result["generation"] == "g"

    @pytest.mark.parametrize(
        "is_yes, remaining_steps, expected",
        [
            (True, 25, "complete_answer"),
            (False, 25, "incomplete_answer"),
            (False, 5, "complete_answer"),
        ],
    )
    def test_grade_generation(self, is_yes, remaining_steps, expected):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=is_yes)

        result = agent.grade_generation_v_documents_and_question(
            self._state(remaining_steps=remaining_steps)
        )

        assert result == expected
        agent.is_yes.assert_called_once_with(
            agent.is_yes.call_args.args[0],
            "grade",
            {"query": "what?", "answer": "an answer"},
        )

    def test_get_workflow_builder(self):
        builder = self._agent().get_workflow_builder("agent-1")

        assert {"retrieve", "grade_documents", "generate", "transform_query"} <= set(
            builder.nodes.keys()
        )

    def test_generate(self):
        agent = self._agent()
        chain = MagicMock()
        chain.invoke.return_value = {"generation": "g", "connection": "c"}
        agent.get_rag_chain = MagicMock(return_value=chain)

        result = agent.generate(self._state())

        assert result["generation"] == "g"
        assert len(result["messages"]) == 1

    def test_generate_summarizes_long_history(self):
        agent = self._agent()
        chain = MagicMock()
        chain.invoke.return_value = {"generation": "g", "connection": "c"}
        agent.get_rag_chain = MagicMock(return_value=chain)
        agent.get_chat_model.return_value.invoke.return_value = AIMessage(
            content="summary"
        )

        agent.generate(self._state(messages=["m1", "m2", "m3", "m4", "m5", "m6"]))

        agent.get_chat_model.return_value.invoke.assert_called_once()

    def test_grade_documents_filters(self):
        agent = self._agent()
        agent.is_yes = MagicMock(side_effect=[True, False])
        documents = [MagicMock(page_content="d1"), MagicMock(page_content="d2")]

        result = agent.grade_documents(self._state(documents=documents))

        assert result["documents"] == [documents[0]]
        assert agent.is_yes.call_args_list[0].args[1:] == (
            "grade docs",
            {"document": "d1", "query": "what?"},
        )

    def test_retrieve(self):
        agent = self._agent()
        agent.get_embeddings_model = MagicMock()
        agent.document_repository = MagicMock()
        documents = [MagicMock(page_content="d1")]
        agent.document_repository.search.return_value = documents

        result = agent.retrieve(self._state())

        assert result == {"documents": documents}

    def test_transform_query(self):
        agent = self._agent()
        rewriter = MagicMock()
        rewriter.invoke.return_value = "improved query"
        agent.get_query_rewriter = MagicMock(return_value=rewriter)

        result = agent.transform_query(self._state())

        assert result["query"] == "improved query"
        assert len(result["messages"]) == 1

    def test_get_input_params(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("execution_system_prompt", "execute"),
            _setting("query_rewriter_system_prompt", "rewrite"),
            _setting("answer_grader_system_prompt", "grade"),
            _setting("retrieval_grader_system_prompt", "grade docs"),
            _setting("collection_name", "kb"),
        ]

        params = agent.get_input_params(_message_request(), "test")

        assert params["collection_name"] == "kb"
        assert params["execution_system_prompt"] == "execute"
        assert params["messages"] == []
        # agents created before the jev settings existed default to llm decisions
        assert params["decision_engine"] == "llm"
        assert params["jev_integration_id"] == ""

    def test_get_input_params_jev_settings(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("execution_system_prompt", "execute"),
            _setting("query_rewriter_system_prompt", "rewrite"),
            _setting("answer_grader_system_prompt", "grade"),
            _setting("retrieval_grader_system_prompt", "grade docs"),
            _setting("collection_name", "kb"),
            _setting("decision_engine", "jev"),
            _setting("jev_integration_id", "jev-int"),
        ]

        params = agent.get_input_params(_message_request(), "test")

        assert params["decision_engine"] == "jev"
        assert params["jev_integration_id"] == "jev-int"

    def _jev_agent(self) -> AdaptiveRagAgent:
        agent = self._agent()
        agent.integration_service = MagicMock()
        agent.get_integration_credentials = MagicMock(
            return_value=("https://api.typesafe.ai", "ts-key")
        )
        return agent

    def _jev_state(self, **overrides) -> dict:
        return self._state(
            decision_engine="jev", jev_integration_id="jev-int", **overrides
        )

    @staticmethod
    def _jev_answers(client_cls, *nouls) -> MagicMock:
        client = client_cls.return_value.__enter__.return_value
        client.system_one.side_effect = [
            MagicMock(answers={"decision": MagicMock(noul=noul)}) for noul in nouls
        ]
        return client

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_grade_documents_with_jev(self, client_cls):
        agent = self._jev_agent()
        agent._ask_llm = MagicMock()
        client = self._jev_answers(client_cls, 0.9, 0.5, 0.2)
        documents = [MagicMock(page_content=f"d{i}") for i in range(3)]

        result = agent.grade_documents(self._jev_state(documents=documents))

        # 0.5 sits on the threshold and is kept
        assert result["documents"] == documents[:2]
        agent._ask_llm.assert_not_called()
        agent.integration_service.get_integration_by_id.assert_called_with(
            "jev-int", "test"
        )
        client_cls.assert_called_with(
            api_key="ts-key", base_url="https://api.typesafe.ai"
        )
        call = client.system_one.call_args_list[0].kwargs
        assert call["state"] == {"query": "what?", "document": "d0"}
        assert call["questions"]["decision"].instructions == "grade docs"

    @pytest.mark.parametrize(
        "noul, expected", [(0.8, "complete_answer"), (0.3, "incomplete_answer")]
    )
    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_grade_generation_with_jev(self, client_cls, noul, expected):
        agent = self._jev_agent()
        agent._ask_llm = MagicMock()
        client = self._jev_answers(client_cls, noul)

        result = agent.grade_generation_v_documents_and_question(self._jev_state())

        assert result == expected
        agent._ask_llm.assert_not_called()
        call = client.system_one.call_args.kwargs
        assert call["state"] == {"query": "what?", "answer": "an answer"}
        assert call["questions"]["decision"].instructions == "grade"

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_jev_failure_falls_back_to_llm(self, client_cls):
        agent = self._jev_agent()
        client_cls.return_value.__enter__.return_value.system_one.side_effect = (
            RuntimeError("jev unavailable")
        )
        agent._ask_llm = MagicMock(return_value={"binary_score": "yes"})

        result = agent.grade_generation_v_documents_and_question(self._jev_state())

        assert result == "complete_answer"
        agent._ask_llm.assert_called_once()

    @patch("agent_lab.services.agent_types.base.TypeSafeClient")
    def test_llm_engine_never_calls_jev(self, client_cls):
        agent = self._jev_agent()
        agent._ask_llm = MagicMock(return_value={"binary_score": "yes"})

        agent.grade_documents(self._state(decision_engine="llm"))
        agent.grade_documents(self._state())  # no decision_engine in state

        client_cls.assert_not_called()
        assert agent._ask_llm.call_count == 2


class TestVoiceMemosAgent:
    def _agent(self) -> VoiceMemosAgent:
        agent = VoiceMemosAgent(agent_utils=MagicMock())
        agent.get_chat_model = MagicMock()
        return agent

    def _state(self, **overrides) -> dict:
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "attachment_id": None,
            "audio_format": "mp3",
            "audio_language_model": "gpt-4o-audio",
            "query": "summarize",
            "transcription": "the transcript",
            "structured_report": None,
            "coordinator_system_prompt": "coordinator",
            "planner_system_prompt": "planner",
            "supervisor_system_prompt": "supervisor",
            "content_analyst_system_prompt": "analyst",
            "reporter_system_prompt": "reporter",
            "messages": [HumanMessage(content="summarize")],
        }
        state.update(overrides)
        return state

    def test_format_response(self):
        state = self._state(messages=[AIMessage(content="done")])

        content, response_data = self._agent().format_response(state)

        assert content == "done"
        assert response_data["transcription"] == "the transcript"

    def test_get_workflow_builder(self):
        builder = self._agent().get_workflow_builder("agent-1")

        assert {
            "coordinator",
            "planner",
            "supervisor",
            "reporter",
            "content_analyst",
        } <= set(builder.nodes.keys())
        edges = [(e.source, e.target) for e in builder.compile().get_graph().edges]
        assert ("supervisor", "content_analyst") in edges

    def test_create_default_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_default_settings("agent-1", "test")

        assert agent.agent_setting_service.create_agent_setting.call_count == 9

    def _settings(self):
        return [
            _setting("coordinator_system_prompt", "coordinator"),
            _setting("planner_system_prompt", "planner"),
            _setting("supervisor_system_prompt", "supervisor"),
            _setting("content_analyst_system_prompt", "analyst"),
            _setting("reporter_system_prompt", "reporter"),
            _setting("audio_language_model", "gpt-4o-audio"),
            _setting("audio_format", "mp3"),
        ]

    def test_get_input_params(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = self._settings()

        params = agent.get_input_params(_message_request("att-1"), "test")

        assert params["attachment_id"] == "att-1"
        assert params["audio_format"] == "mp3"
        assert params["structured_report"] is None
        assert params["decision_engine"] == "jev"

    def test_get_coordinator_context_includes_prior_conversation(self):
        state = self._state(
            messages=[
                HumanMessage(content="first"),
                AIMessage(content="Transcription: 'x'"),
                HumanMessage(content="follow up"),
            ],
            query="follow up",
        )

        context = self._agent().get_coordinator_context(state)

        assert context["query"] == "follow up"
        assert "Transcription: 'x'" in context["conversation"]
        assert "follow up" not in context["conversation"]

    def test_get_coordinator_context_omits_conversation_without_history(self):
        context = self._agent().get_coordinator_context(self._state())

        assert context == {"query": "summarize"}

    @patch(
        "agent_lab.services.agent_types.business.voice_memos.agent.create_react_agent"
    )
    def test_get_coordinator_gate_receives_conversation(self, create_react_agent_mock):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="direct reply")]
        }
        state = self._state(
            messages=[
                HumanMessage(content="first"),
                AIMessage(content="Transcription: 'x'"),
                HumanMessage(content="follow up"),
            ],
            query="follow up",
        )

        agent.get_coordinator(state)

        assert "conversation" in agent.is_yes.call_args.args[2]

    def test_get_coordinator_tools(self):
        assert len(self._agent().get_coordinator_tools()) == 2

    def test_get_content_analyst_tools(self):
        assert self._agent().get_content_analyst_tools() == []

    @patch(
        "agent_lab.services.agent_types.business.voice_memos.agent.create_react_agent"
    )
    def test_get_coordinator_without_attachment_accepted(self, create_react_agent_mock):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=True)
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="direct reply")]
        }

        command = agent.get_coordinator(self._state())

        assert command.goto == END
        assert command.update["messages"][0].content == "direct reply"
        agent.is_yes.assert_called_once()

    @patch(
        "agent_lab.services.agent_types.business.voice_memos.agent.create_react_agent"
    )
    def test_get_coordinator_without_attachment_denied(self, create_react_agent_mock):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=False)
        agent.get_chat_model = MagicMock(
            return_value=RunnableLambda(lambda _: AIMessage(content="Hi!"))
        )

        command = agent.get_coordinator(self._state())

        assert command.goto == END
        assert command.update["messages"][0].content == "Hi!"
        create_react_agent_mock.assert_not_called()

    def test_get_coordinator_with_audio_attachment(self):
        agent = self._agent()
        attachment = MagicMock()
        attachment.raw_content = b"audio-bytes"
        agent.attachment_service.get_attachment_by_id.return_value = attachment
        openai_client = MagicMock()
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="the transcript"))]
        openai_client.chat.completions.create.return_value = completion
        agent.get_openai_client = MagicMock(return_value=openai_client)
        agent.is_yes = MagicMock()

        command = agent.get_coordinator(self._state(attachment_id="att-1"))

        assert command.goto == "planner"
        assert command.update["transcription"] == "the transcript"
        agent.is_yes.assert_not_called()

    def test_get_planner(self):
        agent = self._agent()
        chain = MagicMock()
        chain.invoke.return_value = {"thought": "think", "steps": []}
        agent.get_planner_chain = MagicMock(return_value=chain)

        command = agent.get_planner(self._state())

        assert command.goto == "supervisor"

    def test_get_supervisor_routes(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=False)
        agent.choose = MagicMock(return_value="content_analyst")

        command = agent.get_supervisor(self._state())

        assert command.goto == "content_analyst"
        assert list(agent.choose.call_args.args[2]) == ["content_analyst", "reporter"]

    def test_get_supervisor_ends_when_report_ready(self):
        agent = self._agent()
        agent.is_yes = MagicMock()

        command = agent.get_supervisor(
            self._state(structured_report={"main_topic": "t"})
        )

        assert command.goto == "__end__"
        agent.is_yes.assert_not_called()

    def test_get_reporter_chain(self):
        agent = self._agent()
        llm = MagicMock()
        llm.bind_tools.return_value.with_structured_output.return_value = (
            RunnableLambda(lambda _: {"main_topic": "t"})
        )

        result = agent.get_reporter_chain(llm, "system").invoke(
            {"content_analysis": "analysis"}
        )

        assert result == {"main_topic": "t"}

    def test_get_reporter(self):
        agent = self._agent()
        chain = MagicMock()
        chain.invoke.return_value = {"main_topic": "t"}
        agent.get_reporter_chain = MagicMock(return_value=chain)

        command = agent.get_reporter(self._state())

        assert command.goto == "supervisor"
        assert command.update["structured_report"] == {"main_topic": "t"}

    @patch(
        "agent_lab.services.agent_types.business.voice_memos.agent.create_react_agent"
    )
    def test_get_content_analyst(self, create_react_agent_mock):
        agent = self._agent()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="analysis")]
        }

        command = agent.get_content_analyst(self._state())

        assert command.goto == "supervisor"


class TestAzureEntraIdVoiceMemosAgent:
    def _agent(self) -> AzureEntraIdVoiceMemosAgent:
        return AzureEntraIdVoiceMemosAgent(agent_utils=MagicMock())

    def test_get_coordinator_tools(self):
        assert len(self._agent().get_coordinator_tools()) == 3

    def test_get_content_analyst_tools(self):
        tools = self._agent().get_content_analyst_tools()

        assert [tool.name for tool in tools] == ["person_search", "person_details"]

    def test_get_input_params(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("coordinator_system_prompt", "coordinator"),
            _setting("planner_system_prompt", "planner"),
            _setting("supervisor_system_prompt", "supervisor"),
            _setting("content_analyst_system_prompt", "analyst {{ CURRENT_TIME }}"),
            _setting("reporter_system_prompt", "reporter"),
            _setting("audio_language_model", "gpt-4o-audio"),
            _setting("audio_format", "mp3"),
        ]

        params = agent.get_input_params(_message_request(), "test")

        assert params["content_analyst_system_prompt"].startswith("analyst ")


class TestFastVoiceMemosAgent:
    def _agent(self) -> FastVoiceMemosAgent:
        agent = FastVoiceMemosAgent(agent_utils=MagicMock())
        agent.get_chat_model = MagicMock()
        return agent

    def test_get_input_params(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("coordinator_system_prompt", "coordinator"),
            _setting("content_analyst_system_prompt", "analyst"),
            _setting("audio_language_model", "gpt-4o-audio"),
            _setting("audio_format", "mp3"),
        ]

        params = agent.get_input_params(_message_request("att-1"), "test")

        assert params["attachment_id"] == "att-1"
        assert "planner_system_prompt" not in params
        assert params["decision_engine"] == "jev"

    def test_get_workflow_builder(self):
        builder = self._agent().get_workflow_builder("agent-1")

        assert set(builder.nodes.keys()) == {"coordinator", "content_analyst"}
        builder.compile()

    def test_audio_is_handed_to_content_analyst(self):
        agent = self._agent()
        attachment = MagicMock()
        attachment.raw_content = b"audio-bytes"
        agent.attachment_service.get_attachment_by_id.return_value = attachment
        openai_client = MagicMock()
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="the transcript"))]
        openai_client.chat.completions.create.return_value = completion
        agent.get_openai_client = MagicMock(return_value=openai_client)
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "attachment_id": "att-1",
            "audio_format": "mp3",
            "audio_language_model": "gpt-4o-audio",
            "query": "summarize",
            "coordinator_system_prompt": "coordinator",
            "messages": [HumanMessage(content="summarize")],
        }

        command = agent.get_coordinator(state)

        assert agent.coordinator_accept_node == "content_analyst"
        assert command.goto == "content_analyst"
        assert command.update["transcription"] == "the transcript"

    def test_denied_text_request_ends(self):
        agent = self._agent()
        agent.is_yes = MagicMock(return_value=False)
        agent.get_chat_model = MagicMock(
            return_value=RunnableLambda(lambda _: AIMessage(content="Hi!"))
        )
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "attachment_id": None,
            "query": "hello",
            "coordinator_system_prompt": "coordinator",
            "messages": [HumanMessage(content="hello")],
        }

        command = agent.get_coordinator(state)

        assert command.goto == "__end__"

    @patch(
        "agent_lab.services.agent_types.business.voice_memos.agent.create_react_agent"
    )
    def test_get_content_analyst(self, create_react_agent_mock):
        agent = self._agent()
        create_react_agent_mock.return_value.invoke.return_value = {
            "messages": [AIMessage(content="analysis")],
            "structured_response": {"main_topic": "t"},
        }
        state = {
            "agent_id": "agent-1",
            "schema": "test",
            "content_analyst_system_prompt": "analyst",
        }

        command = agent.get_content_analyst(state)

        assert command.goto == "__end__"
        assert command.update["structured_report"] == {"main_topic": "t"}


class TestAzureWorkflowBase:
    def _agent(self) -> AzureEntraIdOrganizationWorkflowBase:
        agent = AzureEntraIdVoiceMemosAgent(agent_utils=MagicMock())
        agent.get_token = MagicMock(return_value="token")
        return agent

    @patch("agent_lab.services.agent_types.azure.ConfidentialClientApplication")
    def test_get_token_success(self, msal_app, monkeypatch):
        monkeypatch.setenv("AZURE_CLIENT_ID", "cid")
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "secret")
        monkeypatch.setenv("AZURE_TENANT_ID", "tid")
        msal_app.return_value.acquire_token_for_client.return_value = {
            "access_token": "the-token"
        }
        agent = AzureEntraIdVoiceMemosAgent(agent_utils=MagicMock())

        assert agent.get_token() == "the-token"

    @patch("agent_lab.services.agent_types.azure.ConfidentialClientApplication")
    def test_get_token_failure_returns_empty(self, msal_app):
        msal_app.return_value.acquire_token_for_client.return_value = {
            "error": "denied"
        }
        agent = AzureEntraIdVoiceMemosAgent(agent_utils=MagicMock())

        assert agent.get_token() == ""

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_search_returns_users(self, requests_get):
        requests_get.return_value.status_code = 200
        requests_get.return_value.json.return_value = {
            "value": [{"displayName": "John Doe", "userPrincipalName": "john@x.com"}]
        }

        output = self._agent().get_person_search_tool().func(name="John")

        assert output == "John Doe (john@x.com)"

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_search_no_users(self, requests_get):
        requests_get.return_value.status_code = 200
        requests_get.return_value.json.return_value = {"value": []}

        output = self._agent().get_person_search_tool().func(name="Nobody")

        assert output == "No users found"

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_search_error(self, requests_get):
        requests_get.return_value.status_code = 500
        requests_get.return_value.text = "boom"

        output = self._agent().get_person_search_tool().func(name="John")

        assert output == "Error: 500 - boom"

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_details_found(self, requests_get):
        requests_get.return_value.status_code = 200
        requests_get.return_value.json.return_value = {"displayName": "John Doe"}

        output = self._agent().get_person_details_tool().func(email="john@x.com")

        assert '"displayName": "John Doe"' in output

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_details_not_found(self, requests_get):
        requests_get.return_value.status_code = 404

        output = self._agent().get_person_details_tool().func(email="ghost@x.com")

        assert output == "User not found"

    @patch("agent_lab.services.agent_types.azure.requests.get")
    def test_person_details_error(self, requests_get):
        requests_get.return_value.status_code = 503
        requests_get.return_value.text = "unavailable"

        output = self._agent().get_person_details_tool().func(email="john@x.com")

        assert output == "Error: 503 - unavailable"


class TestReactRagAgent:
    def _agent(self) -> ReactRagAgent:
        return ReactRagAgent(agent_utils=MagicMock())

    def test_create_default_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_default_settings("agent-1", "test")

        assert agent.agent_setting_service.create_agent_setting.call_count == 2

    @patch("agent_lab.services.agent_types.react_rag.agent.create_react_agent")
    def test_get_workflow(self, create_react_agent_mock):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("execution_system_prompt", "execute"),
        ]

        workflow = agent.get_workflow("agent-1", "test")

        assert workflow is create_react_agent_mock.return_value
        agent.graph_persistence_factory.build_checkpoint_saver.assert_called_once()

    def test_get_input_params(self):
        agent = self._agent()
        agent.get_embeddings_model = MagicMock()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("collection_name", "kb"),
        ]
        agent.document_repository = MagicMock()
        agent.document_repository.search.return_value = [
            MagicMock(page_content="doc-1"),
            MagicMock(page_content="doc-2"),
        ]

        params = agent.get_input_params(_message_request(), "test")

        assert "doc-1\n---\ndoc-2" in params["messages"][0][1]

    def test_process_message(self):
        agent = self._agent()
        workflow = MagicMock()
        workflow.invoke.return_value = {
            "messages": [HumanMessage(content="q"), AIMessage(content="answer")]
        }
        agent.get_workflow = MagicMock(return_value=workflow)
        agent.get_input_params = MagicMock(return_value={"messages": []})

        message = agent.process_message(_message_request(), "test")

        assert message.message_content == "answer"
        assert message.agent_id == "agent-1"


class TestVisionDocumentAgent:
    def _agent(self) -> VisionDocumentAgent:
        return VisionDocumentAgent(agent_utils=MagicMock())

    def _state(self) -> dict:
        return {
            "agent_id": "agent-1",
            "schema": "test",
            "query": "describe",
            "generation": "a description",
            "execution_system_prompt": "execute",
            "image_base64": "aW1n",
            "image_content_type": "image/png",
        }

    def test_format_response(self):
        content, response_data = self._agent().format_response(self._state())

        assert content == "a description"
        assert response_data["query"] == "describe"

    def test_generate(self):
        agent = self._agent()
        agent.get_chat_model = MagicMock()
        chain = MagicMock()
        chain.invoke.return_value = MagicMock(content="a description")
        agent.get_image_analysis_chain = MagicMock(return_value=chain)

        result = agent.generate(self._state())

        assert result == {"generation": "a description"}
        assert agent.task_notification_service.publish_update.call_count == 2

    def test_get_workflow_builder(self):
        builder = self._agent().get_workflow_builder("agent-1")

        assert set(builder.nodes.keys()) == {"generate"}

    def test_get_input_params(self):
        agent = self._agent()
        agent.agent_setting_service.get_agent_settings.return_value = [
            _setting("execution_system_prompt", "execute"),
        ]
        attachment = MagicMock()
        attachment.raw_content = b"image-bytes"
        attachment.file_name = "photo.png"
        agent.attachment_service.get_attachment_by_id.return_value = attachment

        params = agent.get_input_params(_message_request("att-1"), "test")

        assert params["image_content_type"] == "image/png"
        assert params["execution_system_prompt"] == "execute"

    def test_create_default_settings(self):
        agent = self._agent()
        agent.agent_setting_service = MagicMock()

        agent.create_default_settings("agent-1", "test")

        agent.agent_setting_service.create_agent_setting.assert_called_once()
