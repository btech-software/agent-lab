---
name: software-engineering
description: Use when the user asks about architecture, running, testing, linting, or building the project, about code conventions, about adding or registering agents, MCP tools, prompts, or registrars (the @discoverable_agent / @RegisterMcp* decorator framework and its discovery/bootstrap path), or about the agent simulation suites (scenario, Langfuse, LangWatch) and their observability platform integrations.
---

# Software Engineering

## Architecture

### Dependency Injection

All wiring is in `agent_lab/core/container.py` using `dependency-injector`. The `Container` class declares every service, repository, and agent as a provider. FastAPI endpoints receive dependencies via container wiring (configured in `wiring_config`). To add a new service, register it as a provider in the Container and add the endpoint module to wiring.

### Agent System

Agents are the core abstraction. The class hierarchy:

```
AgentBase (ABC)
├── WorkflowAgentBase          # LangGraph state graph + checkpointer
│   ├── ContactSupportAgentBase
│   └── WebAgentBase           # Adds browser automation + web search tools
│       └── SupervisedWorkflowAgentBase  # Coordinator → Planner → Supervisor pattern
└── TestEchoAgent              # Simple echo agent for testing
```

Key patterns:
- **AgentBase** (`agent_lab/services/agent_types/base.py`): Defines `create_default_settings`, `get_input_params`, `process_message` abstract methods. Also houses `AgentUtils` which bundles all shared dependencies (services, repos, config).
- **AgentRegistry** (`agent_lab/services/agent_types/registry.py`): Lazily maps string type keys (e.g. `"test_echo"`) to agent instances, resolved from the live `Container`. To register a new agent: decorate the `AgentBase` subclass with `@discoverable_agent("your_type")` from `agent_lab.services.agent_types.registration`, then make sure its module is discovered — either list its package in the `scan_packages=[...]` passed to `create_app()`, or advertise it via an `agent_lab.agents` entry point. If the agent needs dependencies beyond `agent_utils`, add providers for them to your `Container` and name them in `@discoverable_agent(..., extra_deps=("provider_name", ...))`; each name must match both the container provider attribute and the constructor kwarg.
- **WorkflowAgentBase**: Provides `get_workflow_builder()` → compiles LangGraph `StateGraph` with a PostgreSQL checkpointer. Handles `process_message` by invoking the graph and publishing progress via Redis (`TaskNotificationService`).
- **SupervisedWorkflowAgentBase**: Implements multi-role orchestration. `get_planner` and `get_reporter` are abstract; `get_coordinator` (accept/deny gate; the LLM writes a reply only on deny) and `get_supervisor` (judge completeness, then route among `get_supervised_agents_configuration()`) are concrete and decide through `AgentBase.is_yes` / `AgentBase.choose`, which use JEV (TypeSafe, via the `decision_engine` / `jev_integration_id` agent settings) and fall back to the LLM. Supervised agents default to `decision_engine="jev"`.

### LLM Integration

`AgentBase.get_chat_model()` dynamically selects the LangChain chat model class based on `integration.integration_type`:
- `openai_api_v1` → `ChatOpenAI`
- `anthropic_api_v1` → `ChatAnthropic`
- `xai_api_v1` → `ChatXAI`
- any other type → raises `ConfigurationError`

Embeddings use `OpenAIEmbeddings` with the integration's endpoint and API key; if the `EMBEDDINGS_ENDPOINT` env var is set, it overrides the endpoint (the integration's key is still sent). In tests, the Ollama container serves this endpoint (`/v1`), transparently mocking the OpenAI API.

API keys and endpoints are stored in Vault under `integration_{id}` and retrieved via `get_integration_credentials()`.

### Request Flow

1. HTTP request hits a FastAPI router in `agent_lab/interface/api/`
2. Router calls a service (e.g., `MessageService.process_message`)
3. Service resolves the agent type via `AgentRegistry.get_agent()`
4. Agent builds a LangGraph workflow, invokes it with PostgreSQL checkpointing
5. Progress updates publish to Redis; final result returns as JSON

### Database Schema

Three PostgreSQL databases:
- **agent_lab**: Relational data (agents, agent_settings, messages, attachments, language_models, language_model_settings, integrations) via SQLAlchemy
- **agent_lab_vectors**: pgvector embeddings via `DocumentRepository`
- **agent_lab_checkpoints**: LangGraph workflow state via `GraphPersistenceFactory`

### Observability

OpenTelemetry is configured in `agent_lab/infrastructure/metrics/tracer.py`. Instrumented: FastAPI, HTTPx, LangChain, SQLAlchemy, Psycopg. Exports via OTLP to a collector that feeds Prometheus (metrics), Loki (logs), Tempo (traces), and Grafana (dashboards). Config in `otel/`.

### MCP Server

