<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Your First Agent</h3>

<p align="center">
  <em>From zero to a running, observable agent — in about 15 minutes</em><br>
  <strong>Type</strong> · Tutorial &nbsp;|&nbsp; <strong>Audience</strong> · Newcomers to Agent-Lab
</p>

---

#### Table of Contents

- [What you'll build](#what-youll-build)
- [Prerequisites](#prerequisites)
- [1. Scaffold the project](#1-scaffold-the-project)
- [2. Understand what you got](#2-understand-what-you-got)
- [3. Test it before running it](#3-test-it-before-running-it)
- [4. Run the app](#4-run-the-app)
- [5. Talk to your agent over REST](#5-talk-to-your-agent-over-rest)
- [6. Watch the trace](#6-watch-the-trace)
- [7. Meet it in an MCP client](#7-meet-it-in-an-mcp-client)
- [What's next?](#whats-next)

---

## What you'll build

A complete, runnable **Agent-Lab application**: a FastAPI service that hosts an echo
agent, an MCP server, PostgreSQL persistence and OpenTelemetry instrumentation — all
scaffolded by one command, none of it hand-wired. Along the way you will create an
agent instance over REST, send it a message, and watch the framework's traces.

## Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- **Docker** (or another container runtime), running

No API keys are needed for this tutorial — the echo agent doesn't call an LLM. LLM-backed
agents come next (see [What's next?](#whats-next)).

---

## 1. Scaffold the project

```bash
uvx cookiecutter gh:btech-software/agent-lab --directory cookiecutter
```

Answer the prompts — the defaults give you a project named **My Agent App**:

```bash
cd my-agent-app
```

The scaffold is a thin **consumer** of the framework, not a fork. `btech-agent-lab`
is a regular dependency in `pyproject.toml`; your code lives next to it and extends it
through the public API.

## 2. Understand what you got

```
my-agent-app/
├── my_agent_app/
│   ├── main.py              # the composition root — one create_app() call
│   ├── core/container.py    # your DI container — add providers here
│   ├── agents/echo/agent.py # your first agent (echo)
│   └── mcp/tools.py         # your first MCP tool
├── config-dev.yml / config-test.yml / config-docker.yml
├── tests/                   # unit tests (no infra) + optional testcontainers suite
├── compose.yml              # app + postgres (pgvector) + redis + vault
└── Makefile, docker/, .github/, pyproject.toml
```

Open `my_agent_app/main.py` — this is the entire application:

```python
from agent_lab import create_app

from my_agent_app.core.container import Container

# An explicit scan_packages list replaces agent_lab's DEFAULT_SCAN_PACKAGES:
# only this project's agents, MCP tools, and prompts are discovered — none of
# the framework's built-in examples. Add "agent_lab.services.agent_types" or
# "agent_lab.interface.mcp" here if you want the built-ins back.
app = create_app(
    container=Container(),
    scan_packages=[
        "my_agent_app.agents",
        "my_agent_app.mcp",
    ],
)
```

And `my_agent_app/agents/echo/agent.py` — the agent itself:

```python
from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState

from agent_lab import AgentBase, AgentUtils, discoverable_agent
from agent_lab.interface.api.messages.schema import Message, MessageRequest
from agent_lab.services.tasks import TaskProgress


@discoverable_agent("my_agent_app_echo")
class EchoAgent(AgentBase):
    """Minimal agent: echoes the incoming message without calling an LLM."""

    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def create_default_settings(self, agent_id: str, schema: str):
        pass

    def get_input_params(self, message_request: MessageRequest, schema: str) -> dict:
        return message_request.model_dump()

    def process_message(self, message_request: MessageRequest, schema: str) -> Message:
        message_content, response_data = self.format_response(
            MessagesState(
                messages=[AIMessage(content=f"Echo: {message_request.message_content}")]
            )
        )

        self.task_notification_service.publish_update(
            task_progress=TaskProgress(
                agent_id=message_request.agent_id,
                status="completed",
                message_content=message_content,
                response_data=response_data,
            )
        )

        return Message(
            message_role="assistant",
            message_content=message_content,
            response_data=response_data,
            agent_id=message_request.agent_id,
        )
```

Two things to notice:

- **`@discoverable_agent("my_agent_app_echo")`** — that single decorator registers the
  class under an `agent_type`. No registry edits, no schema changes: the REST API
  validates `agent_type` against the registry dynamically.
- **`AgentUtils` is injected** through the constructor by the DI container. Declare
  more dependencies with `extra_deps=("my_provider",)` and add matching providers to
  `core/container.py` (see [Developer's Guide](DEV_GUIDE.md#building-agentic-workflows)).

## 3. Test it before running it

The scaffold's unit tests boot the whole application with **no infrastructure at all**:

```bash
uv lock && uv sync --group dev --group test
make test_unit
```

You get the integration flavor too — `make test_integration` spins up real Postgres,
Redis and Vault containers via testcontainers (Docker required).

## 4. Run the app

```bash
docker compose up --build -d
curl http://localhost:18000/status/liveness
```

The stack is the app (port **18000**), PostgreSQL with **pgvector** (three databases:
relational, vectors, LangGraph checkpoints), Redis for pub/sub status updates, and
Vault for secrets. The interactive OpenAPI docs live at
[http://localhost:18000/docs](http://localhost:18000/docs).

> Auth is disabled in the scaffold (`auth.enabled: false`). When you enable it, every
> request needs a bearer token — see [Auth with Keycloak](KEYCLOAK.md).

## 5. Talk to your agent over REST

Agents are *instances* of an implementation, created and configured through the API.
Create one:

```bash
curl -s -X POST http://localhost:18000/agents/create \
  -H "Authorization: Bearer not-applicable" \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "my-first-agent", "agent_type": "my_agent_app_echo"}' | jq
```

Copy the `id` from the response, then send it a message:

```bash
curl -s -X POST http://localhost:18000/messages/post \
  -H "Authorization: Bearer not-applicable" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_id": "<agent_id>",
        "message_role": "human",
        "message_content": "Hello, framework!"
      }' | jq
```

The reply comes back synchronously:

```json
{
  "message_role": "assistant",
  "message_content": "Echo: Hello, framework!",
  "agent_id": "<agent_id>",
  "id": "…"
}
```

That round-trip exercised the whole stack: REST request → registry lookup → DI
container → your agent → message persistence (and the reply is stored too — check
`POST /messages/list`). The full catalog is in the [REST API reference](REST_API.md).

## 6. Watch the trace

Agent-Lab's observability is just OpenTelemetry. When the environment variable
`OTEL_EXPORTER_OTLP_ENDPOINT` is set, the app exports OTLP traces/metrics/logs; when
it is unset, tracing is simply off — no code changes either way.

Run the framework's bundled Grafana stack (from the **framework repository**) and point
your app at its collector:

```bash
# In the agent-lab framework repo — collector on :4318, Grafana UI on :3000
docker compose -f compose-grafana.yml up --build

# Back in your project — restart the app with the endpoint set
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 docker compose up --build -d
```

Send another message, then open **Grafana** at
[http://localhost:3000](http://localhost:3000) (`admin`/`admin`) and explore the
**Agent-Lab** dashboard: the HTTP span, the SQL queries, and — for LLM-backed agents —
every model call with token counts. Prefer a hosted LLM-observability platform? Set
`LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (or `LANGWATCH_ENDPOINT`/
`LANGWATCH_API_KEY`) instead — details in the [Observability guide](OTEL.md).

## 7. Meet it in an MCP client

The scaffold already ships an MCP tool (`my_agent_app/mcp/tools.py`) exposed at
`/mcp`, alongside the framework's agent-discovery, history and messaging tools. Try it
with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
```

Connect to `http://localhost:18000/mcp` (Streamable HTTP), list the tools, and call
`my_agent_app_hello_tool`. The same server works with Claude Desktop and any MCP
client — see the [MCP Server guide](MCP.md).

---

## What's next?

| | Page |
|---|---|
| 🏗️ Build a real (LLM-backed) agent | [Developer's Guide — Building agentic workflows](DEV_GUIDE.md#building-agentic-workflows) |
| ⚙️ Configure databases, auth, secrets | [Configuration reference](CONFIGURATION.md) |
| 🌐 Full endpoint catalog | [REST API reference](REST_API.md) |
| 🧪 Evaluate agent behavior with an LLM judge | [Testing & Simulations](TESTS.md) |
| 🚀 Ship it | [Deployment guide](SETUP.md) |

| | Page |
|---|---|
| ⬅️ Previous | [Documentation hub](README.md) |
| ➡️ Next | [Developer's Guide](DEV_GUIDE.md) |
