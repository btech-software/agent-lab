# Agent-Lab project template

Cookiecutter template scaffolding a downstream application on the
`btech-agent-lab` library.

## Usage

```bash
uvx cookiecutter gh:btech-software/agent-lab --directory cookiecutter
```

Or from a local checkout:

```bash
uvx cookiecutter /path/to/agent-lab --directory cookiecutter
```

## Variables

| Variable | Default | Effect |
|---|---|---|
| `project_name` | `My Agent App` | Human-readable name; `project_slug` (kebab) and `package_name` (snake) derive from it |
| `agent_lab_version` | current release | Lower bound of the generated `btech-agent-lab>=X.Y.Z,<X+1.0.0` dependency range; bumped automatically by semantic-release |
| `github_repository` | `your-org/<slug>` | GitHub `owner/repo` of the generated project; used for the Flux git URL and the `ghcr.io/<owner>/<repo>` image reference |
| `include_docker` | `false` | `docker/`, `compose.yml`, `config-docker.yml`, and the ReAct workflow example agent |
| `include_github_actions` | `false` | `.github/workflows/ci.yml` (lint + tests) |
| `include_testcontainers` | `false` | `tests/integration/` harness (Postgres, Redis, Vault) |
| `include_claude_plugin` | `false` | `.claude-plugin/marketplace.json` + `plugins/<slug>-dev/` (feature-dev workflow plugin) |
| `include_release_pipeline` | `false` | `.github/workflows/release.yml` (python-semantic-release) and `[tool.semantic_release]` in `pyproject.toml`; with `include_docker` also `docker-image.yml` (ghcr.io + cosign). Requires `include_github_actions` |
| `include_aks_gitops` | `false` | `terraform/aks/` (AKS cluster + Flux + Vault config), `gitops/` manifests, and `docs/one-time-setup.md`. Requires `include_docker` |
| `auth_enabled` | `false` | Wires real `auth_*` values into the Vault `app_secrets` payload in `terraform/aks/03_vault_config`: declares `auth_url`/`auth_realm`/`auth_client_id`/`auth_client_secret` (sensitive) terraform variables supplied per environment at apply time. Requires `include_aks_gitops` |

## Maintenance invariants

- **`agents/__init__.py` and `mcp/__init__.py` in the payload must stay empty.**
  Capability discovery is import-driven (`scan_packages` walks and imports
  every submodule), so the toggle deletion matrix in
  `hooks/post_gen_project.py` stays trivially safe only while no `__init__.py`
  imports its siblings.
- **Each toggle owns a disjoint path set** in `post_gen_project.py` — never
  make one deletion rule depend on another toggle's value. One documented
  exception: `.github/workflows/docker-image.yml` needs both
  `include_release_pipeline` and `include_docker`, so both rules remove it
  (`remove()` tolerates already-deleted paths). Invalid toggle combinations
  (`include_release_pipeline` without `include_github_actions`,
  `include_aks_gitops` without `include_docker`, `auth_enabled` without
  `include_aks_gitops`) are rejected
  in `pre_gen_project.py` instead of being patched up after generation.
- **Runtime Jinja must not pass through cookiecutter's renderer.** Files
  containing runtime `{{ ... }}` templates (agent prompt files) or GitHub
  Actions `${{ ... }}` expressions (release.yml, docker-image.yml) are listed
  in `_copy_without_render` in `cookiecutter.json`; README snippets and the
  single expression in ci.yml use `{% raw %}` blocks.
- **Template `.py` payload files are not valid Python before rendering** —
  they are excluded from the host repo's ruff/pre-commit AST hooks. The hooks
  in `hooks/` ARE valid Python (Jinja only inside string literals) and stay
  lint-clean.
- The bake matrix (all 128 toggle combinations, including the invalid ones,
  which assert the `pre_gen` rejection) is tested in
  `tests/template/test_bake_structural.py`; a deeper opt-in test
  (`-m cookiecutter_bake`) installs a baked project against this repo's
  working tree and runs its smoke tests. Adding a new toggle means updating
  `cookiecutter.json`, the deletion matrix, and both tests.
- `agent_lab_version` in `cookiecutter.json` is listed in
  `[tool.semantic_release] version_variables`, and a consistency test asserts
  it matches `pyproject.toml`'s version.
