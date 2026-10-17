<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">REST API Reference</h3>

<p align="center">
  <em>The complete endpoint catalog, with request examples</em><br>
  <strong>Type</strong> · Reference &nbsp;|&nbsp; <strong>Audience</strong> · API consumers
</p>

---

#### Table of Contents

- [Interactive documentation](#interactive-documentation)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Request examples](#request-examples)
- [Conventions](#conventions)

---

## Interactive documentation

Every Agent-Lab application serves OpenAPI 3 automatically — the reference
implementation at [http://localhost:18000/docs](http://localhost:18000/docs) (or your
own app wherever it runs). The catalog below documents the framework's built-in
routers; your `extra_routers` appear in the same schema.

## Authentication

When `auth.enabled` is `true` (see the [Configuration reference](CONFIGURATION.md)),
routes require a Keycloak bearer token. The `/auth` router is only mounted when auth
is enabled:

```bash
TOKEN=$(curl -s -X POST https://<host>/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "…", "password": "…"}' | jq -r '.access_token')

curl -s https://<host>/agents/list -H "Authorization: Bearer $TOKEN" | jq
```

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Create a new bearer token |
| POST | `/auth/renew` | Renew an existing bearer token |
| POST | `/auth/exchange` | Exchange a Microsoft Entra ID authorization code (PKCE) for an app token |
| GET | `/auth/profile` | Get the authenticated user's profile |
| PUT | `/auth/profile` | Update the authenticated user's profile |

Setup of the realm/client is covered in [Auth with Keycloak](KEYCLOAK.md).

**Unauthenticated paths:** `/status/*`, `/docs`, `/openapi.json`, `/mcp`, `/static`,
the OAuth well-known endpoints, and the SPA mount — everything else requires a valid
token.

## Endpoints

### Agents

Create instances of any registered agent type; `agent_type` is validated dynamically
against the [registry](DEV_GUIDE.md#register-the-agent-with-discoverable_agent).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/agents/list` | List all agent instances |
| GET | `/agents/types` | List registered agent types (the registry) |
| GET | `/agents/{agent_id}` | Get an agent instance by ID |
| POST | `/agents/create` | Create a new agent instance |
| POST | `/agents/update` | Update an agent's basic information |
| POST | `/agents/update_setting` | Update a single agent setting |
| POST | `/agents/{agent_id}/reset_settings` | Reset an agent's settings to its defaults |
| DELETE | `/agents/delete/{agent_id}` | Delete an agent instance |
| WS | `/agents/ws/task_updates/{agent_id}` | WebSocket stream of task progress updates for long operations |

### Messages

| Method | Endpoint | Description |
|---|---|---|
| POST | `/messages/post` | Send a message to an agent and get the reply |
| POST | `/messages/list` | List messages for an agent |
| GET | `/messages/{message_id}` | Get expanded message details (replies, attachment) |
| DELETE | `/messages/delete/{message_id}` | Delete a message |

### Language models

| Method | Endpoint | Description |
|---|---|---|
| GET | `/llms/list` | List configured language models |
| GET | `/llms/{language_model_id}` | Get a language model and its settings |
| POST | `/llms/create` | Create a new language model |
| POST | `/llms/update` | Update a language model's configuration |
| POST | `/llms/update_setting` | Update a single language model setting |
| DELETE | `/llms/delete/{language_model_id}` | Delete a language model |

### Integrations

| Method | Endpoint | Description |
|---|---|---|
| GET | `/integrations/list` | List external integrations (AI suppliers) |
| GET | `/integrations/{integration_id}` | Get integration details |
| POST | `/integrations/create` | Create an integration (credentials stored in [Vault](VAULT.md)) |
| DELETE | `/integrations/delete/{integration_id}` | Delete an integration |

### Attachments

| Method | Endpoint | Description |
|---|---|---|
| GET | `/attachments/list` | List attachments |
| GET | `/attachments/download/{attachment_id}` | Download an attachment |
| POST | `/attachments/upload` | Upload a file attachment |
| POST | `/attachments/embeddings` | Generate embeddings for an attachment |

### Status and MCP

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status/liveness` | Liveness probe |
| GET | `/status/readiness` | Readiness probe |
| GET | `/status/metrics` | Prometheus metrics |
| * | `/mcp` | The [MCP server](MCP.md) (Streamable HTTP) |
| GET | `/.well-known/oauth-protected-resource/mcp` | OAuth metadata for MCP clients |

## Request examples

**Create an agent instance** — `agent_name` accepts `[a-zA-Z0-9_-]`;
`agent_type` must be a registered type; `language_model_id` is optional:

```bash
curl -s -X POST http://localhost:18000/agents/create \
  -H "Authorization: Bearer not-applicable" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_name": "support-agent-1",
        "agent_type": "coordinator_planner_supervisor",
        "language_model_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
      }' | jq
```

**Send a message** — `message_role` is one of `human`, `assistant`, `tool`;
`attachment_id` is optional:

```bash
curl -s -X POST http://localhost:18000/messages/post \
  -H "Authorization: Bearer not-applicable" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "message_role": "human",
        "message_content": "Summarize the attached report.",
        "attachment_id": null
      }' | jq
```

**Update an agent setting** — `setting_key` accepts `[a-zA-Z_-]`;
`setting_value` holds up to 16,000 characters (prompt templates and JSON payloads
live here — see the [Entity Domain Model](DOMAIN.md)):

```bash
curl -s -X POST http://localhost:18000/agents/update_setting \
  -H "Authorization: Bearer not-applicable" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "setting_key": "system_prompt",
        "setting_value": "You are a concise research assistant…"
      }' | jq
```

## Conventions

- **IDs** are UUIDs; all list endpoints accept JSON bodies, not query strings.
- **Settings** are key-value pairs persisted with the agent or model — that is how
  the same implementation runs many differently-configured instances.
- **The registry is the source of truth** for valid `agent_type` values — run
  `GET /agents/types` to see what the running app discovered (including your own
  packages via `scan_packages`).

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Configuration reference](CONFIGURATION.md) |
| ➡️ Next | [MCP Server guide](MCP.md) |
