<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Observability</h3>

<p align="center">
  <em>Traces, metrics and logs for every agent interaction — via OpenTelemetry</em><br>
  <strong>Type</strong> · Explanation + How-to &nbsp;|&nbsp; <strong>Audience</strong> · Developers &amp; operators
</p>

---

#### Table of Contents

- [Why observability is built in](#why-observability-is-built-in)
- [What gets instrumented](#what-gets-instrumented)
- [Turning it on](#turning-it-on)
- [LLM observability backends](#llm-observability-backends)
- [Reference dashboards](#reference-dashboards)
- [Extending: your own backend](#extending-your-own-backend)

---

## Why observability is built in

Agents are hard to debug by reading logs: the interesting behavior lives in nested
LLM calls, tool invocations and database round-trips. Agent-Lab treats observability
as a framework feature, not a bolt-on — every HTTP request, model call, SQL query and
outbound HTTP hop becomes a span, exported over industry-standard
[OpenTelemetry](https://opentelemetry.io/) (with [OpenLLMetry](https://github.com/traceloop/openllmetry)
and [OpenInference](https://github.com/Arize-ai/openinference) semantic conventions).

Because it is OTLP end-to-end, any collector-compatible backend works — Grafana
stack, Elastic, Langfuse, LangWatch, or your company's existing APM.

## What gets instrumented

The setup lives in `agent_lab/infrastructure/metrics/tracer.py`. With
`OTEL_EXPORTER_OTLP_ENDPOINT` set, the following are traced automatically:

| Instrumentor | What you see |
|---|---|
| **FastAPI** | One server span per request, with route, status and duration |
| **HTTPX** | Every outbound HTTP call an agent or service makes |
| **LangChain** | Every LLM/chain invocation with token usage — the heart of agent tracing |
| **OpenAI** | OpenAI-native calls (OpenInference conventions) |
| **SQLAlchemy** | Every database statement (relational, vector search, checkpoints) |

Resource identity comes from `SERVICE_NAME` (default `Agent-Lab`) and
`SERVICE_VERSION` (default `snapshot`). Noise paths (`/status/*`, `/docs`,
`/openapi.json`, favicons) are dropped by a custom sampler.

## Turning it on

**No code changes — only an endpoint.** When `OTEL_EXPORTER_OTLP_ENDPOINT` is set,
spans flow to `<endpoint>/v1/traces`, `/v1/metrics` and `/v1/logs` over OTLP/HTTP.
When it is unset, tracing is off.

```bash
# Point the app at any OTLP/HTTP collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn agent_lab.main:app --reload
```

For local development, two pre-configured stacks do all the wiring for you (from the
framework repository):

```bash
docker compose -f compose-grafana.yml up --build      # collector + Prometheus + Tempo + Loki + Grafana
docker compose -f compose-opensearch.yml up --build   # collector + Data Prepper + OpenSearch + Dashboards
```

Each stack bundles its own OpenTelemetry Collector configuration under `otel/grafana/`
and `otel/opensearch/` respectively — those files are the reference for how traces,
metrics and logs are routed. See the [Deployment guide](SETUP.md) for production
topologies.

## LLM observability backends

Beyond raw OTel, Agent-Lab plugs into purpose-built **LLM observability platforms**
through a `TracingBackend` abstraction (wired as DI providers in
`agent_lab/core/container.py`). Both shipped backends are enabled purely by
environment variables and **silently disable themselves** when their variables are
missing, so the app always boots.

### Langfuse

Set the three variables from your Langfuse project and every trace is mirrored to
Langfuse's OTLP endpoint (`{LANGFUSE_HOST}/api/public/otel/v1/traces`) with
`langfuse.trace.*` attributes — prompts, completions, token usage and costs, ready
for the [simulation experiments](TESTS.md#agent-simulations):

| Variable | Purpose |
|---|---|
| `LANGFUSE_HOST` | Langfuse base URL |
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-…` |
| `LANGFUSE_SECRET_KEY` | `sk-lf-…` |

### LangWatch

| Variable | Purpose |
|---|---|
| `LANGWATCH_ENDPOINT` | LangWatch endpoint |
| `LANGWATCH_API_KEY` | LangWatch API key |

LangWatch records a per-message `langwatch.trace()` span, which is how the
simulation suites log judge scores against experiments.

## Reference dashboards

| Stack | Guide | UI |
|---|---|---|
| Grafana + Prometheus + Tempo + Loki | [otel/GRAFANA.md](otel/GRAFANA.md) | [http://localhost:3000](http://localhost:3000) |
| OpenSearch Dashboards | [otel/OPENSEARCH.md](otel/OPENSEARCH.md) | [http://localhost:5601](http://localhost:5601) |

Both guides include demo recordings of the dashboards in action.

## Extending: your own backend

`TracingBackend` is part of the public API. Subclass it to forward spans to your own
platform, and register it on your `Container`:

```python
from agent_lab import Container, TracingBackend


class MyBackend(TracingBackend):
    ...  # export spans wherever your platform needs them


class MyContainer(Container):
    # replace or extend the shipped tracing_backends provider list
    ...
```

The [Configuration reference](CONFIGURATION.md#observability) lists every
observability-related variable in one table.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [MCP Server guide](MCP.md) |
| ➡️ Next | [Reference dashboards: Grafana](otel/GRAFANA.md) · [Testing & Simulations](TESTS.md) |