The MCP server lives in `agent_lab/interface/mcp/` and is mounted at `/mcp` in `agent_lab/app_factory.py` (`http_app(path="/", stateless_http=True)`, lifespan shared with FastAPI). Auth is a Keycloak-backed `OAuthProxy` with persistent, Fernet-encrypted OAuth client storage in Redis (`server.py:_build_auth`).

**Registrar composition.** Capabilities are contributed by `McpRegistrar` subclasses decorated with `@discoverable_mcp_registrar(extra_deps=(...))` — no container edits. Discovery is uniform package scanning: `create_app()` without `scan_packages` scans `DEFAULT_SCAN_PACKAGES` (built-in agents + `agent_lab.interface.mcp` capabilities); an explicit list *replaces* the defaults, which is how a downstream app excludes unwanted built-in agents/tools/prompts. Only the two framework bridges (`DecoratedToolRegistrar`, `DecoratedPromptRegistrar`) load unconditionally (`bootstrap.load_framework_registrars`) so a scan that drops built-in capabilities can never disable the app's own decorated tools/prompts. `bootstrap.build_registrars` instantiates every registered class off the live container, resolving each `extra_deps` name as a container provider kwarg (the shared `agent_lab/core/extra_deps.py` convention, same as `@discoverable_agent`). `build_mcp_server` then iterates registrars calling `register_tools` → `register_prompts` → `register_resources`. Because `build_registrars` eagerly constructs every registrar before `build_mcp_server` runs, side effects in registrar `__init__` (e.g. populating `PromptRegistry`) are always complete before any `register_*` hook executes — dynamic tool descriptions built from `prompt_registry.names()` are safe regardless of order.

