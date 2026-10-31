from datetime import datetime
from pathlib import Path

from langgraph.prebuilt import create_react_agent

from agent_lab.infrastructure.metrics.tracing import (
    trace_agent_message,
    set_current_trace_io,
)
from agent_lab.interface.api.messages.schema import MessageRequest, Message
from agent_lab.services.agent_types.base import AgentUtils, AgentBase
from agent_lab.services.agent_types.registration import discoverable_agent


@discoverable_agent("react_rag")
class ReactRagAgent(AgentBase):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)
        self.graph_persistence_factory = agent_utils.graph_persistence_factory
        self.document_repository = agent_utils.document_repository

    def create_default_settings(self, agent_id: str, schema: str):
        current_dir = Path(__file__).parent
        prompt = self.read_file_content(
            f"{current_dir}/default_execution_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="execution_system_prompt",
            setting_value=prompt,
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

    def get_workflow(self, agent_id: str, schema: str):
        chat_model = self.get_chat_model(agent_id, schema)
        settings = self.agent_setting_service.get_agent_settings(agent_id, schema)
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }
        checkpointer = self.graph_persistence_factory.build_checkpoint_saver()

        template_vars = {
            "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
        }

        return create_react_agent(
            model=chat_model,
            prompt=self.parse_prompt_template(
                settings_dict, "execution_system_prompt", template_vars
            ),
            tools=[],
            checkpointer=checkpointer,
        )

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        query = message_request.message_content
        embeddings_model = self.get_embeddings_model(message_request.agent_id, schema)
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }
        collection_name = settings_dict["collection_name"]
        documents = self.document_repository.search(
            embeddings_model=embeddings_model,
            collection_name=collection_name,
            query=query,
            size=7,
            schema=schema,
        )
        context = "\n---\n".join(document.page_content for document in documents)
        return {
            "messages": [
                ("user", f"<query>{query}</query> <context>{context}</context>")
            ],
        }

    @trace_agent_message
    def process_message(self, message_request: MessageRequest, schema: str) -> Message:
        agent_id = message_request.agent_id
        workflow = self.get_workflow(agent_id, schema)
        config = {
            "configurable": {
                "thread_id": agent_id,
            }
        }
        inputs = self.get_input_params(message_request, schema)
        self.logger.info(f"Agent[{agent_id}] -> Input -> {inputs}")

        workflow_result = workflow.invoke(inputs, config)
        self.logger.info(f"Agent[{agent_id}] -> Result -> {workflow_result}")
        response_content, response_data = self.format_response(workflow_result)

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
            agent_id=message_request.agent_id,
        )
