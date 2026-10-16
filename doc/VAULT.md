<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Secrets with Vault</h3>

<p align="center">
  <em>Where Agent-Lab keeps its secrets — and how it retrieves them</em><br>
  <strong>Type</strong> · How-to &nbsp;|&nbsp; <strong>Audience</strong> · Operators &amp; developers
</p>

---

#### Table of Contents

- [How Agent-Lab uses Vault](#how-agent-lab-uses-vault)
- [Setting up Vault](#setting-up-vault)
- [Provisioning the secret payload](#provisioning-the-secret-payload)
- [Production](#production)

---

## How Agent-Lab uses Vault

Agent-Lab uses [HashiCorp Vault](https://www.hashicorp.com/en/products/vault) for
secure secret management: API keys, database credentials and other sensitive values
live in Vault, not in the database or environment files. During application startup
the active [`ConfigSource`](CONFIGURATION.md#how-configuration-is-loaded) connects to
Vault and loads the configuration payload; [Integrations](DOMAIN.md#entities) store
*references* in the database while the sensitive values are fetched from Vault on
demand.

## Setting up Vault

For local development, the Compose stacks ship a Vault server with a development
configuration (UI at [http://localhost:8200](http://localhost:8200), login token
`dev-only-token`). See [Running the Application](DEV_GUIDE.md#running-the-application).

For production, provision the instance with the Terraform module
`terraform/08_vault-instance/` from the [deployment guide](SETUP.md) — including the
`init` + `unseal` sequence:

```bash
kubectl --namespace vault exec vault-0 -- vault operator init \
    -key-shares=1 \
    -key-threshold=1 \
    -format=json > cluster-keys.json

export VAULT_UNSEAL_KEY=$(jq -r ".unseal_keys_b64[]" cluster-keys.json)
kubectl --namespace vault exec vault-0 -- vault operator unseal $VAULT_UNSEAL_KEY
```

## Provisioning the secret payload

`VaultConfigSource` reads a single KV-v2 secret — mount `secret`, path
`app_secrets` — and maps it onto the application's
[configuration keys](CONFIGURATION.md#configuration-keys). The payload keys are
listed in the [Configuration reference](CONFIGURATION.md#vault-secret-payload);
write it once with the Vault CLI:

```bash
vault kv put secret/app_secrets \
  api_base_url="https://<agent_lab_fqdn>" \
  cdp_url="http://<cdp_host>:9222" \
  auth_enabled="true" \
  auth_url="https://<auth_fqdn>" \
  auth_realm="<realm_name>" \
  auth_client_id="<client_name>" \
  auth_client_secret="<client_secret>" \
  broker_url="redis://:<password>@<redis_host>:6379/0" \
  db_url="postgresql://<user>:<pass>@<db_host>:5432/agent_lab" \
  db_vectors="postgresql://<user>:<pass>@<db_host>:5432/agent_lab_vectors" \
  db_checkpoints="postgresql://<user>:<pass>@<db_host>:5432/agent_lab_checkpoints"
```

When the app cannot (or should not) use a static `VAULT_TOKEN`, the default source
switches to `KubernetesVaultConfigSource` automatically when `VAULT_K8S_ROLE` is set
— it authenticates with the pod's projected ServiceAccount token, so no static token
needs provisioning or rotation.

## Production

Following our cloud-native principles, we recommend the
[Vault Kubernetes HA setup](https://developer.hashicorp.com/vault/docs/deploy/kubernetes).
The `15_agent-lab-dependencies/` Terraform module wires the runtime credentials; the
app picks everything up at startup via
[the configuration contract](CONFIGURATION.md#how-configuration-is-loaded).

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Auth with Keycloak](KEYCLOAK.md) |
| ➡️ Next | [Acknowledgements](ACKNOWLEDGEMENT.md) |
