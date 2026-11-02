import os
import threading
import time
from abc import ABC, abstractmethod

from hvac.adapters import JSONAdapter


class ConfigSource(ABC):
    """Strategy for loading the application configuration dictionary.

    Downstream apps provide their own subclass (or wrap these) to add keys or
    use a different secrets backend, and pass it to ``create_app(config_source=...)``.
    """

    @abstractmethod
    def load(self) -> dict:
        pass


class YamlConfigSource(ConfigSource):
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        import yaml

        with open(self.path) as config_file:
            return yaml.safe_load(config_file)


def vault_tls_verify() -> bool | str:
    """TLS verification for Vault clients, using Vault's standard env vars:
    VAULT_SKIP_VERIFY opts out, VAULT_CACERT names a CA bundle, default verifies."""
    if os.getenv("VAULT_SKIP_VERIFY", "").lower() in ("1", "true", "yes"):
        return False
    return os.getenv("VAULT_CACERT") or True


class VaultConfigSource(ConfigSource):
    def __init__(
        self,
        url: str,
        token: str,
        engine_path: str = "secret",
        secret_path: str = "app_secrets",
    ):
        self.url = url
        self.token = token
        self.engine_path = engine_path
        self.secret_path = secret_path

    def load(self) -> dict:
        import hvac

        client = hvac.Client(url=self.url, token=self.token, verify=vault_tls_verify())
        app_secrets = client.secrets.kv.read_secret_version(
            raise_on_deleted_version=False,
            path=self.secret_path,
            mount_point=self.engine_path,
        )["data"]["data"]
        return {
            "api_base_url": app_secrets["api_base_url"],
            "cdp_url": app_secrets["cdp_url"],
            "auth": {
                "enabled": app_secrets["auth_enabled"],
                "url": app_secrets["auth_url"],
                "realm": app_secrets["auth_realm"],
                "client_id": app_secrets["auth_client_id"],
                "client_secret": app_secrets["auth_client_secret"],
            },
            "vault": {"url": self.url, "token": self.token},
            "broker": {"url": app_secrets["broker_url"]},
            # Vault holds only secrets, so static serving is a code convention:
            # enabled when a SPA build exists under STATIC_DIR (each app points
            # this at its own package dir; images without a frontend boot with
            # static serving off). setup_auth() derives the public-path
            # exclusions from the router prefixes, so nothing to configure here.
            "static": {
                "enabled": os.path.isdir(
                    os.getenv("STATIC_DIR", "static/frontend/browser")
                ),
                "directory": os.getenv("STATIC_DIR", "static/frontend/browser"),
                "index_file": "index.html",
                "mount_path": "/",
            },
            "db": {
                "url": app_secrets["db_url"],
                "vectors": app_secrets["db_vectors"],
                "checkpoints": app_secrets["db_checkpoints"],
            },
        }


SERVICE_ACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


class KubernetesVaultConfigSource(VaultConfigSource):
    """VaultConfigSource that authenticates through Vault's Kubernetes auth
    method with the pod's projected ServiceAccount token, so no static
    VAULT_TOKEN has to be provisioned or rotated.
    """

    def __init__(
        self,
        url: str,
        role: str,
        engine_path: str = "secret",
        secret_path: str = "app_secrets",
        jwt_path: str = SERVICE_ACCOUNT_TOKEN_PATH,
    ):
        super().__init__(
            url=url, token=None, engine_path=engine_path, secret_path=secret_path
        )
        self.role = role
        self.jwt_path = jwt_path

    def load(self) -> dict:
        import hvac

        client = hvac.Client(url=self.url, verify=vault_tls_verify())
        with open(self.jwt_path) as jwt_file:
            client.auth.kubernetes.login(role=self.role, jwt=jwt_file.read())
        self.token = client.token
        config = super().load()
        # lets the container's long-lived client log in again (build_vault_client)
        config["vault"]["k8s_role"] = self.role
        config["vault"]["k8s_jwt_path"] = self.jwt_path
        return config


class KubernetesLoginAdapter(JSONAdapter):
    """hvac adapter that logs in with the pod's ServiceAccount token and logs
    in again once 80% of the token's lease has passed, so a process-wide
    client never sends an expired token."""

    def __init__(self, *args, role: str, jwt_path: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        self.jwt_path = jwt_path
        # the startup token's lease is unknown: log in on first use
        self._renew_at = 0.0
        self._lock = threading.Lock()

    def request(self, method, url, headers=None, raise_exception=True, **kwargs):
        self._ensure_token()
        return super().request(
            method, url, headers=headers, raise_exception=raise_exception, **kwargs
        )

    def _ensure_token(self):
        with self._lock:
            if time.monotonic() < self._renew_at:
                return
            with open(self.jwt_path) as jwt_file:
                jwt = jwt_file.read()
            # super().request: bypass _ensure_token for the login call itself
            response = super().request(
                "post",
                "/v1/auth/kubernetes/login",
                json={"role": self.role, "jwt": jwt},
            )
            self.token = self.get_login_token(response)
            lease = response["auth"]["lease_duration"]
            self._renew_at = time.monotonic() + lease * 0.8 if lease else float("inf")


def build_vault_client(
    url: str,
    token: str | None,
    verify: bool | str,
    k8s_role: str | None = None,
    k8s_jwt_path: str | None = None,
):
    import hvac

    if k8s_role:
        return hvac.Client(
            url=url,
            token=token,
            verify=verify,
            adapter=KubernetesLoginAdapter,
            role=k8s_role,
            jwt_path=k8s_jwt_path or SERVICE_ACCOUNT_TOKEN_PATH,
        )
    return hvac.Client(url=url, token=token, verify=verify)


def default_config_source() -> ConfigSource:
    if os.getenv("VAULT_K8S_ROLE"):
        return KubernetesVaultConfigSource(
            url=os.getenv("VAULT_URL"),
            role=os.getenv("VAULT_K8S_ROLE"),
            engine_path=os.getenv("VAULT_ENGINE_PATH", "secret"),
            secret_path=os.getenv("VAULT_SECRET_PATH", "app_secrets"),
        )
    if os.getenv("DOCKER"):
        return YamlConfigSource("config-docker.yml")
    if os.getenv("TESTING"):
        return YamlConfigSource("config-test.yml")
    if os.getenv("DEVELOPING"):
        return YamlConfigSource("config-dev.yml")
    return VaultConfigSource(
        url=os.getenv("VAULT_URL"),
        token=os.getenv("VAULT_TOKEN"),
        engine_path=os.getenv("VAULT_ENGINE_PATH", "secret"),
        secret_path=os.getenv("VAULT_SECRET_PATH", "app_secrets"),
    )


def load_config(container, source: ConfigSource) -> None:
    container.config.from_dict(source.load())
