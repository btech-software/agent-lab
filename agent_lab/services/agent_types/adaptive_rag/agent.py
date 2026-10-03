from datetime import datetime
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.constants import START, END
from langgraph.graph import StateGraph, MessagesState
from langgraph.managed import RemainingSteps
from typesafe_sdk import Noul, TypeSafeClient
from typing_extensions import Annotated, Callable, List, Literal

from agent_lab.interface.api.messages.schema import MessageRequest
from agent_lab.services.agent_types.adaptive_rag.schema import (
    GradeDocuments,
    GradeAnswer,
    GenerateAnswer,
)
from agent_lab.services.agent_types.base import (
    join_messages,
    AgentUtils,
    WebAgentBase,
)
from agent_lab.services.tasks import TaskProgress
from agent_lab.services.agent_types.registration import discoverable_agent

# minimum jev noul probability for a 'yes' decision
JEV_DECISION_THRESHOLD = 0.5


class AgentState(MessagesState):
    agent_id: str
    schema: str
    query: str
    collection_name: str
    generation: str
    connection: str
    documents: List
    messages: Annotated[List, join_messages]
    remaining_steps: RemainingSteps
    execution_system_prompt: str
    query_rewriter_system_prompt: str
    answer_grader_system_prompt: str
    retrieval_grader_system_prompt: str
    decision_engine: str
    jev_integration_id: str


