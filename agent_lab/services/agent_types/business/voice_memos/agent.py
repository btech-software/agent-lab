import base64
import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from typing_extensions import Literal

from agent_lab.interface.api.messages.schema import MessageRequest
from agent_lab.services.agent_types.azure import AzureEntraIdOrganizationWorkflowBase
from agent_lab.services.agent_types.base import (
    SupervisedWorkflowAgentBase,
    AgentUtils,
    DecisionState,
)
from agent_lab.services.agent_types.business.voice_memos import (
    SUPERVISED_AGENTS,
    SUPERVISED_AGENT_CONFIGURATION,
    AZURE_CONTENT_ANALYST_TOOLS,
    AZURE_CONTENT_ANALYST_TOOLS_CONFIGURATION,
    COORDINATOR_TOOLS,
    COORDINATOR_TOOLS_CONFIGURATION,
    AZURE_COORDINATOR_TOOLS,
    AZURE_COORDINATOR_TOOLS_CONFIGURATION,
)
from agent_lab.services.agent_types.business.voice_memos.schema import (
    AudioAnalysisReport,
)
from agent_lab.services.agent_types.schema import SolutionPlan
from agent_lab.services.tasks import TaskProgress
from agent_lab.services.agent_types.registration import discoverable_agent

CURRENT_TIME_PATTERN = "%a %b %d %Y %H:%M:%S %z"


class AgentState(DecisionState):
    agent_id: str
    schema: str
    attachment_id: str
    audio_format: str
    audio_language_model: str
    query: str
    transcription: str
    next: str
    structured_report: dict
    coordinator_system_prompt: str
    planner_system_prompt: str
    supervisor_system_prompt: str
    supervisor_completion_prompt: str
    content_analyst_system_prompt: str
    reporter_system_prompt: str
    execution_plan: str
    remaining_steps: RemainingSteps


