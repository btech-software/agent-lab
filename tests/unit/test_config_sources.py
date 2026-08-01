"""Unit tests for Vault-backed config sources in agent_lab.core.config.

Self-contained (mocks only) — safe to run standalone with
``pytest --noconftest tests/unit/test_config_sources.py`` to skip the
testcontainers boot.
"""

from unittest.mock import patch

from agent_lab.core.config import (
    KubernetesVaultConfigSource,
    VaultConfigSource,
    YamlConfigSource,
    default_config_source,
)

APP_SECRETS = {
    "api_base_url": "http://app",
    "cdp_url": "",
    "auth_enabled": False,
    "auth_url": "",
    "auth_realm": "",
    "auth_client_id": "",
    "auth_client_secret": "",
    "broker_url": "redis://broker:6379/0",
    "db_url": "postgresql://app",
    "db_vectors": "postgresql://vectors",
    "db_checkpoints": "postgresql://checkpoints",
}


def test_kubernetes_source_logs_in_with_service_account_token(tmp_path):
    jwt_path = tmp_path / "token"
    jwt_path.write_text("sa-jwt")
    source = KubernetesVaultConfigSource(
        url="http://vault:8200", role="my-app", jwt_path=str(jwt_path)
    )

    with patch("hvac.Client") as client_cls:
        client = client_cls.return_value
        client.token = "issued-token"
        client.secrets.kv.read_secret_version.return_value = {
            "data": {"data": APP_SECRETS}
        }
        config = source.load()

    client.auth.kubernetes.login.assert_called_once_with(role="my-app", jwt="sa-jwt")
    assert source.token == "issued-token"
    assert config["api_base_url"] == APP_SECRETS["api_base_url"]
    assert config["broker"]["url"] == APP_SECRETS["broker_url"]
    assert config["db"]["checkpoints"] == APP_SECRETS["db_checkpoints"]


def _load_vault_config():
    source = VaultConfigSource(url="http://vault:8200", token="root")
    with patch("hvac.Client") as client_cls:
        client_cls.return_value.secrets.kv.read_secret_version.return_value = {
            "data": {"data": APP_SECRETS}
        }
        return source.load()


def test_vault_source_disables_static_when_directory_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "missing"))

    config = _load_vault_config()

    assert config["static"]["enabled"] is False


def test_vault_source_enables_static_when_directory_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))

    config = _load_vault_config()

    assert config["static"]["enabled"] is True
    assert config["static"]["directory"] == str(tmp_path)


def test_default_config_source_prefers_kubernetes_role(monkeypatch):
    monkeypatch.setenv("VAULT_K8S_ROLE", "my-app")
    monkeypatch.setenv("VAULT_URL", "http://vault:8200")
    monkeypatch.setenv("DOCKER", "1")

    source = default_config_source()

    assert isinstance(source, KubernetesVaultConfigSource)
    assert source.role == "my-app"
    assert source.url == "http://vault:8200"


def test_default_config_source_without_role_keeps_yaml_selection(monkeypatch):
    monkeypatch.delenv("VAULT_K8S_ROLE", raising=False)
    monkeypatch.setenv("DOCKER", "1")

    source = default_config_source()

    assert isinstance(source, YamlConfigSource)
    assert source.path == "config-docker.yml"
