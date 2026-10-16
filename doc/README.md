<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Documentation</h3>

<p align="center">
  <em>Everything you need to build, evaluate, and deploy LLM agents</em><br>
  <strong>Type</strong> · Index &nbsp;|&nbsp; <strong>Audience</strong> · Everyone — start here
</p>

---

Agent-Lab is a cloud-native Python framework for building, simulating and testing LLM
agents on top of FastAPI, LangChain/LangGraph and PostgreSQL. `pip install
btech-agent-lab`, extend the agent base classes, and assemble a production-ready
application with a single `create_app()` call — REST API, MCP server, persistence,
auth and OpenTelemetry observability included.

The documentation is organized by **what you are trying to do**, in the spirit of the
[Diátaxis](https://diataxis.fr/) framework: *tutorials* when you are learning,
*guides* when you are working, *reference* when you need a fact. Pick your path:

| I want to… | Path |
|---|---|
| **Get started** | [Your first agent](TUTORIAL.md) → [Developer's Guide](DEV_GUIDE.md) |
| **Build an application** | [Developer's Guide](DEV_GUIDE.md) → [Configuration reference](CONFIGURATION.md) → [REST API reference](REST_API.md) → [MCP Server guide](MCP.md) |
| **Evaluate and research** | [Researcher's Guide](RESEARCHER_GUIDE.md) → [Testing & Simulations](TESTS.md) |
| **Deploy and operate** | [Deployment guide](SETUP.md) → [Observability](OTEL.md) → [Keycloak](KEYCLOAK.md) → [Vault](VAULT.md) |
| **Contribute** | [Developer's Guide](DEV_GUIDE.md#contributing) → [Entity Domain Model](DOMAIN.md) → [Acknowledgements](ACKNOWLEDGEMENT.md) |

---

## Tutorials

Learning-oriented: walk through end-to-end, don't deviate.

| Page | Description |
|---|---|
| [Your first agent](TUTORIAL.md) | Scaffold a project, define an agent, call it over REST, watch the trace, expose an MCP tool — in ~15 minutes. |

## Guides

Working-oriented: solve the problem you have right now.

| Page | Description |
|---|---|
| [Developer's Guide](DEV_GUIDE.md) | The flagship guide: two development models, configuration, DI, building agents, every extension point. |
| [MCP Server](MCP.md) | Expose agents to MCP clients (Claude Desktop, MCP Inspector); add tools and prompts. |
| [Testing & Simulations](TESTS.md) | Integration suite with testcontainers; LLM-as-judge agent simulations with Langfuse/LangWatch. |
| [Researcher's Guide](RESEARCHER_GUIDE.md) | Jupyter notebooks, experiments, and prototyping new agent behaviors. |
| [Deployment](SETUP.md) | Local Docker Compose stacks and production Kubernetes with Terraform + Helm. |
| [Auth with Keycloak](KEYCLOAK.md) | Realm, client and service-account setup; token flows the API expects. |
| [Secrets with Vault](VAULT.md) | How configuration secrets are stored, retrieved and rotated. |
| [Observability with Grafana](otel/GRAFANA.md) · [with OpenSearch](otel/OPENSEARCH.md) | Reference dashboards for the two bundled observability stacks. |

## Reference

Facts only: exact, complete, generated from the code.

| Page | Description |
|---|---|
| [Configuration reference](CONFIGURATION.md) | Every config key and environment variable, and how the active `ConfigSource` is chosen. |
| [REST API](REST_API.md) | The full endpoint catalog with request/response examples. |
| [Entity Domain Model](DOMAIN.md) | Entities, relationships and the three PostgreSQL databases. |

## Project

| Page | Description |
|---|---|
| [Acknowledgements](ACKNOWLEDGEMENT.md) | Contributors and third-party software. |
| [License](LICENSE.md) | MIT. |

---

#### What's next?

New to Agent-Lab? Start with **[Your first agent](TUTORIAL.md)** — a complete,
copy-paste walkthrough that ends with a running agent you can talk to over REST and
MCP.
