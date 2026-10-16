<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Researcher's Guide</h3>

<p align="center">
  <em>Experiments, notebooks, and prototyping new agent behaviors</em><br>
  <strong>Type</strong> · Guide &nbsp;|&nbsp; <strong>Audience</strong> · AI researchers &amp; developers
</p>

---

#### Table of Contents

- [Who this guide is for](#who-this-guide-is-for)
- [Quickstart — run the examples](#quickstart--run-the-examples)
- [Project layout — quick tour](#project-layout--quick-tour)
- [Notebooks — the primary learning path](#notebooks--the-primary-learning-path)
- [Core concepts](#core-concepts)
- [Running experiments and capturing results](#running-experiments-and-capturing-results)
- [Prototyping new behaviors](#prototyping-new-behaviors)
- [Testing and evaluation](#testing-and-evaluation)
- [Reproducibility checklist](#reproducibility-checklist)

---

## Who this guide is for

AI researchers and developers who want to explore, reproduce, and extend experiments
in Agent-Lab. If you write Python, use Jupyter, and think in terms of experiments,
agents and pipelines, you'll feel at home. Familiarity with LLMs, RAG and container
basics is helpful but not required.

Agent-Lab provides reusable components (agent types, tools, integrations) plus a
collection of Jupyter notebooks with step-by-step examples, so you can get
productive quickly.

## Quickstart — run the examples

Requirements: **Python 3.12+**, a working Jupyter environment (JupyterLab or
Notebook), and optionally local Docker for end-to-end integrations. Working in a
clone of the repository:

```bash
uv sync --group notebooks   # runtime + notebook dependencies in one virtualenv
jupyter lab                 # from the repository root
```

Open `notebooks/` and start with `01_…`, progressing through the ones that interest
you.

Notes:

- Notebooks are mostly self-contained; each header states the required environment
  variables and external services (API keys, endpoints).
- The required keys live in `.env` — copy `.env.example` and fill it in (see the
  [Configuration reference](CONFIGURATION.md)).
- To experiment against Agent-Lab from your own project instead of the repository,
  `pip install btech-agent-lab` and assemble the app with `create_app()` — see
  [Extending the framework](DEV_GUIDE.md#extending-the-framework) in the
  Developer's Guide.

## Project layout — quick tour

- `notebooks/` — interactive examples of agent types, evaluation and integrations. **Start here.**
- `agent_lab/` — the framework package:
  - `app_factory.py` — the composition root: `create_app()`.
  - `core/` — configuration sources, DI container, `extra_deps` resolution.
  - `domain/` — models, repository interfaces, exceptions (the [Entity Domain Model](DOMAIN.md)).
  - `services/` — business logic and the `agent_types/` implementations.
  - `interface/` — `api/` (HTTP routers) and `mcp/` (the MCP server).
  - `infrastructure/` — database, auth, metrics/tracing adapters.
- `tests/` — `unit/`, `integration/`, `template/` and `simulation/` suites (see [Testing & Simulations](TESTS.md)).
- `doc/` — the documentation you are reading.

Understanding these layers tells you where behavior lives: examples in `notebooks`,
core contracts in `core/` and `domain/`, and adapters in `infrastructure/`.

## Notebooks — the primary learning path

Typical progression:

| Notebook | Demonstrates |
|---|---|
| [01_setup_embeddings_service.ipynb](../notebooks/01_setup_embeddings_service.ipynb) | Configure and validate your embeddings provider (start here) |
| [02_test_agent_type-adaptive_rag.ipynb](../notebooks/02_test_agent_type-adaptive_rag.ipynb) | Adaptive RAG: retrieval grader, query rewriter, answer grader |
| [03_test_agent_type-react_rag.ipynb](../notebooks/03_test_agent_type-react_rag.ipynb) | ReAct pattern with retrieval and tool usage |
| [04_test_agent_type-vision_document.ipynb](../notebooks/04_test_agent_type-vision_document.ipynb) | Vision + document retrieval |
| [05_test_agent_type-multiagent-coder.ipynb](../notebooks/05_test_agent_type-multiagent-coder.ipynb) | Multi-agent collaboration for code tasks |
| [06_test_agent_type-multiagent-researcher.ipynb](../notebooks/06_test_agent_type-multiagent-researcher.ipynb) | Multi-agent research workflows |
| [07_test_agent_type-multiagent-browser.ipynb](../notebooks/07_test_agent_type-multiagent-browser.ipynb) | Web-browsing agents |
| [08_test_agent_type-multiagent-voice-assistant.ipynb](../notebooks/08_test_agent_type-multiagent-voice-assistant.ipynb) | Voice agent (and variants 09/10: Azure Entra ID, fast) |
| [11_mcp_client-openai-responses.ipynb](../notebooks/11_mcp_client-openai-responses.ipynb) | Talking to the MCP server from the OpenAI Responses API |

Each notebook contains: a short description of the experiment objective, the
required environment variables and secrets, helper functions, and printed/visual
outputs to inspect agent decisions and metrics.

Pro tip: run notebooks in order for an incremental learning curve. Use smaller
datasets and sample sizes while iterating to keep runs fast.

## Core concepts

- **Agent** — a registered implementation under `agent_lab/services/agent_types/`
  (`@discoverable_agent`). The registry resolves it lazily through the DI container,
  injecting declared `extra_deps`.
- **Tools** — discrete abilities an agent can call (search, browsing, TTS/ASR),
  implemented as adapters in `agent_lab/infrastructure/` or `agent_lab/interface/`.
- **Container** — the DI composition object (`agent_lab/core/container.py`);
  subclass it to add providers for your experiments.
- **Repositories** — data-access interfaces in `agent_lab/domain/repositories/`.
- **ConfigSource** — where configuration comes from; use the YAML sources in
  experiments, [Vault](VAULT.md) in production.

When you want to modify behavior, decide whether the change is: *experimental*
(notebook only), *architectural* (`core`/`domain`/`services`), or
*integration-level* (adapter in `infrastructure`). Favor small, testable changes —
and add or update a notebook to show the new behavior.

## Running experiments and capturing results

Notebooks print intermediate steps; for more robust experiments:

- Use deterministic seeds where randomness matters.
- Capture the metrics relevant to your question — latency, token usage, tool-call
  counts, judge scores. The observability layer exports everything as OpenTelemetry
  (see [Observability](OTEL.md)); the simulation harness logs judge scores to
  Langfuse/LangWatch (see [Testing & Simulations](TESTS.md#agent-simulations)).
- For repeatable runs, export notebook cells to scripts and run them in CI or on
  compute nodes:

  ```bash
  jupyter nbconvert --to script notebooks/02_test_agent_type-adaptive_rag.ipynb
  ```

- The `docker/app/Dockerfile` builds a pinned runtime image for reproducible
  execution.

## Prototyping new behaviors

1. **Add a new agent type**: create the class under
   `agent_lab/services/agent_types/`, decorate it with
   `@discoverable_agent("your_type")`, and add a notebook that mounts it through the
   DI container and exercises it with a small scenario. The full walkthrough is in
   [Building agentic workflows](DEV_GUIDE.md#building-agentic-workflows).
2. **Swap an embeddings provider**: implement a compatible adapter under
   `agent_lab/infrastructure/` and validate it with notebook 01.
3. **Add a retrieval store or vector DB**: implement repository methods in
   `agent_lab/domain/repositories/` and an adapter in
   `agent_lab/infrastructure/database/`; seed it with a small loader notebook and
   demonstrate retrieval in a query notebook.

Design tip: keep adapter interfaces narrow and test them in isolation with small
unit tests.

## Testing and evaluation

```bash
make test_unit           # unit tests — no infrastructure needed
make test                # unit + integration with coverage
make test_simulations    # LLM-as-judge agent simulations (live LLMs)
```

When you change core behavior, add a unit test and a short notebook demonstrating
the change — that pairing is what makes research reproducible here. The full
harness, judge configuration and evaluation platforms are covered in
[Testing & Simulations](TESTS.md).

## Reproducibility checklist

- Pin your environment (uv + `pyproject.toml` / `uv.lock`).
- Record seeds and config files (`config-dev.yml`, `config-test.yml`).
- Save the notebook checkpoint and any output artifacts (CSV/JSON) alongside your
  experiment.
- Note the [tracing endpoints](OTEL.md#turning-it-on) you exported to — traces are
  your experiment log.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Entity Domain Model](DOMAIN.md) |
| ➡️ Next | [Deployment](SETUP.md) |
