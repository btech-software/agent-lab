# Security Policy

## Supported Versions

Agent-Lab is versioned with [python-semantic-release](https://github.com/python-semantic-release/python-semantic-release); releases are cut from `main` and no maintenance branches are kept for older lines, so security fixes target the latest release line and `main`.

| Version              | Supported          |
| -------------------- | ------------------ |
| 1.17.x (latest line) | :white_check_mark: |
| `main` (development) | :white_check_mark: |
| < 1.17               | :x:                |

Dependency security updates are applied automatically via weekly [Dependabot](.github/dependabot.yml) runs on the `uv` ecosystem (minor/patch updates grouped).

## Reporting a Vulnerability

**Do not report vulnerabilities through public GitHub issues.**

Use GitHub's private vulnerability reporting:

> https://github.com/btech-software/agent-lab/security/advisories/new

Please include:

- A description of the vulnerability and its impact.
- The affected component(s): the FastAPI API (`agent_lab/interface/api/`), the MCP server and its Keycloak OAuth proxy (`agent_lab/interface/mcp/`), the agent framework (`agent_lab/services/`), or the deployment configs (`compose-*.yml`, `docker/`, `charts/`).
- The affected version or commit.
- Steps to reproduce — a minimal proof of concept is ideal.
- Any suggested mitigation.

### What to expect

- Acknowledgment within 5 business days.
- Status updates at least every 7 days until resolution.
- **Accepted**: the fix is developed privately, released as a patch to the supported version line, and disclosed once a fixed release is available. Credit is offered to the reporter; a CVE is requested via GitHub when warranted.
- **Declined**: a short explanation of why.

### Out of scope

- Issues that require privileged access to the host or container itself.
- Reports without a reproduction or with no plausible impact.

## Security Fix History

### Unreleased (after 1.17.9) — internal security audit remediation

Fixes from an internal audit, landed in `e25d929` and `a37ab31`.

**Authentication and access control**

- Public-path auth exclusions (`/status`, `/.well-known`, `/mcp`, `/static`) are anchored to whole path segments. Paths that only share a prefix, such as `/statusx` or `/static-evil/…`, now require authentication.
- The task-updates WebSocket checks that the agent belongs to the caller's tenant. If it doesn't, the connection is closed with policy violation (1008) before it is accepted.

**Tenant isolation (vector store)**

- Embedding collections are named `<tenant schema>/<collection>`, so retrieval and deletion only reach the caller's own tenant. Every RAG agent passes the tenant schema to search.
- The vector repository validates tenant schema names itself, against a strict identifier pattern, before touching any store.
- Deleting an attachment also deletes its embedding chunks.
- Re-embedding replaces an attachment's chunks atomically: new chunks are written first, then the old ones are deleted, so a failed re-embed keeps the previous chunks.
- A blank `collection_name` is rejected.

**Input validation and SSRF**

- Integration endpoints must be `http(s)` URLs with a host.
- The web-crawl tool rejects sources that are not `http(s)`.
- Azure Graph lookups escape OData string literals and percent-encode the email path segment (an injection fix).

**Secrets and credentials**

- Debug request/response logging redacts `Authorization`, `Cookie`, `Set-Cookie` and `Proxy-Authorization`.
- Integration Vault secrets no longer leak:
  - Deleting an integration removes its secret.
  - A failed create discards the secret it just wrote, unless the database row has already committed.
  - A cleanup failure is logged without masking the original error.
- Vault TLS verification is on by default. `VAULT_CACERT` supplies a private CA; `VAULT_SKIP_VERIFY` turns verification off and is meant for development only. See [CONFIGURATION.md](doc/CONFIGURATION.md).

**Resource exhaustion and robustness**

- Agent runs go through a dedicated thread limiter (16 concurrent runs). Long runs can no longer use up the shared thread pool and starve the health probes.
- Model clients use the tenant's configured `timeout`.
- The vector store reuses one database engine per URL instead of building one per call.
- Attachment processing uses self-cleaning temporary directories.
- The audio optimizer writes beside its input and removes partial output when ffmpeg fails.

**Release integrity**

- The Helm chart version advances with each release.
- The chart publish job fails rather than overwrite an archive that is already published on `gh-pages`.
