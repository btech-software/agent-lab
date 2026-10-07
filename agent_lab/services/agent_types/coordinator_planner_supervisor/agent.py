import ast
import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool, BaseTool
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import create_react_agent, InjectedState
from langgraph.types import Command
from typing_extensions import List, Annotated, Literal

from agent_lab.interface.api.messages.schema import MessageRequest
from agent_lab.services.agent_types.base import (
    DecisionState,
    SupervisedWorkflowAgentBase,
    AgentUtils,
    join_messages,
)
from agent_lab.services.agent_types.coordinator_planner_supervisor import (
    SUPERVISED_AGENTS,
    SUPERVISED_AGENT_CONFIGURATION,
)
from agent_lab.services.agent_types.schema import SolutionPlan
from agent_lab.services.tasks import TaskProgress
from agent_lab.services.agent_types.registration import discoverable_agent


class AgentState(DecisionState):
    agent_id: str
    schema: str
    query: str
    next: str
    collection_name: str
    coordinator_system_prompt: str
    planner_system_prompt: str
    supervisor_system_prompt: str
    researcher_system_prompt: str
    coder_system_prompt: str
    browser_system_prompt: str
    reporter_system_prompt: str
    deep_search_mode: bool
    execution_plan: str
    messages: Annotated[List, join_messages]
    remaining_steps: RemainingSteps


