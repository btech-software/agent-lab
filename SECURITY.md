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