@discoverable_agent("adaptive_rag")
class AdaptiveRagAgent(WebAgentBase):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def create_default_settings(self, agent_id: str, schema: str):
        current_dir = Path(__file__).parent

        execution_prompt = self.read_file_content(
            f"{current_dir}/default_execution_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="execution_system_prompt",
            setting_value=execution_prompt,
            schema=schema,
        )

        query_rewriter_prompt = self.read_file_content(
            f"{current_dir}/default_query_rewriter_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="query_rewriter_system_prompt",
            setting_value=query_rewriter_prompt,
            schema=schema,
        )

        answer_grader_prompt = self.read_file_content(
            f"{current_dir}/default_answer_grader_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="answer_grader_system_prompt",
            setting_value=answer_grader_prompt,
            schema=schema,
        )

        retrieval_grader_prompt = self.read_file_content(
            f"{current_dir}/default_retrieval_grader_system_prompt.txt"
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="retrieval_grader_system_prompt",
            setting_value=retrieval_grader_prompt,
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

        # grading decisions: "llm" (default) or "jev" via a typesafe_api_v1 integration
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="decision_engine",
            setting_value="llm",
            schema=schema,
        )
        self.agent_setting_service.create_agent_setting(
            agent_id=agent_id,
            setting_key="jev_integration_id",
            setting_value="",
            schema=schema,
        )

    def format_response(self, workflow_state: AgentState) -> (str, dict):
        return workflow_state.get("generation"), {
            "agent_id": workflow_state.get("agent_id"),
            "query": workflow_state.get("query"),
            "collection_name": workflow_state.get("collection_name"),
            "generation": workflow_state.get("generation"),
            "connection": workflow_state.get("connection"),
            "documents": [
                document.page_content for document in workflow_state.get("documents")
            ],
        }

    def ask_jev(self, state: AgentState, jev_state: dict, instructions: str) -> bool:
        integration = self.integration_service.get_integration_by_id(
            state["jev_integration_id"], state["schema"]
        )
        api_endpoint, api_key = self.get_integration_credentials(integration)
        with TypeSafeClient(api_key=api_key, base_url=api_endpoint) as client:
            answers = client.system_one(
                state=jev_state,
                questions={"decision": Noul(instructions=instructions)},
            ).answers
        return answers["decision"].noul >= JEV_DECISION_THRESHOLD

    def decide(
        self,
        state: AgentState,
        llm_decision: Callable[[], bool],
        jev_state: dict,
        instructions: str,
    ) -> bool:
        if state.get("decision_engine") == "jev":
            try:
                return self.ask_jev(state, jev_state, instructions)
            except Exception as e:
                self.logger.warning(
                    f"Agent[{state['agent_id']}] -> JEV decision failed, falling back to LLM -> {e}"
                )
        return llm_decision()

    def get_query_rewriter(self, chat_model, query_rewriter_system_prompt):
        re_write_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", query_rewriter_system_prompt),
                (
                    "human",
                    "Here is the initial query: <query>{query}</query> \n Formulate an improved query.",
                ),
            ]
        )

        return re_write_prompt | chat_model | StrOutputParser()

    def get_answer_grader(self, llm, answer_grader_system_prompt):
        # LLM with function call
        structured_llm_grader = llm.with_structured_output(GradeAnswer)

        answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", answer_grader_system_prompt),
                ("human", "<query>{query}</query>\n<answer>{generation}</answer>"),
            ]
        )

        return answer_prompt | structured_llm_grader

    def grade_generation_v_documents_and_question(
        self, state: AgentState
    ) -> Literal["complete_answer", "incomplete_answer"]:
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        chat_model = self.get_chat_model(agent_id, schema)
        generation = state["generation"]
        remaining_steps = state["remaining_steps"]
        answer_grader_system_prompt = state["answer_grader_system_prompt"]
        limit_remaining_steps = 10

        def llm_decision() -> bool:
            score = self.get_answer_grader(
                chat_model, answer_grader_system_prompt
            ).invoke({"query": query, "generation": generation})
            return score is not None and score["binary_score"] == "yes"

        # Check question-answering
        is_complete = self.decide(
            state,
            llm_decision,
            jev_state={"query": query, "answer": generation},
            instructions=answer_grader_system_prompt,
        )

        if is_complete or remaining_steps <= limit_remaining_steps:
            return "complete_answer"

        return "incomplete_answer"

    def get_workflow_builder(self, agent_id: str):
        workflow_builder = StateGraph(AgentState)

        # node definitions
        workflow_builder.add_node("retrieve", self.retrieve)
        workflow_builder.add_node("grade_documents", self.grade_documents)
        workflow_builder.add_node("generate", self.generate)
        workflow_builder.add_node("transform_query", self.transform_query)

        # edge definitions
        workflow_builder.add_edge(START, "retrieve")
        workflow_builder.add_edge("retrieve", "grade_documents")
        workflow_builder.add_edge("grade_documents", "generate")
        workflow_builder.add_edge("transform_query", "retrieve")
        workflow_builder.add_conditional_edges(
            "generate",
            self.grade_generation_v_documents_and_question,
            {
                "complete_answer": END,
                "incomplete_answer": "transform_query",
            },
        )

        return workflow_builder

    def get_rag_chain(self, llm, execution_system_prompt):
        structured_llm_generator = llm.with_structured_output(GenerateAnswer)
        generate_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", execution_system_prompt),
                (
                    "human",
                    "<query>{query}</query>\n<context>{context}</context>",
                ),
            ]
        )
        return generate_prompt | structured_llm_generator

    def generate(self, state: AgentState):
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        documents = state["documents"]
        execution_system_prompt = state["execution_system_prompt"]
        chat_model = self.get_chat_model(agent_id, schema)
        previous_messages = state["messages"]
        context = "\n---\n".join(document.page_content for document in documents)
        if len(previous_messages) > 5:
            token_limit = 10240
            prompt = (
                f"Summarize the text delimited by <context></context> using at most {token_limit} tokens.\n"
                f"<context>{previous_messages}</context>"
            )
            summary = chat_model.invoke(prompt)
            context = context + f"\n\nSummary previous messages:{summary}"
        else:
            context = context + f"\n\nPrevious messages:{previous_messages}"

        self.logger.info(f"Agent[{agent_id}] -> Generate -> Query -> {query}")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Generating response...",
            )
        )
        response = self.get_rag_chain(chat_model, execution_system_prompt).invoke(
            {"context": context, "query": query}
        )

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=response["generation"],
            )
        )

        response["messages"] = [
            self.create_thought_chain(
                human_input=query,
                ai_response=response["generation"],
                connection=response["connection"],
            )
        ]

        return response

    def get_retrieval_grader(self, chat_model, retrieval_grader_system_prompt):
        # LLM with function call
        structured_llm_grader = chat_model.with_structured_output(GradeDocuments)

        grade_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", retrieval_grader_system_prompt),
                (
                    "human",
                    "<document>{document}</document>\n<query>{query}</query>",
                ),
            ]
        )

        return grade_prompt | structured_llm_grader

    def grade_documents(self, state: AgentState):
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        documents = state["documents"]
        chat_model = self.get_chat_model(agent_id, schema)
        retrieval_grader_system_prompt = state["retrieval_grader_system_prompt"]
        filtered_docs = []
        self.logger.info(f"Agent[{agent_id}] -> Document Grader -> Query -> {query} ")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Grading documents relevance to query '{query}'...",
            )
        )
        for d in documents:

            def llm_decision() -> bool:
                score = self.get_retrieval_grader(
                    chat_model, retrieval_grader_system_prompt
                ).invoke({"query": query, "document": d.page_content})
                return score is not None and score["binary_score"] == "yes"

            if self.decide(
                state,
                llm_decision,
                jev_state={"query": query, "document": d.page_content},
                instructions=retrieval_grader_system_prompt,
            ):
                filtered_docs.append(d)

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Filtered out {len(documents) - len(filtered_docs)} documents. ",
            )
        )
        return {"documents": filtered_docs}

    def retrieve(self, state: AgentState):
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        collection_name = state["collection_name"]
        embeddings = self.get_embeddings_model(agent_id, schema)
        self.logger.info(
            f"Agent[{agent_id}] -> Retrieve -> Query -> {query} -- Collection -> {collection_name}"
        )
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Retrieving documents...",
            )
        )
        documents = self.document_repository.search(
            embeddings_model=embeddings,
            collection_name=collection_name,
            query=query,
            size=3,
        )

        return {"documents": documents}

    def transform_query(self, state: AgentState):
        agent_id = state["agent_id"]
        schema = state["schema"]
        query = state["query"]
        chat_model = self.get_chat_model(agent_id, schema)
        query_rewriter_system_prompt = state["query_rewriter_system_prompt"]
        self.logger.info(f"Agent[{agent_id}] -> Transform query -> Query -> {query}")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content="Transforming query for better semantic document match...",
            )
        )
        transformed_query = self.get_query_rewriter(
            chat_model, query_rewriter_system_prompt
        ).invoke({"query": query})
        messages = [
            self.create_thought_chain(
                human_input=query,
                ai_response=f"Transformed query: {transformed_query}",
                connection="Transformed query can help generating a better answer.",
            )
        ]
        self.logger.info(f"Agent[{agent_id}] -> Transform query -> Query -> {query}")
        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=agent_id,
                status="in_progress",
                message_content=f"Transformed query: `{transformed_query}` ",
            )
        )
        return {"query": transformed_query, "messages": messages}

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        settings = self.agent_setting_service.get_agent_settings(
            message_request.agent_id, schema
        )
        settings_dict = {
            setting.setting_key: setting.setting_value for setting in settings
        }

        template_vars = {
            "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
        }

        return {
            "agent_id": message_request.agent_id,
            "schema": schema,
            "query": message_request.message_content,
            "collection_name": settings_dict["collection_name"],
            "execution_system_prompt": self.parse_prompt_template(
                settings_dict, "execution_system_prompt", template_vars
            ),
            "query_rewriter_system_prompt": self.parse_prompt_template(
                settings_dict, "query_rewriter_system_prompt", template_vars
            ),
            "answer_grader_system_prompt": self.parse_prompt_template(
                settings_dict, "answer_grader_system_prompt", template_vars
            ),
            "retrieval_grader_system_prompt": self.parse_prompt_template(
                settings_dict, "retrieval_grader_system_prompt", template_vars
            ),
            "decision_engine": settings_dict.get("decision_engine", "llm"),
            "jev_integration_id": settings_dict.get("jev_integration_id", ""),
            "messages": [],
        }
