import asyncio
import json
import logging
import os
import shlex
import uuid
from abc import ABC, abstractmethod
from datetime import timedelta, datetime, timezone

import hvac
import icalendar
from browser_use import (
    llm as browser_use_llm,
    Agent as BrowserAgent,
    Browser,
    ChatOpenAI as BrowserChatOpenAI,
    ChatAnthropic as BrowserChatAnthropic,
)
from dependency_injector.providers import Configuration
from jinja2 import Environment, DictLoader, select_autoescape
from langchain_anthropic import ChatAnthropic
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool, BaseTool
from langchain_xai import ChatXAI
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from markitdown import MarkItDown
from langgraph.graph import MessagesState
from langgraph.types import Command
from openai import OpenAI
from typing_extensions import List, Annotated, Literal

from agent_lab.domain.exceptions.base import ConfigurationError, ResourceNotFoundError
from agent_lab.domain.models import Agent, Integration, LanguageModel
from agent_lab.infrastructure.database.checkpoints import GraphPersistenceFactory
from agent_lab.infrastructure.database.vectors import DocumentRepository
from agent_lab.infrastructure.metrics.tracing import (
    trace_agent_message,
    set_current_trace_io,
)
from agent_lab.interface.api.messages.schema import MessageRequest, Message
from agent_lab.services.agent_settings import AgentSettingService
from agent_lab.services.agents import AgentService
from agent_lab.services.attachments import AttachmentService
from agent_lab.services.integrations import IntegrationService
from agent_lab.services.language_model_settings import LanguageModelSettingService
from agent_lab.services.language_models import LanguageModelService
from agent_lab.services.tasks import TaskNotificationService, TaskProgress


def join_messages(left: List, right: List) -> List:
    if not isinstance(left, list):
        left = [left]
    if not isinstance(right, list):
        right = [right]

    combined = left + right

    unique_messages = []
    for msg in combined:
        if msg not in unique_messages:
            unique_messages.append(msg)

    return unique_messages


class AgentUtils:
    def __init__(
        self,
        agent_service: AgentService,
        agent_setting_service: AgentSettingService,
        attachment_service: AttachmentService,
        language_model_service: LanguageModelService,
        language_model_setting_service: LanguageModelSettingService,
        integration_service: IntegrationService,
        vault_client: hvac.Client,
        graph_persistence_factory: GraphPersistenceFactory,
        document_repository: DocumentRepository,
        task_notification_service: TaskNotificationService,
        config: Configuration,
    ):
        self.config = config
        self.agent_service = agent_service
        self.agent_setting_service = agent_setting_service
        self.attachment_service = attachment_service
        self.language_model_service = language_model_service
        self.language_model_setting_service = language_model_setting_service
        self.integration_service = integration_service
        self.vault_client = vault_client
        self.graph_persistence_factory = graph_persistence_factory
        self.document_repository = document_repository
        self.task_notification_service = task_notification_service


