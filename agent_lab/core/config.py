import os
from abc import ABC, abstractmethod


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

        client = hvac.Client(url=self.url, token=self.token, verify=False)
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

        client = hvac.Client(url=self.url, verify=False)
        with open(self.jwt_path) as jwt_file:
            client.auth.kubernetes.login(role=self.role, jwt=jwt_file.read())
        self.token = client.token
        return super().load()


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
