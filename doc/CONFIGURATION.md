<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Configuration Reference</h3>

<p align="center">
  <em>Every configuration key and environment variable, and how the active source is chosen</em><br>
  <strong>Type</strong> · Reference &nbsp;|&nbsp; <strong>Audience</strong> · Operators &amp; developers
</p>

---

#### Table of Contents

- [How configuration is loaded](#how-configuration-is-loaded)
- [Configuration keys](#configuration-keys)
- [Vault secret payload](#vault-secret-payload)
- [Environment variables](#environment-variables)
- [Custom configuration sources](#custom-configuration-sources)

---

## How configuration is loaded

Configuration is a plain dictionary loaded by a `ConfigSource` (see
`agent_lab/core/config.py`) and bound to the DI container. `create_app()` selects a
source through `default_config_source()`, in this exact order — **first match wins**:

| # | Condition (environment variable set) | Active source |
|---|---|---|
| 1 | `VAULT_K8S_ROLE` | `KubernetesVaultConfigSource` — Vault via the pod's projected ServiceAccount token |
| 2 | `DOCKER` | `YamlConfigSource("config-docker.yml")` |
| 3 | `TESTING` | `YamlConfigSource("config-test.yml")` |
| 4 | `DEVELOPING` | `YamlConfigSource("config-dev.yml")` |
| 5 | *(none of the above)* | `VaultConfigSource` — reads `VAULT_URL` / `VAULT_TOKEN` |

You can override the selection per app:

```python
app = create_app(config_source=YamlConfigSource("config.yml"))  # explicit
```

## Configuration keys

The dictionary the active source must return. Defaults shown are from
`config-dev.yml` (development); the reference app ships `config-dev.yml`,
`config-test.yml` and `config-docker.yml` with this exact shape.

| Key | Purpose | Example value |
|---|---|---|
| `api_base_url` | Public base URL of this API (used for links in responses) | `http://localhost:8000` |
| `cdp_url` | Headless Chrome (CDP) endpoint for web agents (`WebAgentBase`) | `http://localhost:9222` |
| `auth.enabled` | Mount auth middleware and the `/auth` routes when `true` | `false` |
| `auth.url` | Keycloak base URL | `https://auth.example.com` |
| `auth.realm` | Keycloak realm name | `agent-lab` |
| `auth.client_id` | OIDC client id | `agent-lab-api` |
| `auth.client_secret` | OIDC client secret | `…` |
| `broker.url` | Redis URL for pub/sub status updates on long operations | `redis://localhost:6379/0` |
| `db.url` | PostgreSQL — relational data | `postgresql://postgres:postgres@localhost:5432/agent_lab` |
| `db.vectors` | PostgreSQL — pgvector embeddings database | `postgresql://postgres:postgres@localhost:5432/agent_lab_vectors` |
| `db.checkpoints` | PostgreSQL — LangGraph checkpoint (agent memory) database | `postgresql://postgres:postgres@localhost:5432/agent_lab_checkpoints` |
| `vault.url` | Vault address (also written back so services can read secrets) | `http://localhost:8200` |
| `vault.token` | Vault token | `dev-only-token` |
| `static.enabled` | Serve a SPA build (`false` when no frontend build exists) | `false` |
| `static.directory` | Directory containing the SPA build | `static/frontend/browser` |
| `static.index_file` | SPA fallback file | `index.html` |
| `static.mount_path` | Mount point of the SPA | `/` |

`static` is special: the YAML sources configure it explicitly, while the Vault source
derives it from a code convention — enabled when a SPA build exists under `STATIC_DIR`.

## Vault secret payload

`VaultConfigSource` reads a single KV-v2 secret (engine `secret`, path `app_secrets`
by default) and maps it onto the keys above:

| Secret key | Maps to |
|---|---|
| `api_base_url` | `api_base_url` |
| `cdp_url` | `cdp_url` |
| `auth_enabled` → `auth.enabled` | `auth.enabled` |
| `auth_url` → `auth.url` | `auth.url` |
| `auth_realm` → `auth.realm` | `auth.realm` |
| `auth_client_id` → `auth.client_id` | `auth.client_id` |
| `auth_client_secret` → `auth.client_id` | `auth.client_secret` |
| `broker_url` | `broker.url` |
| `db_url` | `db.url` |
| `db_vectors` | `db.vectors` |
| `db_checkpoints` | `db.checkpoints` |

How to provision that payload (dev Docker Compose, Kubernetes, Terraform) is covered
in [Secrets with Vault](VAULT.md) and the [Deployment guide](SETUP.md).

## Environment variables

### Config source selection

| Variable | Default | Purpose |
|---|---|---|
| `DEVELOPING` | *(unset)* | Selects `config-dev.yml` (IDE debugging) |
| `TESTING` | *(unset)* | Selects `config-test.yml` (test suite) |
| `DOCKER` | *(unset)* | Selects `config-docker.yml` (Compose) |
| `VAULT_URL` | *(unset)* | Vault address for the default source |
| `VAULT_TOKEN` | *(unset)* | Vault token for the default source |
| `VAULT_ENGINE_PATH` | `secret` | KV-v2 mount point |
| `VAULT_SECRET_PATH` | `app_secrets` | Secret path |
| `VAULT_K8S_ROLE` | *(unset)* | Vault Kubernetes auth role; enables the K8s source and takes precedence |
| `STATIC_DIR` | `static/frontend/browser` | Where the SPA build is looked up |

### Observability

| Variable | Default | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(unset — tracing off)* | OTLP/HTTP collector base URL; traces → `/v1/traces`, metrics → `/v1/metrics`, logs → `/v1/logs` |
| `SERVICE_NAME` | `Agent-Lab` | OTel resource name |
| `SERVICE_VERSION` | `snapshot` | OTel resource version |
| `LANGFUSE_HOST` | *(unset)* | Langfuse base URL; with the two keys below, enables the Langfuse backend |
| `LANGFUSE_PUBLIC_KEY` | *(unset)* | Langfuse `pk-lf-…` key |
| `LANGFUSE_SECRET_KEY` | *(unset)* | Langfuse `sk-lf-…` key |
| `LANGWATCH_ENDPOINT` | *(unset)* | LangWatch endpoint; with the key below, enables the LangWatch backend |
| `LANGWATCH_API_KEY` | *(unset)* | LangWatch API key |

If any Langfuse variable is missing, the Langfuse backend is silently disabled and
the app still boots (same for LangWatch). Details and the extension point:
[Observability](OTEL.md).

### Auth and integrations

| Variable | Default | Purpose |
|---|---|---|
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` | *(unset)* | Microsoft Entra ID credentials for `/auth/exchange` |
| `EMBEDDINGS_ENDPOINT` | *(unset)* | Embeddings service used by retrieval agents |
| `OPENAI_API_KEY` | *(unset)* | OpenAI (voice memos audio input; simulation judge default) |

### Simulations (test suite only)

| Variable | Default | Purpose |
|---|---|---|
| `SIMULATION_LLM_MODEL` | *(required)* | Model tag executing the agents under test (e.g. `qwen3:30b`) |
| `SIMULATION_LLM_API_BASE` | *(required)* | OpenAI-compatible endpoint serving that model |
| `SIMULATION_LLM_API_KEY` | `dummy-key` | API key for the endpoint, if required |
| `SIMULATION_JUDGE_MODEL` | `openai/gpt-5-nano` | litellm model id used by the LLM-as-judge |
| `SIMULATION_JUDGE_API_BASE` | provider default | Custom OpenAI-compatible endpoint for the judge |
| `SIMULATION_JUDGE_API_KEY` | provider default | API key for the custom judge endpoint |

See [Testing & Simulations](TESTS.md) for how these are consumed.

## Custom configuration sources

Implement the `ConfigSource` ABC and pass it to `create_app(config_source=...)` —
useful for AWS Secrets Manager, environment-only deployments, or wrapping another
source:

```python
from agent_lab import ConfigSource, create_app


class MyConfigSource(ConfigSource):
    def load(self) -> dict:
        return {
            "api_base_url": "https://api.example.com",
            "db": {"url": "postgresql://…", "vectors": "…", "checkpoints": "…"},
            "auth": {"enabled": True, "url": "…", "realm": "…", "client_id": "…", "client_secret": "…"},
            "broker": {"url": "redis://…"},
            # … remaining keys as in the table above
        }


app = create_app(config_source=MyConfigSource())
```

The shipped sources (`YamlConfigSource`, `VaultConfigSource`,
`KubernetesVaultConfigSource`) and `default_config_source()` are all exported from the
top-level `agent_lab` package.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Developer's Guide](DEV_GUIDE.md) |
| ➡️ Next | [REST API reference](REST_API.md) · [Secrets with Vault](VAULT.md) |