@discoverable_agent("coordinator_planner_supervisor")
class CoordinatorPlannerSupervisorAgent(SupervisedWorkflowAgentBase):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def format_response(self, workflow_state: AgentState) -> (str, dict):
        response_data = {
            "agent_id": workflow_state.get("agent_id"),
            "query": workflow_state.get("query"),
            "collection_name": workflow_state.get("collection_name"),
            "deep_search_mode": workflow_state.get("deep_search_mode"),
            "execution_plan": workflow_state.get("execution_plan"),
        }
        return workflow_state["messages"][-1].content, response_data

    def create_default_settings(self, agent_id: str, schema: str):
        current_dir = Path(__file__).parent

        coordinator_prompt = self.read_file_content(
            f"{current_dir}/default_coordinator_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="coordinator_system_prompt",
            setting_value=coordinator_prompt,
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

        supervisor_prompt = self.read_file_content(
            f"{current_dir}/default_supervisor_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="supervisor_system_prompt",
            setting_value=supervisor_prompt,
            schema=schema,
        )

        researcher_prompt = self.read_file_content(
            f"{current_dir}/default_researcher_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="researcher_system_prompt",
            setting_value=researcher_prompt,
            schema=schema,
        )

        coder_prompt = self.read_file_content(
            f"{current_dir}/default_coder_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="coder_system_prompt",
            setting_value=coder_prompt,
            schema=schema,
        )

        browser_prompt = self.read_file_content(
            f"{current_dir}/default_browser_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="browser_system_prompt",
            setting_value=browser_prompt,
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

        collection_name = self.read_file_content(
            f"{current_dir}/default_collection_name.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="collection_name",
            setting_value=collection_name,
            schema=schema,
        )

        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="deep_search_mode",
            setting_value="False",
            schema=schema,
        )

        self.create_decision_settings(agent_id, schema)

    def get_supervised_agents_configuration(self) -> dict:
        return SUPERVISED_AGENT_CONFIGURATION

    def get_workflow_builder(self, agent_id: str):
        workflow_builder = StateGraph(AgentState)
        workflow_builder.add_edge(START, "coordinator")
        workflow_builder.add_node("coordinator", self.get_coordinator)
        workflow_builder.add_node("planner", self.get_planner)
        workflow_builder.add_node("supervisor", self.get_supervisor)
        workflow_builder.add_node("researcher", self.get_researcher)
        workflow_builder.add_node("coder", self.get_coder)
        workflow_builder.add_node("browser", self.get_browser)
        workflow_builder.add_node("reporter", self.get_reporter)
        return workflow_builder

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }

        deep_search_mode = settings_dict["deep_search_mode"] == "True"

        template_vars = {
            "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
            "DEEP_SEARCH_MODE": deep_search_mode,
            "SUPERVISED_AGENTS": SUPERVISED_AGENTS,
            "SUPERVISED_AGENT_CONFIGURATION": SUPERVISED_AGENT_CONFIGURATION,
        }

        return {
            "agent_id": message_request.agent_id,
            "schema": schema,
            "query": message_request.message_content,
            "collection_name": settings_dict["collection_name"],
            "deep_search_mode": deep_search_mode,
            "coordinator_system_prompt": self.parse_prompt_template(
                settings_dict, "coordinator_system_prompt", template_vars
            ),
            "planner_system_prompt": self.parse_prompt_template(
                settings_dict, "planner_system_prompt", template_vars
            ),
            "supervisor_system_prompt": self.parse_prompt_template(
                settings_dict, "supervisor_system_prompt", template_vars
            ),
            "researcher_system_prompt": self.parse_prompt_template(
                settings_dict, "researcher_system_prompt", template_vars
            ),
            "coder_system_prompt": self.parse_prompt_template(
                settings_dict, "coder_system_prompt", template_vars
            ),
            "browser_system_prompt": self.parse_prompt_template(
                settings_dict, "browser_system_prompt", template_vars
            ),
            "reporter_system_prompt": self.parse_prompt_template(
                settings_dict, "reporter_system_prompt", template_vars
            ),
            **self.get_decision_params(settings_dict),
            "messages": [HumanMessage(content=message_request.message_content)],
        }

    def get_coordinator(
        self, state: AgentState
    ) -> Command[Literal["planner", "__end__"]]:
        # return annotation drives LangGraph's edge inference
        return super().get_coordinator(state)

    def get_supervisor(
        self, state: AgentState
    ) -> Command[Literal[*SUPERVISED_AGENTS, "__end__"]]:
        # return annotation drives LangGraph's edge inference
        return super().get_supervisor(state)

    def get_planner(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Planning how to reply...",
            )
        )
        query = state["query"]
        planner_system_prompt = state["planner_system_prompt"]
        deep_search_mode = state["deep_search_mode"]
        self.logger.info(
            f"Agent[{agent_id}] -> Planner -> Query -> {query} -> Deep Search Mode -> {deep_search_mode}"
        )
        chat_model = (
            self.get_chat_model(agent_id, schema)
            .bind_tools(self.get_planner_tools())
            .with_structured_output(SolutionPlan)
        )

        if deep_search_mode:
            search_response = self.get_web_search_tool().invoke({"query": query})
            search_results = f"{json.dumps([{'title': elem['title'], 'content': elem['snippet']} for elem in search_response], ensure_ascii=False)}"
            response = self.get_planner_chain(
                llm=chat_model,
                planner_system_prompt=planner_system_prompt,
                search_results=search_results,
            ).invoke({"query": query, "search_results": search_results})
        else:
            response = self.get_planner_chain(
                llm=chat_model, planner_system_prompt=planner_system_prompt
            ).invoke({"query": query})

        self.logger.info(f"Agent[{agent_id}] -> Planner -> Response -> {response}")
        plain_response = json.dumps(response)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response.get("thought"),
            )
        )

        return Command(
            update={
                "messages": [AIMessage(content=plain_response, name="planner")],
                "execution_plan": response,
            },
            goto="supervisor",
        )

    def get_research_knowledge_base_tool(
        self, state: Annotated[dict, InjectedState]
    ) -> BaseTool:
        @tool("research_knowledge_base")
        def retrieve_tool_call():
            """
            Consult the knowledge base. Use this to perform research on known knowledge bases.

            Returns:
                str: Documents retrieved from knowledge base separated by line breaks.
            """
            agent_id = state["agent_id"]
            schema = state["schema"]
            collection_name = state["collection_name"]
            execution_plan = state["execution_plan"]
            embeddings_model = self.get_embeddings_model(agent_id, schema)
            thought_docs = self.document_repository.search(
                embeddings_model=embeddings_model,
                collection_name=collection_name,
                query=execution_plan["thought"],
                size=3,
            )
            return "\n\n".join([doc.page_content for doc in thought_docs])

        return retrieve_tool_call

    def get_researcher(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        deep_search_mode = state["deep_search_mode"]
        researcher_system_prompt = state["researcher_system_prompt"]

        self.logger.info(
            f"Agent[{agent_id}] -> Researcher -> Deep Search Mode -> {deep_search_mode}"
        )

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Researching the topic...",
            )
        )

        if deep_search_mode:
            tools = [self.get_web_search_tool(), self.get_web_crawl_tool()]
        else:
            tools = [self.get_research_knowledge_base_tool(state)]

        chat_model = self.get_chat_model(agent_id, schema)
        researcher = create_react_agent(
            model=chat_model,
            tools=tools,
            prompt=researcher_system_prompt,
        )
        response = researcher.invoke(state)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response["messages"][-1].content,
            )
        )

        self.logger.info(f"Agent[{agent_id}] -> Researcher -> Response -> {response}")
        return Command(
            update={"messages": response["messages"]},
            goto="supervisor",
        )

    @staticmethod
    def _analyze_ast(tree):
        collectors = {
            "imports": [],
            "functions": [],
            "classes": [],
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = ", ".join(alias.name for alias in node.names)
                collectors["imports"].append(f"{module}: {names}" if module else names)
            elif isinstance(node, ast.FunctionDef):
                args = ", ".join(arg.arg for arg in node.args.args)
                collectors["functions"].append(f"{node.name}({args})")
            elif isinstance(node, ast.ClassDef):
                bases = ", ".join(
                    getattr(b, "id", getattr(b, "attr", "?")) for b in node.bases
                )
                collectors["classes"].append(
                    f"{node.name}({bases})" if bases else node.name
                )
        return collectors

    def get_python_tool(self) -> BaseTool:
        @tool("python_tool")
        def python_tool_call(
            code: Annotated[str, "The python3 code to analyze."],
        ):
            """Use this to analyze python3 code structure and validate syntax.
            This tool parses the code and returns its structure (imports, functions, classes)
            without executing it. Use it to verify code correctness and understand its components."""

            if not isinstance(code, str):
                error_msg = f"Invalid input: code must be a string, got {type(code)}"
                self.logger.error(error_msg)
                return f"Error analyzing code: {error_msg}"

            self.logger.info("Analyzing Python code")
            try:
                tree = ast.parse(code)
                result = self._analyze_ast(tree)
                summary = ["Syntax: valid", f"Lines: {len(code.splitlines())}"]
                for label, items in result.items():
                    if items:
                        summary.append(f"{label.capitalize()}: {'; '.join(items)}")
                analysis = "\n".join(summary)
                self.logger.info("Code analysis successful")
                return f"Analysis of:\n```python\n{code}\n```\n{analysis}"
            except SyntaxError as e:
                self.logger.error(f"Syntax error: {e}")
                return f"Syntax error in code:\n```python\n{code}\n```\nError at line {e.lineno}: {e.msg}"

        return python_tool_call

    def get_coder(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        coder_system_prompt = state["coder_system_prompt"]

        self.logger.info(f"Agent[{agent_id}] -> Coder")

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Generating code...",
            )
        )

        chat_model = self.get_chat_model(agent_id, schema)
        coder = create_react_agent(
            model=chat_model,
            tools=[self.get_bash_tool(), self.get_python_tool()],
            prompt=coder_system_prompt,
        )

        response = coder.invoke(state)
        self.logger.info(f"Agent[{agent_id}] -> Coder -> Response -> {response}")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response["messages"][-1].content,
            )
        )
        return Command(
            update={"messages": response["messages"]},
            goto="supervisor",
        )

    def get_browser(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        browser_system_prompt = state["browser_system_prompt"]

        self.logger.info(f"Agent[{agent_id}] -> Browser")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Browsing the web for information...",
            )
        )

        chat_model = self.get_chat_model(agent_id, schema)
        browser = create_react_agent(
            model=chat_model,
            tools=[self.get_web_browser_tool(agent_id, schema)],
            prompt=browser_system_prompt,
        )

        response = browser.invoke(state)
        self.logger.info(f"Agent[{agent_id}] -> Browser -> Response -> {response}")
        command = Command(
            update={"messages": response["messages"]},
            goto="supervisor",
        )
        return command

    def get_reporter(self, state: AgentState) -> Command[Literal["supervisor"]]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        self.logger.info(f"Agent[{agent_id}] -> Reporter")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Generating report...",
            )
        )
        reporter_system_prompt = state["reporter_system_prompt"]
        chat_model = self.get_chat_model(agent_id, schema)
        reporter = create_react_agent(
            model=chat_model,
            tools=self.get_reporter_tools(),
            prompt=reporter_system_prompt,
        )
        response = reporter.invoke(state)
        command = Command(
            update={"messages": response["messages"]},
            goto="supervisor",
        )
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response["messages"][-1].content,
            )
        )
        self.logger.info(f"Agent[{agent_id}] -> Reporter -> Response -> {response}")
        return command
