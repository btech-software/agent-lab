<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Testing &amp; Simulations</h3>

<p align="center">
  <em>Two harnesses: real-infrastructure integration tests and LLM-as-judge agent simulations</em><br>
  <strong>Type</strong> · Guide &nbsp;|&nbsp; <strong>Audience</strong> · Developers, researchers &amp; contributors
</p>

---

#### Table of Contents

- [Two complementary harnesses](#two-complementary-harnesses)
- [Integration tests](#integration-tests)
- [Agent simulations](#agent-simulations)
- [Judge and agent LLM configuration](#judge-and-agent-llm-configuration)
- [Setting up the evaluation platforms](#setting-up-the-evaluation-platforms)

---

Testing agents is a first-class capability of the framework, not an afterthought.
Agent-Lab ships two complementary harnesses you can use both to validate the
framework itself and to validate the agents you build on top of it:

- **Integration tests** exercise the system against real infrastructure (Postgres,
  Redis, Keycloak, embeddings, headless Chrome) spun up on demand with
  testcontainers — covering external services, database operations, vector search
  and API endpoints.
- **Agent simulations** evaluate agent behavior end-to-end against live LLMs, scored
  by an LLM-as-judge and tracked over time in Langfuse and LangWatch.

The main configuration for integration tests lives in `tests/conftest.py`; customize
it to your environment.

**Note:** integration tests and simulations perform real calls to external services
and may incur costs. Run them in a controlled environment and monitor usage.

## Integration tests

Requires **Docker** (or another container runtime) — the suite provisions real
containers via [testcontainers](https://testcontainers-python.readthedocs.io/en/latest/).

```bash
make test_unit         # fast lane: boots the app with no infrastructure
make test_integration  # the full real-infrastructure suite
make test              # both, with coverage (gate: 90%)
```

The first execution can take several minutes — Docker images and embedding models
are downloaded once. Coverage of `agent_lab/` is enforced in CI (SonarCloud).

The scaffolded projects mirror this: `tests/` contains no-container smoke tests plus
an optional testcontainers suite.

## Agent simulations

End-to-end agent simulations live in `tests/simulation/` and call live LLM
providers. They are marked `agent_test` and deselected by default; run them with:

```bash
make test_simulations
# or a single track:
make scenario_simulation
make langwatch_simulation
make langfuse_simulation
```

Three complementary tracks share the agent bootstrap helpers, the judge and the
dataset definitions under `tests/simulation/datasets/`:

- `tests/simulation/scenario/` — conversational simulations using the
  [langwatch-scenario](https://github.com/langwatch/scenario) framework: a user
  simulator drives the agent while a judge agent scores the interaction.
- `tests/simulation/langfuse/` — dataset-driven experiments using
  [Langfuse](https://langfuse.com/) datasets. Each run syncs the dataset definitions,
  invokes the agent per item, scores the output with a client-side LLM-as-judge, and
  records run and scores in Langfuse for comparison over time. Skips automatically
  when `LANGFUSE_BASE_URL` (or the deprecated `LANGFUSE_HOST`), `LANGFUSE_PUBLIC_KEY`
  and `LANGFUSE_SECRET_KEY` are not set.
- `tests/simulation/langwatch/` — the same dataset experiments mirrored to
  [LangWatch](https://langwatch.ai/) via `langwatch.experiment`, logging the judge
  score per item. Definitions sync idempotently into a single consolidated
  `simulations` dataset (a `dataset` column identifies the source definition, since
  the LangWatch free plan allows at most 3 datasets per project). Skips
  automatically when `LANGWATCH_ENDPOINT` and `LANGWATCH_API_KEY` are not set.

The reference agents covered across the tracks: the coordinator-planner-supervisor,
react RAG, vision/document, browser automation, voice memos and adaptive RAG agents.

## Judge and agent LLM configuration

The judge (and the scenario user simulator) use litellm model ids against any
OpenAI-API-compatible endpoint:

| Environment variable | Default | Purpose |
|---|---|---|
| `SIMULATION_JUDGE_MODEL` | `openai/gpt-5-nano` | litellm model id used by the LLM-as-judge |
| `SIMULATION_JUDGE_API_BASE` | provider default | custom OpenAI-compatible endpoint for the judge model |
| `SIMULATION_JUDGE_API_KEY` | provider default | API key for the custom endpoint |

The agents under test run on a default LLM served by any OpenAI-compatible endpoint
(e.g. a LAN inference server), provisioned per test by
`tests/simulation/common/llm_factory.py`. The exception is the voice memos agent,
which stays on OpenAI (it needs audio chat input). Embeddings keep using the
`EMBEDDINGS_ENDPOINT` fallback (the test Ollama container serving `bge-m3`),
matching the pgvector dump. The endpoint must support tool calling / structured
output for the supervisor-based suites (browser automation, supervisor):

| Environment variable | Default | Purpose |
|---|---|---|
| `SIMULATION_LLM_MODEL` | none (required) | model tag executing the simulations (e.g. `qwen3:30b`) |
| `SIMULATION_LLM_API_BASE` | none (required) | OpenAI-compatible endpoint serving the model |
| `SIMULATION_LLM_API_KEY` | `dummy-key` | API key, if the endpoint requires one |

## Setting up the evaluation platforms

`make test_simulations` (and the per-track targets) run the
`sync_simulation_evals` step first, which mirrors the dataset definitions to every
configured platform. To also provision the **Langfuse server-side evaluation
setup** (an LLM connection for the judge model, a `simulation_llm_as_judge`
evaluator, and one evaluation rule per simulation dataset — visible in the Langfuse
Evaluations section), run:

```bash
uv run python tests/setup_simulation_evals.py
```

The script is idempotent and safe to re-run.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Observability](OTEL.md) |
| ➡️ Next | [Entity Domain Model](DOMAIN.md) · [Researcher's Guide](RESEARCHER_GUIDE.md) |