@discoverable_agent("voice_memos")
class VoiceMemosAgent(SupervisedWorkflowAgentBase):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def format_response(self, workflow_state: AgentState) -> (str, dict):
        response_data = {
            "agent_id": workflow_state.get("agent_id"),
            "attachment_id": workflow_state.get("attachment_id"),
            "audio_format": workflow_state.get("audio_format"),
            "audio_language_model": workflow_state.get("audio_language_model"),
            "structured_report": workflow_state.get("structured_report"),
            "query": workflow_state.get("query"),
            "transcription": workflow_state.get("transcription"),
            "execution_plan": workflow_state.get("execution_plan"),
        }
        return workflow_state.get("messages")[-1].content, response_data

    def get_workflow_builder(self, agent_id: str):
        workflow_builder = StateGraph(AgentState)
        workflow_builder.add_edge(START, "coordinator")
        workflow_builder.add_node("coordinator", self.get_coordinator)
        workflow_builder.add_node("planner", self.get_planner)
        workflow_builder.add_node("supervisor", self.get_supervisor)
        workflow_builder.add_node("reporter", self.get_reporter)
        workflow_builder.add_node("content_analyst", self.get_content_analyst)
        return workflow_builder

    def create_default_settings(self, agent_id: str, schema: str):
        current_dir = Path(__file__).parent

        supervisor_prompt = self.read_file_content(
            f"{current_dir}/default_supervisor_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="supervisor_system_prompt",
            setting_value=supervisor_prompt,
            schema=schema,
        )

        supervisor_completion_prompt = self.read_file_content(
            f"{current_dir}/default_supervisor_completion_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="supervisor_completion_prompt",
            setting_value=supervisor_completion_prompt,
            schema=schema,
        )

        coordinator_prompt = self.read_file_content(
            f"{current_dir}/default_coordinator_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="coordinator_system_prompt",
            setting_value=coordinator_prompt,
            schema=schema,
        )

        content_analyst_prompt = self.read_file_content(
            f"{current_dir}/default_content_analyst_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="content_analyst_system_prompt",
            setting_value=content_analyst_prompt,
            schema=schema,
        )

        planner_prompt = self.read_file_content(
            f"{current_dir}/default_planner_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="planner_system_prompt",
            setting_value=planner_prompt,
            schema=schema,
        )

        reporter_prompt = self.read_file_content(
            f"{current_dir}/default_reporter_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="reporter_system_prompt",
            setting_value=reporter_prompt,
            schema=schema,
        )

        audio_language_model = self.read_file_content(
            f"{current_dir}/default_audio_language_model.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="audio_language_model",
            setting_value=audio_language_model,
            schema=schema,
        )

        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="audio_format",
            setting_value="mp3",
            schema=schema,
        )

        self.create_decision_settings(agent_id, schema)

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }
        if "supervisor_completion_prompt" not in settings_dict:
            # agents created before this setting existed use the packaged default
            settings_dict["supervisor_completion_prompt"] = self.read_file_content(
                f"{Path(__file__).parent}/default_supervisor_completion_prompt.txt"
            )

        template_vars = {
            "CURRENT_TIME": datetime.now().strftime(CURRENT_TIME_PATTERN),
            "SUPERVISED_AGENTS": SUPERVISED_AGENTS,
            "SUPERVISED_AGENT_CONFIGURATION": SUPERVISED_AGENT_CONFIGURATION,
            "COORDINATOR_TOOLS": COORDINATOR_TOOLS,
            "COORDINATOR_TOOLS_CONFIGURATION": COORDINATOR_TOOLS_CONFIGURATION,
            "CONTENT_ANALYST_TOOLS": [],
            "CONTENT_ANALYST_TOOLS_CONFIGURATION": {},
            "HAS_AUDIO_ATTACHMENT": message_request.attachment_id is not None,
        }

        return {
            "agent_id": message_request.agent_id,
            "schema": schema,
            "attachment_id": message_request.attachment_id,
            "audio_language_model": settings_dict.get("audio_language_model"),
            "audio_format": settings_dict.get("audio_format"),
            "query": message_request.message_content,
            "structured_report": None,
            **self.get_decision_params(settings_dict),
            "content_analyst_system_prompt": self.parse_prompt_template(
                settings_dict, "content_analyst_system_prompt", template_vars
            ),
            "coordinator_system_prompt": self.parse_prompt_template(
                settings_dict, "coordinator_system_prompt", template_vars
            ),
            "planner_system_prompt": self.parse_prompt_template(
                settings_dict, "planner_system_prompt", template_vars
            ),
            "supervisor_system_prompt": self.parse_prompt_template(
                settings_dict, "supervisor_system_prompt", template_vars
            ),
            "supervisor_completion_prompt": self.parse_prompt_template(
                settings_dict, "supervisor_completion_prompt", template_vars
            ),
            "reporter_system_prompt": self.parse_prompt_template(
                settings_dict, "reporter_system_prompt", template_vars
            ),
            "messages": [HumanMessage(content=message_request.message_content)],
        }

    def get_coordinator_tools(self) -> list:
        return [self.get_web_search_tool(), self.get_web_crawl_tool()]

    def get_coordinator(
        self, state: AgentState
    ) -> Command[Literal["planner", "__end__"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        attachment_id = state["attachment_id"]
        query = state["query"]
        coordinator_system_prompt = state["coordinator_system_prompt"]

        if attachment_id is None:
            # text requests pass the base accept/deny gate first
            gate = super().get_coordinator(state)
            if gate.goto == END:
                return gate

            self.logger.info(f"Agent[{agent_id}] -> Coordinator -> Query -> {query}")

            coordinator = create_react_agent(
                model=self.get_chat_model(agent_id, schema),
                tools=self.get_coordinator_tools(),
                prompt=self.get_worker_prompt(coordinator_system_prompt),
                name="coordinator",
            )
            response = coordinator.invoke(state)
            response_message = response["messages"][-1]

            self.task_notification_service.publish_update(
                task_progress=TaskProgress(
                    agent_id=agent_id,
                    status="in_progress",
                    message_content=response_message.content,
                )
            )

            self.logger.info(
                f"Agent[{agent_id}] -> Coordinator -> Response -> {response}"
            )

            return Command(
                goto=END,
                update={"messages": response["messages"]},
            )
        else:
            # https://platform.openai.com/docs/guides/audio?api-mode=chat&lang=python
            audio_format = state["audio_format"]
            audio_language_model = state["audio_language_model"]

            self.logger.info(
                f"Agent[{agent_id}] -> Coordinator -> Query -> {query} -> Attachment[{attachment_id}]"
            )

            self.task_notification_service.publish_update(
                task_progress=TaskProgress(
                    agent_id=agent_id,
                    status="in_progress",
                    message_content="Analyzing audio...",
                )
            )

            attachment = self.attachment_service.get_attachment_by_id(
                attachment_id, schema
            )
            audio_base64 = base64.b64encode(attachment.raw_content).decode()
            messages = [
                {"role": "system", "content": coordinator_system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": query},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_base64,
                                "format": audio_format,
                            },
                        },
                    ],
                },
            ]

            openai_client = self.get_openai_client(agent_id, schema)
            completion = openai_client.chat.completions.create(
                model=audio_language_model, modalities=["text"], messages=messages
            )
            response = completion.choices[0].message
            transcription = response.content

            self.task_notification_service.publish_update(
                task_progress=TaskProgress(
                    agent_id=agent_id,
                    status="in_progress",
                    message_content=f"{transcription}",
                )
            )

            self.logger.info(
                f"Agent[{agent_id}] -> Coordinator -> Response -> {response}"
            )
            return Command(
                goto=self.coordinator_accept_node,
                update={
                    "messages": [
                        AIMessage(
                            content=f"Transcription: '{transcription}'",
                            name="coordinator",
                        )
                    ],
                    "transcription": transcription,
                },
            )

    def get_planner(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        transcription = state["transcription"]
        planner_system_prompt = state["planner_system_prompt"]

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Planning how to reply...",
            )
        )

        self.logger.info(
            f"Agent[{agent_id}] -> Planner -> Query -> {query} -> Transcription -> {transcription}"
        )
        chat_model = (
            self.get_chat_model(agent_id, schema)
            .bind_tools(self.get_planner_tools())
            .with_structured_output(SolutionPlan)
        )
        response = self.get_planner_chain(
            llm=chat_model, planner_system_prompt=planner_system_prompt
        ).invoke(
            {
                "query": f"User instructions: {query}\n\nAudio transcription: {transcription}"
            }
        )

        plain_response = json.dumps(response)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response.get("thought"),
            )
        )
        self.logger.info(f"Agent[{agent_id}] -> Planner -> Response -> {response}")

        return Command(
            update={
                "messages": [AIMessage(content=plain_response, name="planner")],
                "execution_plan": response,
            },
            goto="supervisor",
        )

    def get_coordinator_context(self, state: AgentState) -> dict:
        context = super().get_coordinator_context(state)
        messages = state["messages"]
        last_human = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)),
            default=len(messages),
        )
        if last_human > 0:
            context["conversation"] = "\n".join(
                f"{message.type}: {message.content}"
                for message in messages[:last_human]
            )
        return context

    def get_supervisor(
        self, state: AgentState
    ) -> Command[Literal[*SUPERVISED_AGENTS, "__end__"]]:
        if state["structured_report"] is not None:
            return Command(goto=END)
        return super().get_supervisor(state)

    def get_supervised_agents_configuration(self) -> dict:
        return SUPERVISED_AGENT_CONFIGURATION

    def get_reporter_chain(self, llm, reporter_system_prompt: str):
        structured_llm_generator = llm.bind_tools(
            self.get_reporter_tools()
        ).with_structured_output(AudioAnalysisReport)
        reporter_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", reporter_system_prompt),
                ("human", "<content_analysis>{content_analysis}</content_analysis>"),
            ]
        )
        return reporter_prompt | structured_llm_generator

    def get_reporter(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        messages = state["messages"]
        self.logger.info(f"Agent[{agent_id}] -> Reporter")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Generating structured report...",
            )
        )
        reporter_system_prompt = state["reporter_system_prompt"]
        response = self.get_reporter_chain(
            llm=self.get_chat_model(agent_id, schema),
            reporter_system_prompt=reporter_system_prompt,
        ).invoke({"content_analysis": messages[-1].content})
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Structured report generated: {response.get('main_topic')}...",
            )
        )
        self.logger.info(f"Agent[{agent_id}] -> Supervisor -> Response -> {response}")
        return Command(
            update={"structured_report": response},
            goto="supervisor",
        )

    def get_content_analyst_tools(self) -> list:
        return []

    def get_content_analyst(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        self.logger.info(f"Agent[{agent_id}] -> Content Analyst")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Analysing transcription content...",
            )
        )
        content_analyst_system_prompt = state["content_analyst_system_prompt"]
        content_analyst = create_react_agent(
            model=self.get_chat_model(agent_id, schema),
            tools=self.get_content_analyst_tools(),
            prompt=self.get_worker_prompt(content_analyst_system_prompt),
            name="content_analyst",
        )
        response = content_analyst.invoke(state)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Content analysis complete: {response.get('messages')[-1].content}",
            )
        )
        self.logger.info(
            f"Agent[{agent_id}] -> Content Analyst -> Response -> {response}"
        )
        return Command(
            update={"messages": response["messages"]},
            goto="supervisor",
        )


