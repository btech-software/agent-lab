<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Cloud-native framework for building, simulating and testing LLM agents</h3>

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/btech-agent-lab.svg)](https://pypi.org/project/btech-agent-lab/)
[![Continuous Integration](https://github.com/btech-software/agent-lab/actions/workflows/build.yml/badge.svg)](https://github.com/btech-software/agent-lab/actions/workflows/build.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=btech-software_agent-lab&metric=alert_status)](https://sonarcloud.io/dashboard?id=btech-software_agent-lab)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=btech-software_agent-lab&metric=coverage)](https://sonarcloud.io/component_measures?metric=coverage&selected=btech-software_agent-lab%3Aapp&id=btech-software_agent-lab)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009485.svg?logo=fastapi&logoColor=white)](#key-features)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/btech-software/agent-lab/blob/main/LICENSE)

</div>

---

### Table of Contents
- [What is Agent-Lab?](#what-is-agent-lab)
- [Install](#install)
- [Quickstart](#quickstart)
- [How it works](#how-it-works)
- [Project Principles](#project-principles)
- [Key Features](#key-features)
- [MCP Server](#mcp-server)
- [Reference Implementation](#reference-implementation)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## What is Agent-Lab?

**Agent-Lab is a cloud-native Python framework for building, simulating and testing LLM agents on top of FastAPI, LangChain/LangGraph and PostgreSQL.**

You `pip install` it as a library, define your agents by extending its base classes, and assemble a production-ready FastAPI application with a single `create_app()` call — no need to fork or edit the framework. Everything an agent needs is included: a REST API, an MCP server, relational and vector persistence, agent memory (LangGraph checkpoints), OpenTelemetry observability, and a batteries-included simulation and testing harness with LLM-as-judge evaluation.

Agent-Lab covers three things well:

- **🏗️ Build** — Define agents by subclassing `WorkflowAgentBase` (LangGraph state graphs) and registering them with a decorator. `create_app()` wires up the REST API, MCP server, persistence, auth and observability around them. Extend via subclassing and configuration, never by editing framework code.
- **🧪 Simulate** — Exercise agents end-to-end against live LLMs with conversational scenarios (a user simulator + judge agent) and dataset-driven experiments, scored by an LLM-as-judge and tracked over time in [Langfuse](https://langfuse.com/) and [LangWatch](https://langwatch.ai/).
- **✅ Test** — Validate every change with an integration suite that spins up real infrastructure (Postgres, Redis, Keycloak, embeddings, headless Chrome) via testcontainers.

The repository also ships a complete **reference implementation** — a standalone, deployable app with a set of ready-to-use agents (RAG, browser automation, voice memos, vision, multi-agent supervisors) — that doubles as a working example of how to consume the framework. See [Reference Implementation](#reference-implementation).

---

## Install

```bash
pip install btech-agent-lab
```

Requires **Python 3.12+**. Agents are served through FastAPI and persist to PostgreSQL (relational data, pgvector embeddings, and LangGraph checkpoints); see the [Setup guide](https://github.com/btech-software/agent-lab/blob/main/doc/SETUP.md) for provisioning those in development or production.

---

## Quickstart

Scaffold a complete, runnable project from the bundled [project template](https://github.com/btech-software/agent-lab/tree/main/cookiecutter):

```bash
uvx cookiecutter gh:btech-software/agent-lab --directory cookiecutter
```

Answer the prompts (project name, optional docker / GitHub Actions / testcontainers support) and you get a ready-made thin consumer of the framework:

```
my-agent-app/
├── my_agent_app/
│   ├── main.py              # app = create_app(container=..., scan_packages=[...])
│   ├── core/container.py    # your DI container — add providers here
│   ├── agents/              # example echo agent + single-node ReAct workflow agent
│   └── mcp/                 # example MCP tool and prompt, exposed at /mcp
├── config-dev.yml / config-test.yml / config-docker.yml
├── tests/                   # no-container smoke tests (+ optional testcontainers suite)
├── compose.yml              # app + postgres (pgvector) + redis + vault
└── docker/, .github/, Makefile, pyproject.toml
```

Run it:

```bash
cd my-agent-app
uv lock && uv sync --group dev --group test
make test_unit                  # boots the app with no infrastructure needed
docker compose up --build -d    # full local stack
curl http://localhost:18000/status/liveness
```

Your agents are reachable over the REST API (`/agents`, `/messages`, ...), exposed through the MCP server at `/mcp`, and the interactive OpenAPI docs live at `/docs`.

Prefer wiring the app by hand? Add `btech-agent-lab` to any project, subclass the agent base classes, register them with `@discoverable_agent`, and call `create_app()` — the [Developer's Guide](https://github.com/btech-software/agent-lab/blob/main/doc/DEV_GUIDE.md) walks through the manual path, configuration, the DI container, and routers.

---

## How it works

**Tech stack:** Python 3.12, FastAPI, LangChain/LangGraph, PostgreSQL (3 databases: relational, vectors via pgvector, LangGraph checkpoints), Redis for pub/sub, Keycloak for auth, OpenTelemetry for observability.

**Architecture** — Clean Architecture with Dependency Injection:
- **Interface** — FastAPI routers + MCP server
- **Services** — Business logic, agent implementations
- **Domain** — SQLAlchemy models, repository interfaces
- **Infrastructure** — DB, auth, metrics (OpenTelemetry)

**The public API** — everything you need to consume Agent-Lab as a library is exported from the top-level `agent_lab` package and designed to be extended without editing framework code:

| Export | Purpose |
|---|---|
| `create_app(...)` | Composition root — builds the FastAPI app from your agents, container, config and routers. |
| `discoverable_agent` | Decorator that registers an `AgentBase` subclass under an `agent_type`. |
| `AgentBase`, `WorkflowAgentBase`, `SupervisedWorkflowAgentBase`, `WebAgentBase`, `ContactSupportAgentBase` | Base classes to extend, from simple message handlers to multi-agent supervisors. |
| `Container` | Subclass to add your own providers (services, MCP registrars, tracing backends). |
| `ConfigSource`, `YamlConfigSource`, `VaultConfigSource` | Supply configuration from YAML, Vault, or a custom source. |
| `RouterMount` | Mount extra FastAPI routers with their auth policy. |
| `McpRegistrar` | Extend the MCP server with additional tools. |

**Agent system** — Agents extend `WorkflowAgentBase` (which uses LangGraph state graphs). The hierarchy goes from simple (echo, adaptive RAG) to complex (coordinator-planner-supervisor multi-agent). Agents process messages, have configurable settings (Jinja2-templated prompts), and persist state in the checkpoints database. Registering an agent with `@discoverable_agent` makes it discoverable, resolvable through the DI container, and valid at the API — no manual registry or schema edits required.

---

## Project Principles

- Give researchers and developers a framework with everything they need to build, test, and experiment with LLM agents, plus ready-to-use reference implementations.
- Extend through the public API — subclassing, decorators and configuration — never by editing framework code.
- Expose an MCP server for agent discovery, conversation history, and agent-to-agent communication.
- Ship with integration and simulation test suites so every agent change is validated automatically.
- Provide full observability through logs, metrics, and traces for explainability and evaluation.
- Run anywhere with a cloud-native architecture built for containerized deployment and horizontal scaling.

---

## Key Features

- **Agent Framework**: Build agents by extending base classes and assembling the app with `create_app()`; discover them via package scanning or [entry points](https://github.com/btech-software/agent-lab/blob/main/doc/DEV_GUIDE.md).
- **Agent Simulations**: Evaluate agent behavior end-to-end with `langwatch-scenario` conversational simulations and dataset-driven experiments, scored by an LLM-as-judge and tracked in [Langfuse](https://langfuse.com/) and [LangWatch](https://langwatch.ai/). See the [testing guide](https://github.com/btech-software/agent-lab/blob/main/doc/TESTS.md).
- **Integration Testing**: Ensure reliability and correctness with a comprehensive [integration test suite](https://github.com/btech-software/agent-lab/blob/main/doc/TESTS.md) backed by testcontainers.
- **REST API**: Manage integrations with AI suppliers, LLM settings, agents, and conversation histories through the built-in [REST API](https://github.com/btech-software/agent-lab/blob/main/doc/REST_API.md).
- **MCP Server**: Utilize the [Model Context Protocol (MCP) server](https://github.com/btech-software/agent-lab/blob/main/doc/MCP.md) for agent discovery, dialog history, and agent-to-agent communication.
- **Observability**: Obtain detailed insights through logs, metrics, and traces powered by [OpenTelemetry](https://github.com/btech-software/agent-lab/blob/main/doc/OTEL.md), with reference implementations for [Grafana](https://github.com/btech-software/agent-lab/blob/main/doc/otel/GRAFANA.md) and [OpenSearch Dashboards](https://github.com/btech-software/agent-lab/blob/main/doc/otel/OPENSEARCH.md).
- **Relational Persistence**: Store data reliably using PostgreSQL to support the [entity domain model](https://github.com/btech-software/agent-lab/blob/main/doc/DOMAIN.md) for prompts, agent-specific settings, conversations, and more.
- **Secrets Management**: Securely store and retrieve secrets with [Vault](https://github.com/btech-software/agent-lab/blob/main/doc/VAULT.md).
- **Vector Storage and Search**: Efficiently manage vector data using PgVector for similarity search and retrieval.
- **Agent Memory**: Use the PostgreSQL checkpointer to store and retrieve agent memory, enabling agents to maintain context across interactions.
- **Cloud-Native**: Optimized for cloud environments with Docker, Kubernetes, and [Terraform scripts](https://github.com/btech-software/agent-lab/blob/main/doc/SETUP.md) for streamlined deployment.

---

## MCP Server

Agent-Lab features a MCP Server that allows agent discovery (`get_agent_list` tool), dialog history (`get_message_list` tool) and agent-to-agent communication (`post_message` tool).

The following example shows MCP Server discovering and obtaining dialog history of a [supervised coder agent](https://github.com/btech-software/agent-lab/blob/main/notebooks/05_test_agent_type-multiagent-coder.ipynb) instance:

<div align="center">

![Claude Desktop Demo](https://raw.githubusercontent.com/btech-software/agent-lab/main/doc/claude_demo.gif)

</div>

Please refer to [MCP guide](https://github.com/btech-software/agent-lab/blob/main/doc/MCP.md) for more details.


**Note**: Claude Desktop is used only for demonstration purposes. This project is not affiliated with Anthropic AI.

---

## Reference Implementation

The repository ships a complete, deployable reference application (`agent_lab.main`) that registers every built-in agent — RAG, browser automation, voice memos, vision, and multi-agent supervisors. It's both a product you can run and the canonical example of how to consume the framework.

You can run it in two ways:

```bash
# As a standalone app (the reference implementation)
uvicorn agent_lab.main:app --reload
```

```bash
# Or with the bundled observability stack
docker compose -f compose-grafana.yml up --build      # Grafana
docker compose -f compose-opensearch.yml up --build    # OpenSearch Dashboards
```

It ships with Helm charts (`charts/`) for Kubernetes and Terraform scripts (`terraform/`) for provisioning cloud infrastructure — databases, auth realms, and secrets. See the [Setup guide](https://github.com/btech-software/agent-lab/blob/main/doc/SETUP.md) for details.

> Agent-Lab is the **generic base** for downstream reference implementations. Only generic, reusable capabilities belong in the framework; product-specific agents and services live in the apps that consume it.

---

## Documentation

The complete documentation lives in [`doc/`](https://github.com/btech-software/agent-lab/blob/main/doc/README.md),
organized around how you use Agent-Lab (in the spirit of the [Diátaxis](https://diataxis.fr/) framework):

- **[Your first agent](https://github.com/btech-software/agent-lab/blob/main/doc/TUTORIAL.md)** — scaffold, define, call over REST, watch the trace, expose an MCP tool: a complete 15-minute tutorial.
- **[Developer's Guide](https://github.com/btech-software/agent-lab/blob/main/doc/DEV_GUIDE.md)** — the flagship guide: two development models, configuration, DI, building agents, and every extension point.
- **[Researcher's Guide](https://github.com/btech-software/agent-lab/blob/main/doc/RESEARCHER_GUIDE.md)** — notebooks, experiments, and prototyping new agent behaviors.
- **[Testing & Simulations](https://github.com/btech-software/agent-lab/blob/main/doc/TESTS.md)** — the integration suite (testcontainers) and LLM-as-judge agent simulations.
- **Reference** — [REST API](https://github.com/btech-software/agent-lab/blob/main/doc/REST_API.md) · [Configuration](https://github.com/btech-software/agent-lab/blob/main/doc/CONFIGURATION.md) · [Entity Domain Model](https://github.com/btech-software/agent-lab/blob/main/doc/DOMAIN.md).
- **Build & Operate** — [MCP Server](https://github.com/btech-software/agent-lab/blob/main/doc/MCP.md) · [Observability](https://github.com/btech-software/agent-lab/blob/main/doc/OTEL.md) · [Deployment](https://github.com/btech-software/agent-lab/blob/main/doc/SETUP.md) · [Auth with Keycloak](https://github.com/btech-software/agent-lab/blob/main/doc/KEYCLOAK.md) · [Secrets with Vault](https://github.com/btech-software/agent-lab/blob/main/doc/VAULT.md).

---

## Contributing

Community support is greatly appreciated. If you encounter any issues or have suggestions for enhancements, please report them by creating an issue on our [GitHub Issues](https://github.com/btech-software/agent-lab/issues) page.

Refer to our [Developer's Guide](https://github.com/btech-software/agent-lab/blob/main/doc/DEV_GUIDE.md) for instructions on how to contribute to the project.

---

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/btech-software/agent-lab/blob/main/LICENSE) file for details.
