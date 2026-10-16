<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Entity Domain Model</h3>

<p align="center">
  <em>The entities behind every Agent-Lab application — and how they persist</em><br>
  <strong>Type</strong> · Explanation &nbsp;|&nbsp; <strong>Audience</strong> · Developers &amp; contributors
</p>

---

#### Table of Contents

- [Entities](#entities)
- [Where data lives](#where-data-lives)
- [Security and secrets management](#security-and-secrets-management)

---

Agent-Lab applications share one domain model, defined in `agent_lab/domain/`. The
same model powers the REST API schemas, the persistence layer and the agent runtime —
learn it once and you know what every endpoint reads and writes.

<div align="center">

![Entity domain model](domain_model_web.png)

</div>

## Entities

| Entity | What it models |
|---|---|
| **Agent** | An LLM agent *instance* — `agent_name`, `agent_type` (validated against the [registry](DEV_GUIDE.md#register-the-agent-with-discoverable_agent)), active flag and timestamps. One implementation, many configured instances. |
| **AgentSettings** | Key-value configuration of an agent instance: prompts (Jinja2 templates), collection names, temperature, custom values. Up to 16,000 characters per value — this is where agent behavior is tuned via `POST /agents/update_setting`. |
| **LanguageModel** | A language model available to agents, with its supplier connection. |
| **LanguageModelSettings** | Per-model parameters (temperature, max tokens, …), managed via the `/llms` endpoints. |
| **Integration** | An external integration (e.g. an AI supplier) and its configuration. Secrets are stored in [Vault](VAULT.md), never in the database. |
| **Message** | One conversation turn: role (`human` / `assistant` / `tool`), content, `response_data`, and thread links (`replies_to`). Persisted with the agent's memory via LangGraph checkpoints. |
| **Attachment** | A file attached to a message: raw content, parsed content, and the embeddings collection reference used for retrieval. |

An example of persisted agent settings — prompts and custom values for the voice
memos agent — from
[notebooks/08_test_agent_type-multiagent-voice-assistant.ipynb](../notebooks/08_test_agent_type-multiagent-voice-assistant.ipynb):

<div align="center">

![Agent Settings Example](agent_settings_example.png)

</div>

## Where data lives

Agent-Lab uses **three PostgreSQL databases** (plus Redis) — provisioned by the
[deployment guide](SETUP.md) and configured via `db.url`, `db.vectors` and
`db.checkpoints` (see the [Configuration reference](CONFIGURATION.md)):

| Store | Contents |
|---|---|
| `db.url` | Relational data: agents, settings, models, integrations, messages, attachments |
| `db.vectors` | pgvector embeddings — vector search and retrieval (`/attachments/embeddings`) |
| `db.checkpoints` | LangGraph checkpoint data — agent memory across interactions |
| Redis (`broker.url`) | Pub/sub broker for status updates on long-running operations; also MCP OAuth client storage |

## Security and secrets management

Secrets — integration credentials, model API keys, the configuration payload itself —
are managed with [Vault](VAULT.md). The database stores references; the sensitive
values are retrieved from Vault at startup and on demand. See
[Secrets with Vault](VAULT.md) and the [Configuration reference](CONFIGURATION.md#vault-secret-payload).

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Testing & Simulations](TESTS.md) |
| ➡️ Next | [Researcher's Guide](RESEARCHER_GUIDE.md) |