class AgentBase(ABC):
    def __init__(self, agent_utils: AgentUtils):
        self.base_url = agent_utils.config.get("api_base_url")
        self.agent_service = agent_utils.agent_service
        self.agent_setting_service = agent_utils.agent_setting_service
        self.attachment_service = agent_utils.attachment_service
        self.document_repository = agent_utils.document_repository
        self.language_model_service = agent_utils.language_model_service
        self.language_model_setting_service = agent_utils.language_model_setting_service
        self.integration_service = agent_utils.integration_service
        self.task_notification_service = agent_utils.task_notification_service
        self.vault_client = agent_utils.vault_client
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def create_default_settings(self, agent_id: str, schema: str):
        pass

    @abstractmethod
    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        pass

    @abstractmethod
    def process_message(self, message_request: MessageRequest, schema: str) -> Message:
        pass

    def format_response(self, workflow_state: MessagesState) -> (str, dict):
        response_data = {
            "messages": [
                json.loads(message.model_dump_json())
                for message in workflow_state["messages"]
            ]
        }
        return response_data["messages"][-1]["content"], response_data

    def get_language_model_integration(
        self, agent: Agent, schema: str
    ) -> (LanguageModel, Integration):
        language_model = self.language_model_service.get_language_model_by_id(
            agent.language_model_id, schema
        )
        integration = self.integration_service.get_integration_by_id(
            language_model.integration_id, schema
        )
        return language_model, integration

    def get_integration_credentials(self, integration: Integration) -> (str, str):
        secrets = self.vault_client.secrets.kv.read_secret_version(
            path=f"integration_{integration.id}", raise_on_deleted_version=False
        )
        api_endpoint = secrets["data"]["data"]["api_endpoint"]
        api_key = secrets["data"]["data"]["api_key"]
        return api_endpoint, api_key

    def get_embeddings_model(self, agent_id, schema: str) -> Embeddings:
        agent = self.agent_service.get_agent_by_id(agent_id, schema)
        language_model, integration = self.get_language_model_integration(agent, schema)
        api_endpoint, api_key = self.get_integration_credentials(integration)

        lm_settings = self.language_model_setting_service.get_language_model_settings(
            language_model.id, schema
        )

        lm_settings_dict = {
            setting.setting_key: setting.setting_value for setting in lm_settings
        }

        if os.getenv("EMBEDDINGS_ENDPOINT"):
            api_endpoint = os.getenv("EMBEDDINGS_ENDPOINT")

        return OpenAIEmbeddings(
            model=lm_settings_dict["embeddings"],
            openai_api_base=api_endpoint,
            openai_api_key=api_key,
            check_embedding_ctx_length=False,
            chunk_size=100,
        )

    def get_chat_model(
        self, agent_id, schema: str, language_model_tag: str = None
    ) -> BaseChatModel:
        agent = self.agent_service.get_agent_by_id(agent_id, schema)
        language_model, integration = self.get_language_model_integration(agent, schema)
        api_endpoint, api_key = self.get_integration_credentials(integration)

        if language_model_tag is None:
            language_model_tag = language_model.language_model_tag

        lm_settings = self.language_model_setting_service.get_language_model_settings(
            language_model.id, schema
        )

        lm_settings_dict = {
            setting.setting_key: setting.setting_value for setting in lm_settings
        }

        # generation guardrails, set as language model settings on creation;
        # absent settings (pre-existing models) keep provider defaults
        guardrail_kwargs = {}
        if "max_tokens" in lm_settings_dict:
            guardrail_kwargs["max_tokens"] = int(lm_settings_dict["max_tokens"])
        if "timeout" in lm_settings_dict:
            guardrail_kwargs["timeout"] = float(lm_settings_dict["timeout"])

        if integration.integration_type == "openai_api_v1":
            return ChatOpenAI(
                model_name=language_model_tag,
                openai_api_base=api_endpoint,
                openai_api_key=api_key,
                **guardrail_kwargs,
            )
        elif integration.integration_type == "xai_api_v1":
            return ChatXAI(
                model=language_model_tag,
                xai_api_base=api_endpoint,
                xai_api_key=api_key,
                **guardrail_kwargs,
            )
        elif integration.integration_type == "anthropic_api_v1":
            return ChatAnthropic(
                model=language_model_tag,
                anthropic_api_url=api_endpoint,
                anthropic_api_key=api_key,
                **guardrail_kwargs,
            )
        else:
            raise ConfigurationError(
                f"unsupported integration type: {integration.integration_type}"
            )

    def get_openai_client(self, agent_id: str, schema: str) -> OpenAI:
        agent = self.agent_service.get_agent_by_id(agent_id, schema)
        _, integration = self.get_language_model_integration(agent, schema)
        api_endpoint, api_key = self.get_integration_credentials(integration)

        return OpenAI(
            api_key=api_key,
            base_url=api_endpoint,
        )

    def read_file_content(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            raise ResourceNotFoundError(file_path)

        with open(file_path, "r") as file:
            return file.read().strip()

    def parse_prompt_template(
        self, settings_dict: dict, prompt_key: str, template_vars: dict
    ) -> str:
        env = Environment(
            loader=DictLoader(settings_dict),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(prompt_key)
        return template.render(template_vars)


class WorkflowAgentBase(AgentBase, ABC):
    QUERY_FORMAT = "<query>{query}</query>"

    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)
        self.graph_persistence_factory = agent_utils.graph_persistence_factory

    @abstractmethod
    def get_workflow_builder(self, agent_id: str):
        pass

    def get_config(self, agent_id: str) -> dict:
        return {
            "configurable": {
                "thread_id": agent_id,
            },
            "recursion_limit": 30,
        }

    def create_thought_chain(
        self,
        human_input: str,
        ai_response: str,
        connection: str = None,
        llm: BaseChatModel = None,
        token_limit: int = 1024,
    ):
        # Build the chain of thought
        if llm is not None:
            prompt = (
                f"Summarize the text delimited by <ai_resp></ai_resp> using at most {token_limit} tokens.\n"
                f"<ai_resp>{ai_response}</ai_resp>"
            )
            processed_response = llm.invoke(prompt).content
        else:
            processed_response = ai_response

        thought_chain = (
            f"First: The human asked or stated - {human_input}\n"
            f"Then: The AI responded with - {processed_response}\n"
        )

        if connection is not None:
            thought_chain += f"Connection: {connection}"

        return thought_chain

    @trace_agent_message
    def process_message(self, message_request: MessageRequest, schema: str) -> Message:
        agent_id = message_request.agent_id
        checkpointer = self.graph_persistence_factory.build_checkpoint_saver()
        workflow = self.get_workflow_builder(agent_id).compile(
            checkpointer=checkpointer
        )

        config = self.get_config(agent_id)
        self.logger.info(f"Agent[{agent_id}] -> Config -> {config}")

        inputs = self.get_input_params(message_request, schema)
        self.logger.info(f"Agent[{agent_id}] -> Input -> {inputs}")

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="...",
            )
        )

        workflow_result = workflow.invoke(inputs, config)
        self.logger.info(f"Agent[{agent_id}] -> Result -> {workflow_result}")
        response_content, response_data = self.format_response(workflow_result)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="completed",
                message_content=response_content,
                response_data=response_data,
            )
        )

        # Langfuse trace output formatting
        set_current_trace_io(
            input_value=message_request.message_content,
            output_value=response_content,
            metadata={
                "agent_id": agent_id,
                "agent_class": self.__class__.__name__,
                "schema": schema,
            },
        )

        return Message(
            message_role="assistant",
            message_content=response_content,
            response_data=response_data,
            agent_id=agent_id,
        )

    def get_image_analysis_chain(
        self, llm, execution_system_prompt, image_content_type
    ):
        generate_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", execution_system_prompt),
                (
                    "human",
                    [
                        {
                            "type": "text",
                            "text": WorkflowAgentBase.QUERY_FORMAT,
                        },
                        {
                            "type": "image_url",
                            "image_url": f"data:{image_content_type};base64,"
                            + "{image_base64}",
                        },
                    ],
                ),
            ]
        )
        return generate_prompt | llm

    _REDIRECT_OPS = {"<", ">", ">>", "<<", "2>", "2>>", "&>", "&>>"}

    @staticmethod
    def _classify_shell_token(token, redirect_ops):
        if token == "|":
            return "pipe"
        if token in (";", "&&", "||"):
            return "separator"
        if token in redirect_ops:
            return "redirection"
        if "=" in token and not token.startswith("-"):
            parts = token.split("=", 1)
            if parts[0].isidentifier():
                return "variable"
        if token.startswith(("$(", "`")):
            return "subshell"
        return "command"

    @staticmethod
    def _apply_shell_token(kind, token, state):
        if kind in ("pipe", "separator") and state["current_cmd"]:
            state["commands"].append(" ".join(state["current_cmd"]))
            state["current_cmd"] = []

        if kind == "pipe":
            state["pipes"] += 1
        elif kind == "redirection":
            state["redirections"].append(token)
        elif kind == "variable":
            state["variables"].append(token.split("=", 1)[0])
        elif kind == "subshell":
            state["subshells"] += 1
            state["current_cmd"].append(token)
        elif kind == "command":
            state["current_cmd"].append(token)

    @staticmethod
    def _analyze_shell(script):
        try:
            tokens = shlex.split(script)
        except ValueError as e:
            return None, str(e)

        classify = WorkflowAgentBase._classify_shell_token
        ops = WorkflowAgentBase._REDIRECT_OPS
        apply_token = WorkflowAgentBase._apply_shell_token

        state = {
            "commands": [],
            "current_cmd": [],
            "pipes": 0,
            "redirections": [],
            "variables": [],
            "subshells": 0,
        }

        for token in tokens:
            apply_token(classify(token, ops), token, state)

        if state["current_cmd"]:
            state["commands"].append(" ".join(state["current_cmd"]))

        return {
            "commands": state["commands"],
            "pipes": state["pipes"],
            "redirections": state["redirections"],
            "variables": state["variables"],
            "subshells": state["subshells"],
        }, None

    def get_bash_tool(self) -> BaseTool:
        @tool("bash_tool")
        def bash_tool_call(
            cmd: Annotated[str, "The bash script to analyze."],
        ):
            """Use this to analyze bash script structure and validate syntax.
            This tool parses the script and returns its structure (commands, pipes,
            redirections, variables) without executing it. Use it to verify script
            correctness and understand its components."""

            if not isinstance(cmd, str):
                error_msg = f"Invalid input: cmd must be a string, got {type(cmd)}"
                self.logger.error(error_msg)
                return f"Error analyzing script: {error_msg}"

            self.logger.info("Analyzing Bash script")
            result, error = self._analyze_shell(cmd)

            if error:
                self.logger.error(f"Shell parse error: {error}")
                return f"Parse error in script:\n```bash\n{cmd}\n```\nError: {error}"

            summary = [
                "Syntax: valid",
                f"Lines: {len(cmd.splitlines())}",
            ]
            if result["commands"]:
                summary.append(f"Commands: {'; '.join(result['commands'])}")
            if result["pipes"]:
                summary.append(f"Pipes: {result['pipes']}")
            if result["redirections"]:
                summary.append(f"Redirections: {', '.join(result['redirections'])}")
            if result["variables"]:
                summary.append(f"Variables: {', '.join(result['variables'])}")
            if result["subshells"]:
                summary.append(f"Subshells: {result['subshells']}")

            analysis = "\n".join(summary)
            self.logger.info("Script analysis successful")
            return f"Analysis of:\n```bash\n{cmd}\n```\n{analysis}"

        return bash_tool_call

    def get_last_interaction_messages(self, messages):
        subarray = []
        found_human_message = False

        for message in reversed(messages):
            subarray.insert(0, message)
            if isinstance(message, HumanMessage):
                found_human_message = True
                break

        return subarray if found_human_message else []