@discoverable_agent("azure_entra_id_voice_memos")
class AzureEntraIdVoiceMemosAgent(
    AzureEntraIdOrganizationWorkflowBase, VoiceMemosAgent
):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def get_coordinator_tools(self) -> list:
        return [
            self.get_ical_attachment_tool(),
            self.get_web_search_tool(),
            self.get_web_crawl_tool(),
        ]

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        input_params = super().get_input_params(message_request, schema)
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }
        template_vars = {
            "CURRENT_TIME": datetime.now().strftime(CURRENT_TIME_PATTERN),
            "COORDINATOR_TOOLS": AZURE_COORDINATOR_TOOLS,
            "COORDINATOR_TOOLS_CONFIGURATION": AZURE_COORDINATOR_TOOLS_CONFIGURATION,
            "CONTENT_ANALYST_TOOLS": AZURE_CONTENT_ANALYST_TOOLS,
            "CONTENT_ANALYST_TOOLS_CONFIGURATION": AZURE_CONTENT_ANALYST_TOOLS_CONFIGURATION,
        }
        input_params["content_analyst_system_prompt"] = self.parse_prompt_template(
            settings_dict, "content_analyst_system_prompt", template_vars
        )
        return input_params

    def get_content_analyst_tools(self) -> list:
        return [self.get_person_search_tool(), self.get_person_details_tool()]


