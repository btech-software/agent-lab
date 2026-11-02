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


class TestVaultTlsVerification:
    def _verify_kwargs(self, tmp_path):
        jwt_path = tmp_path / "token"
        jwt_path.write_text("sa-jwt")
        sources = [
            VaultConfigSource(url="https://vault:8200", token="root"),
            KubernetesVaultConfigSource(
                url="https://vault:8200", role="r", jwt_path=str(jwt_path)
            ),
        ]
        verify = []
        for source in sources:
            with patch("hvac.Client") as client_cls:
                client_cls.return_value.secrets.kv.read_secret_version.return_value = {
                    "data": {"data": APP_SECRETS}
                }
                source.load()
            verify.extend(c.kwargs["verify"] for c in client_cls.call_args_list)
        return verify

    def test_verifies_certificates_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VAULT_SKIP_VERIFY", raising=False)
        monkeypatch.delenv("VAULT_CACERT", raising=False)
        assert self._verify_kwargs(tmp_path) == [True, True, True]

    def test_custom_ca_bundle(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VAULT_SKIP_VERIFY", raising=False)
        monkeypatch.setenv("VAULT_CACERT", "/etc/ssl/vault-ca.pem")
        assert set(self._verify_kwargs(tmp_path)) == {"/etc/ssl/vault-ca.pem"}

    def test_explicit_opt_out(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VAULT_SKIP_VERIFY", "true")
        assert set(self._verify_kwargs(tmp_path)) == {False}

    def test_container_vault_client_uses_same_setting(self, monkeypatch):
        from agent_lab.core.container import Container

        monkeypatch.delenv("VAULT_SKIP_VERIFY", raising=False)
        monkeypatch.delenv("VAULT_CACERT", raising=False)
        assert Container.vault_client.kwargs["verify"]() is True


class TestKubernetesVaultClientRelogin:
    """The container shares one Vault client for the process, so a Kubernetes
    login token must be replaced before its lease (the role's token_ttl) ends."""

    def _client(self, tmp_path, lease_duration=3600):
        from agent_lab.core.config import build_vault_client

        jwt_path = tmp_path / "token"
        jwt_path.write_text("sa-jwt")
        calls = []

        def fake_request(adapter, method, url, headers=None, **kwargs):
            calls.append((method, url, adapter.token))
            if url == "/v1/auth/kubernetes/login":
                assert kwargs["json"] == {"role": "my-app", "jwt": "sa-jwt"}
                login_number = sum(1 for c in calls if c[1] == url)
                return {
                    "auth": {
                        "client_token": f"token-{login_number}",
                        "lease_duration": lease_duration,
                    }
                }
            return {"data": {"data": {"k": "v"}}}

        client = build_vault_client(
            url="http://vault:8200",
            token="startup-token",
            verify=True,
            k8s_role="my-app",
            k8s_jwt_path=str(jwt_path),
        )
        return client, calls, fake_request

    def _read(self, client):
        client.secrets.kv.read_secret_version(
            path="integration_1", raise_on_deleted_version=False
        )

    def test_logs_in_before_first_request_and_reuses_token(self, tmp_path):
        client, calls, fake_request = self._client(tmp_path)
        with (
            patch("hvac.adapters.JSONAdapter.request", fake_request),
            patch("agent_lab.core.config.time.monotonic", return_value=1000.0),
        ):
            self._read(client)
            self._read(client)

        assert [(c[1], c[2]) for c in calls] == [
            ("/v1/auth/kubernetes/login", "startup-token"),
            ("/v1/secret/data/integration_1", "token-1"),
            ("/v1/secret/data/integration_1", "token-1"),
        ]

    def test_logs_in_again_before_lease_expires(self, tmp_path):
        client, calls, fake_request = self._client(tmp_path, lease_duration=3600)
        clock = [1000.0]
        with (
            patch("hvac.adapters.JSONAdapter.request", fake_request),
            patch("agent_lab.core.config.time.monotonic", lambda: clock[0]),
        ):
            self._read(client)
            clock[0] += 3600 * 0.9  # still inside the lease
            self._read(client)

        logins = [c for c in calls if c[1] == "/v1/auth/kubernetes/login"]
        assert len(logins) == 2
        assert calls[-1] == ("get", "/v1/secret/data/integration_1", "token-2")

    def test_static_token_client_without_role(self):
        from agent_lab.core.config import build_vault_client

        client = build_vault_client(
            url="http://vault:8200", token="root", verify=True, k8s_role=None
        )

        assert client.token == "root"


def test_kubernetes_source_passes_role_to_client_config(tmp_path):
    jwt_path = tmp_path / "token"
    jwt_path.write_text("sa-jwt")
    source = KubernetesVaultConfigSource(
        url="http://vault:8200", role="my-app", jwt_path=str(jwt_path)
    )

    with patch("hvac.Client") as client_cls:
        client_cls.return_value.secrets.kv.read_secret_version.return_value = {
            "data": {"data": APP_SECRETS}
        }
        config = source.load()

    assert config["vault"]["k8s_role"] == "my-app"
    assert config["vault"]["k8s_jwt_path"] == str(jwt_path)
