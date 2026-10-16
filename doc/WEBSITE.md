# ⚠️ INTERNAL — Website Mapping Spec

**This file is a working document for the website milestone, not user documentation.**
Do not link it from user-facing pages; the site generator should exclude it.

---

## Purpose

Define the mechanical mapping from this documentation set (`doc/`) to the future
product website, so the site build is a transformation, not a rewrite. The doc set
was structured around this contract:

## The style contract (machine-parseable)

Every user-facing page follows the same shape, which doubles as front matter:

| Site field | Doc source |
|---|---|
| `title` | The `<h3>` under the project header |
| `subtitle` | The `<em>` line inside the first `<p>` |
| `type` | The first `<strong>Type</strong> · X` — one of: Tutorial, Guide, Reference, How-to, Explanation, Index, Project |
| `audience` | The `<strong>Audience</strong> · X` |
| `nav` | Prev/next links in the `#### What's next?` footer |
| `toc` | The `#### Table of Contents` list (GitHub-anchor style) |

Body conventions: imperative voice, code-first, complete runnable snippets (no
`…` fragments), prerequisites up top, relative links *inside* `doc/` only.

## Page inventory → site structure

| File | Site section | Nav label | Type | Audience | Assets |
|---|---|---|---|---|---|
| `README.md` | Docs home | Documentation | Index | Everyone | — |
| `TUTORIAL.md` | Getting Started | Your First Agent | Tutorial | Newcomers | — |
| `DEV_GUIDE.md` | Build | Developer's Guide | Guide | Developers, contributors | `agent_base_classes_web.png`, `agent_settings_example.png` |
| `CONFIGURATION.md` | Reference | Configuration Reference | Reference | Operators, developers | — |
| `REST_API.md` | Reference | REST API | Reference | API consumers | — |
| `MCP.md` | Build | MCP Server | Guide | Developers | `mcp_inspector_demo.gif`, `claude_setup_1-4.png`, `claude_demo.gif/png` |
| `OTEL.md` | Observe | Observability | Explanation + How-to | Developers, operators | — |
| `otel/GRAFANA.md` | Observe | Grafana | How-to | Developers, operators | `grafana_demo.gif` |
| `otel/OPENSEARCH.md` | Observe | OpenSearch Dashboards | How-to | Developers, operators | `opensearch_dashboards_demo.gif` |
| `TESTS.md` | Evaluate | Testing & Simulations | Guide | Developers, researchers | — |
| `DOMAIN.md` | Reference | Entity Domain Model | Explanation | Developers, contributors | `domain_model_web.png`, `agent_settings_example.png` |
| `RESEARCHER_GUIDE.md` | Evaluate | Researcher's Guide | Guide | Researchers | — |
| `SETUP.md` | Deploy & Operate | Deployment | How-to | Operators | `docker_desktop_kubernetes.png`, `agent_lab_deployment_example.png` |
| `KEYCLOAK.md` | Deploy & Operate | Auth with Keycloak | How-to | Operators, developers | — |
| `VAULT.md` | Deploy & Operate | Secrets with Vault | How-to | Operators, developers | — |
| `ACKNOWLEDGEMENT.md` | Community | Acknowledgements | Project | Everyone | — |
| `LICENSE.md` | Community | License | Project | Everyone | — |

**Deleted:** `ETL.md` (was a `WIP...` stub; no ETL code exists — confirmed against
`pyproject.toml`, Makefile, terraform).

## Prev/next chain (default reading order)

`README.md` → `TUTORIAL.md` → `DEV_GUIDE.md` → `CONFIGURATION.md` →
`REST_API.md` → `MCP.md` → `OTEL.md` → `TESTS.md` → `DOMAIN.md` →
`RESEARCHER_GUIDE.md` → `SETUP.md` → `KEYCLOAK.md` → `VAULT.md` →
`ACKNOWLEDGEMENT.md` → `LICENSE.md` → (leaf: `otel/GRAFANA.md` →
`otel/OPENSEARCH.md`)

## Site IA sketch (aligned with the Spring Boot reference model)

1. **Home** — hero (build / simulate / test pillars), quickstart code block,
   audience cards (reuse root `README.md` copy as the base).
2. **Getting Started** — `TUTORIAL.md` (split into steps or kept as one page).
3. **Build** — `DEV_GUIDE.md` (candidate to split by its H2 sections into subpages:
   setup / running / practices / building agents / extending) + `MCP.md`.
4. **Evaluate** — `TESTS.md` + `RESEARCHER_GUIDE.md`.
5. **Observe** — `OTEL.md` + the two dashboard pages.
6. **Deploy & Operate** — `SETUP.md` + `KEYCLOAK.md` + `VAULT.md`.
7. **Reference** — `REST_API.md` + `CONFIGURATION.md` + `DOMAIN.md`.
8. **Community** — acknowledgements, license, contributing.

## Build-time generation opportunities

- **REST API table** — generate from the app's `openapi.json` instead of the
  hand-maintained table; keep the hand-written examples.
- **Configuration reference** — generate the key table from `agent_lab/core/config.py`
  + `config-*.yml`; keep hand-written purpose/description columns if not derivable.
- **Endpoint table in `REST_API.md`** — verify against `agent_lab/interface/api/`
  at build time in CI to catch drift.

## Content sources for the site

- Hero copy / pitch: root `README.md` (canonical — keep in sync).
- Style reference: Spring Boot Reference (structure) + FastAPI (voice).
- Screenshots: re-record `claude_demo.gif`, `mcp_inspector_demo.gif`,
  `grafana_demo.gif`, `opensearch_dashboards_demo.gif` before site launch if the UI
  changed; statics are safe (`*.png`).