@discoverable_agent("fast_voice_memos")
class FastVoiceMemosAgent(VoiceMemosAgent):
    coordinator_accept_node = "content_analyst"

    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }

        template_vars = {
            "CURRENT_TIME": datetime.now().strftime(CURRENT_TIME_PATTERN),
            "COORDINATOR_TOOLS": [],
            "COORDINATOR_TOOLS_CONFIGURATION": {},
            "CONTENT_ANALYST_TOOLS": [],
            "CONTENT_ANALYST_TOOLS_CONFIGURATION": {},
            "HAS_AUDIO_ATTACHMENT": message_request.attachment_id is not None,
        }

        return {
            "agent_id": message_request.agent_id,
            "schema": schema,
            "attachment_id": message_request.attachment_id,
            "audio_language_model": settings_dict.get("audio_language_model"),
            "audio_format": settings_dict.get("audio_format"),
            "query": message_request.message_content,
            "structured_report": None,
            **self.get_decision_params(settings_dict),
            "content_analyst_system_prompt": self.parse_prompt_template(
                settings_dict, "content_analyst_system_prompt", template_vars
            ),
            "coordinator_system_prompt": self.parse_prompt_template(
                settings_dict, "coordinator_system_prompt", template_vars
            ),
            "messages": [HumanMessage(content=message_request.message_content)],
        }

    def get_workflow_builder(self, agent_id: str):
        workflow_builder = StateGraph(AgentState)
        workflow_builder.add_edge(START, "coordinator")
        workflow_builder.add_node("coordinator", self.get_coordinator)
        workflow_builder.add_node("content_analyst", self.get_content_analyst)
        return workflow_builder

    def get_coordinator(
        self, state: AgentState
    ) -> Command[Literal["content_analyst", "__end__"]]:
        # return annotation drives LangGraph's edge inference for this graph
        return super().get_coordinator(state)

    def get_content_analyst(self, state: AgentState) -> Command[Literal["__end__"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        self.logger.info(f"Agent[{agent_id}] -> Content Analyst")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Analysing transcription content...",
            )
        )
        content_analyst_system_prompt = state["content_analyst_system_prompt"]
        content_analyst = create_react_agent(
            model=self.get_chat_model(agent_id, schema),
            tools=self.get_content_analyst_tools(),
            prompt=self.get_worker_prompt(content_analyst_system_prompt),
            name="content_analyst",
            response_format=AudioAnalysisReport,
        )
        response = content_analyst.invoke(state)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Content analysis complete: {response.get('messages')[-1].content}",
            )
        )
        self.logger.info(
            f"Agent[{agent_id}] -> Content Analyst -> Response -> {response}"
        )
        return Command(
            update={
                "messages": response["messages"],
                "structured_report": response["structured_response"],
            },
            goto="__end__",
        )