class ContactSupportAgentBase(WorkflowAgentBase, ABC):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    @abstractmethod
    def get_person_search_tool(self) -> BaseTool:
        pass

    @abstractmethod
    def get_person_details_tool(self) -> BaseTool:
        pass

    def get_ical_attachment_tool(self) -> BaseTool:
        @tool("ical_attachment")
        def ical_attachment_tool_call(
            event_name: Annotated[str, "The name of the event."],
            event_description: Annotated[str, "The description of the event."],
            event_start_datetime: Annotated[datetime, "The start date of the event."],
            event_duration_minutes: Annotated[
                int, "The duration of the event in minutes."
            ],
            event_attendees: Annotated[
                list[str], "The attendees of the event in the format 'name <email>'"
            ],
        ):
            """
            Creates an iCalendar attachment and returns a link to download it.
            Use this tool to create appointments or other types of events per user request.
            This tool generates an attachment with corresponding URL, you must forward it to the user so
            they can download it.
            """
            event_attachment_id = str(uuid.uuid4())

            if event_start_datetime.tzinfo is None:
                event_start_datetime = event_start_datetime.replace(tzinfo=timezone.utc)

            event_end_datetime = event_start_datetime + timedelta(
                minutes=event_duration_minutes
            )

            # Create calendar
            cal = icalendar.Calendar()
            cal.add("prodid", "-//Agent-Lab//ical_attachment_tool")
            cal.add("version", "2.0")

            if event_attendees:
                cal.add("method", "REQUEST")
            else:
                cal.add("method", "PUBLISH")

            # Create event
            event = icalendar.Event()
            event.add("summary", event_name)
            event.add("description", event_description)
            event.add("dtstart", event_start_datetime)
            event.add("dtend", event_end_datetime)
            event.add("uid", event_attachment_id)
            event.add("dtstamp", datetime.now(timezone.utc))

            for attendee in event_attendees:
                event.add("attendee", attendee)

            cal.add_component(event)
            ical_result = cal.to_ical()
            parsed_ical_result = ical_result.decode("utf-8")
            self.attachment_service.create_attachment_with_content(
                raw_content=ical_result,
                parsed_content=parsed_ical_result,
                file_name=f"{event_attachment_id}.ics",
                attachment_id=event_attachment_id,
                schema="public",
            )

            return f"{self.base_url}/attachments/download/{event_attachment_id}"

        return ical_attachment_tool_call