**Simple decorator surfaces.** For one-off capabilities there are function-level decorators, discovered through the same `scan_packages` / `agent_lab.agents` entry-point pass as `@discoverable_agent`: `@discoverable_mcp_tool("name", ...)` on an **async** function whose leading `container` parameter is bound and hidden from the client-facing schema (leave `container` unannotated — a TYPE_CHECKING-only annotation breaks fastmcp's `get_type_hints`), and `@discoverable_mcp_prompt("name", ...)` on a **sync** function (`PromptRegistry.resolve` is synchronous) exposed on the full prompt triple; its optional `agent_type`/`setting_key` pair opts into tenant overrides that replace the output verbatim (params affect only the default path). Collected by `DecoratedToolRegistrar` / `DecoratedPromptRegistrar`.

**Registration decorator conventions.** When adding the next decorator, follow the shared contract so the framework stays uniform: the registration key is the first positional argument (`discoverable_agent("type")`, `discoverable_mcp_tool("name")`, `discoverable_mcp_prompt("name")`); a duplicate key pointing at a *different* target raises at import time while re-decorating the *same* target is a no-op (module re-imports must stay safe); invalid targets fail at decoration time with the reason (e.g. async prompt fns are rejected because `PromptRegistry.resolve` is synchronous). Each registration module keeps a module-level `_registry` dict plus a `_reset_registry_for_tests()` hook, and `tests/unit/test_framework_registration.py` snapshots/restores every registry via autouse fixtures — extend that file (not a new per-module test file) when the framework grows.

**Prompt exposure triple.** Every pipeline prompt is exposed under three surfaces at once, because tools are the only MCP primitive reliably model-callable across all clients:
1. the `read_prompt_mcp` tool (dispatches through the shared `PromptRegistry`; accepts an optional `parameters` dict),
2. `prompts/get` (named arguments advertised as `PromptArgument`s — MCP arguments are strings; fastmcp converts them to the function signature's types),
3. resources: one concrete `prompt://<name>` per prompt (`mime_type="text/plain"`) plus a single global template `prompt://{name}{?parameters}` on `DefaultToolRegistrar` where `parameters` is a JSON object query param. Concrete resources win on exact URI match; the template handles parameterized reads — never register a second template over the same URI space.

**Adding a per-agent-type prompt registrar.** Subclass `PromptSetRegistrar`: declare `agent_type`, `role_setting_keys`, `role_prompt_names`, pass default templates to `__init__`. Override `_render(template, params)` for server-side Jinja and `_build_prompt_fn(role)` to accept named arguments (explicit signatures only — no dynamic-signature construction). Prompts whose templates contain Jinja control flow over server-side data (`SUPERVISED_AGENTS`, etc.) must be rendered server-side, never returned raw to the model. Register it with `@discoverable_mcp_registrar(extra_deps=("user_prompt_resolver", "prompt_registry"))`.

**Multi-tenancy.** Every prompt surface funnels through `UserPromptResolver.resolve(agent_type, setting_key, default_template)`: the tenant schema is derived from the MCP access token (`_get_mcp_schema()`; no/anonymous token → `"public"`), a non-empty tenant `AgentSetting` overrides the packaged default, and tenant overrides pass through the same `_render` path as defaults.

**MCP gotchas (cost real debugging time):**
- FastAPI merges dependency-set headers (e.g. `cache_control()`) only into non-`Response` returns — endpoints returning `FileResponse` must set headers on the response directly.
- Register closures in loops via a helper method called once per iteration (own stack frame) instead of `lambda x=x` default-arg tricks.
- fastmcp's `@mcp.tool` rejects `functools.partial` objects outright ("First argument to @tool must be a function..."). To bind a server-side value (e.g. `container`) into a tool function, wrap it instead: `functools.wraps(fn)` around a passthrough, then slice the bound parameter off `wrapper.__signature__` — fastmcp builds the client-facing schema from the remaining params. Reference implementation: `tool_registration.bind_container`.
- Never call `inspect.signature(..., eval_str=True)` on (or annotate injected params of) functions whose annotations name TYPE_CHECKING-only imports — annotation resolution raises `NameError` at registration time. Leave injected params unannotated; client-facing string annotations (`from __future__ import annotations`) resolve fine because fastmcp follows `__wrapped__` back to the function's own module globals.
- fastmcp resource templates support `{param}` path params and RFC 6570 `{?a,b}` query params; a function parameter matching a query param must have a default.
- Verify MCP behavior at protocol level with an in-memory client (`async with Client(mcp)` from fastmcp): `list_prompts` argument advertising, `get_prompt` with arguments, `list_resource_templates`, `read_resource` with query params. Mock-based unit tests alone don't prove the decorators produce valid registrations.

### Porting between Agent-Lab and downstream forks

When syncing generic improvements (see CLAUDE.md for the boundary rules):
- Diff both directions first — agent-lab evolves independently (dependency versions, tracing backends, test tooling are usually ahead of forks). Never assume the fork is strictly newer.
- Port tests together with code, genericizing fork-specific fixture names (agent types, setting values).
- Agent-lab is the canonical template for new downstream projects: prefer the cleanest generic API over byte-parity with an old fork, and note deliberate divergences so forks adopt the new version.
- Check `fastmcp`/decorator API compatibility against the *installed* version in `.venv` when the fork pins an older release.

---

## Common Commands

### Backend

**Important:** This project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management. Run all Python commands through `uv run <command>` so they execute inside the project's managed virtualenv. Use `uv sync` to install/update dependencies from `uv.lock`.

```bash
# Run the app locally (requires Postgres, Redis, Vault running)
docker compose -f compose-grafana.yml up --build -d

# Run all tests (spins up testcontainers: Postgres, Redis, Vault, Keycloak, Ollama, chromedp)
make test

# Run a single test file
uv run pytest tests/integration/test_status_endpoint.py

# Run a single test by name
uv run pytest tests/integration/test_status_endpoint.py -k "test_name"

# Agent simulations (live LLM calls; see the Agent Simulations section)
make test_simulations       # all suites in one pytest session (containers boot once)
make scenario_simulation    # or run one suite: scenario | langfuse | langwatch
make langfuse_simulation
make langwatch_simulation

# Lint
make lint

# Format (via ruff)
uv run ruff format .
uv run ruff check --fix .
```

**Pytest boot cost:** every pytest invocation — including pure unit-test files — pays the full testcontainers session-fixture boot (~2 min for Postgres, Redis, Vault, Keycloak, Ollama, chromedp) before the first test runs. Batch all files you need into a single invocation instead of running them one by one, and run `make lint` (instant) before tests so trivial failures don't cost a container boot.

### Backend Debugging

```bash
# View live app container logs (useful for debugging API errors)
docker compose logs -f app

# Rebuild and restart the app container after backend code changes
docker compose build app && docker compose up -d app
```

**Note:** The backend runs inside a Docker container. Local changes to Python files in `agent_lab/` are NOT reflected until the container is rebuilt. Always rebuild after modifying backend code.

## Agent Simulations

End-to-end agent simulations live in `tests/simulation/` behind the `agent_test` marker (deselected by default via `pytest.ini` addopts — any manual pytest invocation of these suites needs `-m agent_test`). Three tracks share the agent bootstrap helpers (`common/reference_agents.py`), the litellm LLM-as-judge (`common/judge.py`), and the versioned dataset definitions (`tests/simulation/datasets/*.json`):

- `scenario/` — conversational simulations via langwatch-scenario (user simulator + judge agent)
- `langfuse/` — dataset-driven experiments via Langfuse `run_experiment`; client-side judge scores are pushed to each run's trace
- `langwatch/` — the same experiments mirrored to LangWatch via `langwatch.experiment`

`uv run python scripts/setup_simulation_evals.py` idempotently provisions everything server-side: datasets on both platforms plus the Langfuse LLM connection, `simulation_llm_as_judge` evaluator, and per-dataset evaluation rules. All tracks share the judge configuration: `SIMULATION_JUDGE_MODEL` (default `openai/gpt-5-nano`), with `SIMULATION_JUDGE_API_BASE` / `SIMULATION_JUDGE_API_KEY` for a custom OpenAI-compatible endpoint. Details in `doc/TESTS.md`.

### Simulation platform gotchas

These cost real debugging time — check them before touching the simulation code:

- The repo-root `.env` loads as a side effect of `import scenario`, and `load_dotenv` does **not** override already-exported shell variables — a stale exported key silently shadows a rotated one in `.env`.
- Never put `@scenario.cache()` on helpers shared outside `scenario.run()`: it reads scenario's run ContextVar before checking whether caching is enabled, so any call outside a scenario run crashes.
- Langfuse v4: experiment items whose task raised are silently dropped from `item_results` — assert against the dataset's item list or a green test can be vacuous (`tests/simulation/langfuse/runner.py` does this). The evaluator-create request field is `model_config_` (trailing underscore; `model_config` is Pydantic-reserved and gets silently swallowed). Evaluator/rule creation preflights a live LLM call — pass `request_options={"timeout_in_seconds": 120}`. Evaluation rules are live-ingestion only (no backfill of past runs). The SDK prefers `LANGFUSE_BASE_URL`; `LANGFUSE_HOST` is a deprecated fallback still used by the app and `.env`.
- LangWatch: dataset create/list endpoints exist server-side but are not wrapped by the SDK — call them through `get_instance().rest_api_client.get_httpx_client()`. The server slugifies dataset names (underscores become dashes): always use the slug the server returns. Entries are schema-validated against the dataset's `columnTypes`, and the free plan caps a project at 3 datasets — which is why all definitions consolidate into the single `simulations` dataset with a `dataset` column.
- When a test's outcome lives in an external platform, verify through that platform's API that the runs/scores actually landed; exit code alone has produced false positives here.

## REST API Design

Follow the **Richardson Maturity Model** (Level 3) when designing or modifying API endpoints.

### HTTP Method Selection

Choose the method based on the operation's semantics, not implementation convenience:

| Method | Use When | Safe | Idempotent | Cacheable |
|--------|----------|------|------------|-----------|
| `GET` | Retrieving data (reads, queries, searches, bulk lookups) | Yes | Yes | Yes |
| `POST` | Creating resources or triggering non-idempotent operations | No | No | No |
| `PUT` | Full replacement of a resource | No | Yes | No |
| `PATCH` | Partial update of a resource | No | No | No |
| `DELETE` | Removing a resource | No | Yes | No |

**Key rule:** If a request is **safe** (no side effects) and **idempotent** (same result on repeated calls), it MUST be a GET. This enables browser/CDN caching via `Cache-Control` headers. POST requests are never cached by browsers regardless of cache headers.

### Query Parameters vs Request Body

- **GET endpoints**: Pass filters via query parameters. For lists, use comma-separated values (e.g., `?key_tickers=AAPL,MSFT,NVDA`).
- **POST/PUT/PATCH endpoints**: Use JSON request body for resource creation/mutation.
- **URL path parameters**: Use for resource identifiers (e.g., `/stats_close/{index_name}/{key_ticker}`).

### Caching

- Use the `cache_control(max_age)` dependency from `agent_lab/interface/api/cache_control.py`.
- Read-heavy, infrequently-changing data (e.g., market caps, EOD stats): `cache_control(86400)` (24h).
- Frequently-changing data (e.g., news, real-time prices): `cache_control(3600)` (1h) or less.
- Caching only works with GET — never rely on cache headers for POST endpoints.

### Resource Naming

- Use **nouns** for resources, not verbs: `/markets/stats_close`, not `/markets/get_stats`.
- Use **snake_case** for path segments and query params (matching Python conventions).
- Use plural when returning collections: `/markets/news`, `/markets/indicators`.

### Validation

- Path/query params are validated via `_validate_index_name()` regex in `endpoints.py`.
- Never expose internal patterns (e.g., ES wildcards `*`) through the API — resolve them server-side or use aliases.

---

## Code Conventions

- **Linting**: ruff only (`make lint` runs `ruff check` + `ruff format --check`); ruff-check and ruff-format run as pre-commit hooks.
- **Pre-commit hooks**: Also run `make test` as a local hook on every commit — tests must pass before commits succeed.
- **Config files**: YAML-based (`config-*.yml`), loaded conditionally by env var in `Container`.
- **Agent prompts**: Use Jinja2 templates stored in agent settings, rendered via `AgentBase.parse_prompt_template()`.
- **Versioning**: Managed by `python-semantic-release`.
- **Testing**: pytest with testcontainers — tests spin up real Postgres, Redis, Vault, Keycloak, Ollama, and chromedp containers. The `conftest.py` session fixture manages container lifecycle.
