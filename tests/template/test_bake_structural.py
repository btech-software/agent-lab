"""Bake-matrix tests for the cookiecutter template in cookiecutter/.

No containers or network needed — safe to run standalone with
``pytest --noconftest tests/template`` to skip the testcontainers boot.
"""

import itertools
import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from cookiecutter.exceptions import FailedHookException
from cookiecutter.main import cookiecutter

REPO_ROOT = Path(__file__).parents[2]
TEMPLATE_DIR = str(REPO_ROOT / "cookiecutter")
TOGGLES = (
    "include_docker",
    "include_github_actions",
    "include_testcontainers",
    "include_claude_plugin",
    "include_release_pipeline",
    "include_aks_gitops",
    "auth_enabled",
)


def bake(output_dir: Path, **extra_context) -> Path:
    return Path(
        cookiecutter(
            TEMPLATE_DIR,
            no_input=True,
            output_dir=str(output_dir),
            extra_context={"project_name": "Test App", **extra_context},
        )
    )


def toggle_combinations():
    for values in itertools.product([True, False], repeat=len(TOGGLES)):
        yield dict(zip(TOGGLES, values))


@pytest.mark.parametrize(
    "toggles",
    list(toggle_combinations()),
    ids=lambda toggles: "-".join(
        f"{name.removeprefix('include_')}={'on' if value else 'off'}"
        for name, value in toggles.items()
    ),
)
def test_bake_produces_expected_tree(tmp_path, toggles):
    invalid = (
        (toggles["include_release_pipeline"] and not toggles["include_github_actions"])
        or (toggles["include_aks_gitops"] and not toggles["include_docker"])
        or (toggles["auth_enabled"] and not toggles["include_aks_gitops"])
    )
    if invalid:
        with pytest.raises(FailedHookException):
            bake(tmp_path, **toggles)
        return

    root = bake(tmp_path, **toggles)

    assert (root / "docker").exists() == toggles["include_docker"]
    assert (root / "compose.yml").exists() == toggles["include_docker"]
    assert (root / "config-docker.yml").exists() == toggles["include_docker"]
    assert (root / "test_app" / "agents" / "react_agent").exists() == toggles[
        "include_docker"
    ]
    assert (root / ".github").exists() == toggles["include_github_actions"]
    assert (root / "tests" / "integration").exists() == toggles[
        "include_testcontainers"
    ]
    assert (root / ".claude-plugin" / "marketplace.json").exists() == toggles[
        "include_claude_plugin"
    ]
    plugin_dir = root / "plugins" / "test-app-dev"
    assert (plugin_dir / ".claude-plugin" / "plugin.json").exists() == toggles[
        "include_claude_plugin"
    ]
    assert (plugin_dir / "commands" / "test-app-dev.md").exists() == toggles[
        "include_claude_plugin"
    ]
    if toggles["include_claude_plugin"]:
        plugin_readme = (plugin_dir / "README.md").read_text()
        assert "/test-app-dev" in plugin_readme
        assert "/feature-dev" not in plugin_readme
    assert (root / "terraform").exists() == toggles["include_aks_gitops"]
    assert (root / "gitops").exists() == toggles["include_aks_gitops"]
    assert (root / "docs").exists() == toggles["include_aks_gitops"]
    if toggles["include_aks_gitops"]:
        app_kustomization = (
            root / "gitops" / "apps" / "test-app" / "kustomization.yaml"
        ).read_text()
        assert "ghcr.io/your-org/test-app" in app_kustomization
        app_ingress = (
            root / "gitops" / "apps" / "test-app" / "ingress.yaml"
        ).read_text()
        assert "${app_hostname}" in app_ingress
        assert (root / "gitops" / "apps" / "test-app" / "cdp-deployment.yaml").exists()
        assert (root / "terraform" / "aks" / "03_vault_config" / "outputs.tf").exists()
        aks_variables = (
            root / "terraform" / "aks" / "01_aks" / "variables.tf"
        ).read_text()
        assert '"rg-test-app"' in aks_variables
        assert '"aks-test-app"' in aks_variables
        assert '"kv-test-app-unseal"' in aks_variables
        vault_config = root / "terraform" / "aks" / "03_vault_config"
        vault_variables = (vault_config / "variables.tf").read_text()
        assert ('variable "auth_client_secret"' in vault_variables) == toggles[
            "auth_enabled"
        ]
        vault_main = (vault_config / "main.tf").read_text()
        if toggles["auth_enabled"]:
            assert "auth_enabled       = true" in vault_main
            assert "auth_client_secret = var.auth_client_secret" in vault_main
        else:
            assert "auth_enabled       = false" in vault_main
            assert 'auth_client_secret = ""' in vault_main
    workflows = root / ".github" / "workflows"
    assert (workflows / "release.yml").exists() == toggles["include_release_pipeline"]
    assert (workflows / "docker-image.yml").exists() == (
        toggles["include_release_pipeline"] and toggles["include_docker"]
    )

    pyproject_text = (root / "pyproject.toml").read_text()
    assert ("[tool.semantic_release]" in pyproject_text) == toggles[
        "include_release_pipeline"
    ]
    if toggles["include_release_pipeline"]:
        assert ("kustomization.yaml:newTag" in pyproject_text) == toggles[
            "include_aks_gitops"
        ]
        version_variables = tomllib.loads(pyproject_text)["tool"]["semantic_release"][
            "version_variables"
        ]
        for version_variable in version_variables:
            versioned_file = version_variable.rsplit(":", 1)[0]
            assert (root / versioned_file).exists(), (
                f"version_variables references missing file {versioned_file}"
            )

    for py_file in root.rglob("*.py"):
        compile(py_file.read_text(), str(py_file), "exec")

    for rendered_file in root.rglob("*"):
        if rendered_file.is_file():
            assert "{{ cookiecutter" not in rendered_file.read_text(errors="ignore"), (
                f"unrendered template variable in {rendered_file}"
            )

    assert "[tool.uv.sources]" not in (root / "pyproject.toml").read_text()

    subprocess.run(["uv", "run", "ruff", "check", str(root)], cwd=REPO_ROOT, check=True)
    subprocess.run(
        ["uv", "run", "ruff", "format", "--check", str(root)],
        cwd=REPO_ROOT,
        check=True,
    )


def test_runtime_prompt_template_survives_bake(tmp_path):
    root = bake(tmp_path, include_docker=True)
    prompt = (
        root
        / "test_app"
        / "agents"
        / "react_agent"
        / "default_execution_system_prompt.txt"
    ).read_text()
    assert "{{ CURRENT_TIME }}" in prompt


def test_pre_gen_rejects_reserved_package_name(tmp_path):
    with pytest.raises(FailedHookException):
        bake(tmp_path, project_name="Agent Lab")


def test_agent_lab_version_default_matches_library_version():
    pyproject_version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())[
        "project"
    ]["version"]
    template_version = json.loads(
        (REPO_ROOT / "cookiecutter" / "cookiecutter.json").read_text()
    )["agent_lab_version"]

    assert template_version == pyproject_version, (
        "cookiecutter.json's agent_lab_version default has drifted from "
        "pyproject.toml's version — update it (or verify the semantic-release "
        "version_variables substitution actually fired)."
    )