class WebAgentBase(WorkflowAgentBase, ABC):
    def __init__(self, agent_utils: AgentUtils):
        self.cdp_url = agent_utils.config["cdp_url"]
        super().__init__(agent_utils)

    def get_browser_chat_model(
        self, agent_id, schema: str, language_model_tag: str = None
    ) -> browser_use_llm.base.BaseChatModel:
        agent = self.agent_service.get_agent_by_id(agent_id, schema)
        language_model, integration = self.get_language_model_integration(agent, schema)
        api_endpoint, api_key = self.get_integration_credentials(integration)

        if language_model_tag is None:
            language_model_tag = language_model.language_model_tag

        if integration.integration_type == "openai_api_v1":
            return BrowserChatOpenAI(
                model=language_model_tag,
                base_url=api_endpoint,
                api_key=api_key,
                temperature=1,
                reasoning_effort="medium",
                frequency_penalty=None,
            )
        elif integration.integration_type == "anthropic_api_v1":
            return BrowserChatAnthropic(
                model=language_model_tag,
                base_url=api_endpoint,
                api_key=api_key,
            )
        else:
            raise ConfigurationError(
                f"unsupported integration type: {integration.integration_type}"
            )

    def get_web_browser_tool(self, agent_id: str, schema: str) -> BaseTool:
        chat_model = self.get_browser_chat_model(agent_id, schema)

        @tool("browser_tool")
        def browser_tool_call(  # pragma: no cover - drives a live browser session
            instruction: Annotated[str, "The instruction to use browser."],
        ):
            """
            "Use this tool to interact with web browsers. Input should be a natural language description of
            what you want to do with the browser, such as 'Go to google.com and search for browser-use', or 'Navigate
            to Reddit and find the top post about AI'."
            """

            self.task_notification_service.publish_update(
                task_progress=TaskProgress(
                    agent_id=agent_id,
                    status="in_progress",
                    message_content="Starting headless browser tool...",
                )
            )

            browser = Browser(cdp_url=self.cdp_url)

            browser_agent = BrowserAgent(
                task=instruction, llm=chat_model, browser=browser
            )

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(browser_agent.run())
                json_result = json.dumps({"result_content": result.final_result()})

            finally:
                loop.close()

            self.logger.info(
                f"Browser tool completed successfully, result: {json_result}"
            )

            return json_result

        return browser_tool_call

    def get_web_crawl_tool(self) -> BaseTool:
        @tool("web_crawl")
        def web_crawl_tool_call(
            urls: Annotated[List[str], "The URLs to read content from."],
        ):
            """
            Extracts content from web pages based on provided URLs and returns
            it as markdown. Input should be a list of one or more URLs.
            """
            markitdown = MarkItDown()
            results = []
            for url in urls:
                try:
                    results.append(
                        {"url": url, "content": markitdown.convert(url).text_content}
                    )
                except Exception as e:
                    results.append({"url": url, "error": str(e)})
            return json.dumps({"results": results}, ensure_ascii=False)

        return web_crawl_tool_call

    def get_web_search_tool(self, max_results=5) -> BaseTool:
        return DuckDuckGoSearchResults(
            name="web_search",
            description=(
                "A web search engine. Useful for when you need to answer "
                "questions about current events. Input should be a search query."
            ),
            num_results=max_results,
            output_format="list",
        )


class SupervisedWorkflowAgentBase(WebAgentBase, ABC):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def get_coordinator_tools(self) -> list:
        return []

    @abstractmethod
    def get_coordinator(
        self, state: MessagesState
    ) -> Command[Literal["planner", "__end__"]]:
        pass

    def get_coordinator_chain(self, llm, coordinator_system_prompt: str):
        coordinator_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", coordinator_system_prompt),
                ("human", WorkflowAgentBase.QUERY_FORMAT),
            ]
        )
        return coordinator_prompt | llm

    def get_planner_tools(self) -> list:
        return [self.get_web_search_tool(), self.get_web_crawl_tool()]

    @abstractmethod
    def get_planner(self, state: MessagesState) -> Command[Literal["supervisor"]]:
        pass

    def get_planner_chain(
        self, llm, planner_system_prompt: str, search_results: str = None
    ):
        if search_results is not None:
            planner_input = (
                WorkflowAgentBase.QUERY_FORMAT
                + "\n\n<search_results>{search_results}</search_results>"
            )
        else:
            planner_input = WorkflowAgentBase.QUERY_FORMAT

        planner_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", planner_system_prompt),
                ("human", planner_input),
            ]
        )
        return planner_prompt | llm

    def get_supervisor_tools(self) -> list:
        return []

    @abstractmethod
    def get_supervisor(self, state: MessagesState) -> Command:
        pass

    def get_supervisor_chain(self, llm, supervisor_system_prompt: str):
        supervisor_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", supervisor_system_prompt),
                ("human", "<messages>{messages}</messages>"),
            ]
        )
        return supervisor_prompt | llm

    @abstractmethod
    def get_reporter(self, state: MessagesState) -> Command[Literal["supervisor"]]:
        pass

    def get_reporter_tools(self) -> list:
        return []
