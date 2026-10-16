<h2 align="center"><a href="https://github.com/btech-software/agent-lab">Agent-Lab | 🤖🧪</a></h2>
<h3 align="center">Auth with Keycloak</h3>

<p align="center">
  <em>OIDC authentication for the REST API and MCP server</em><br>
  <strong>Type</strong> · How-to &nbsp;|&nbsp; <strong>Audience</strong> · Operators &amp; developers
</p>

---

#### Table of Contents

- [How Agent-Lab uses Keycloak](#how-agent-lab-uses-keycloak)
- [Configure a realm, client and service account](#configure-a-realm-client-and-service-account)
- [Issue and verify tokens](#issue-and-verify-tokens)
- [Automated provisioning](#automated-provisioning)

---

## How Agent-Lab uses Keycloak

[Keycloak](https://www.keycloak.org/) manages authentication and authorization via
OpenID Connect. When `auth.enabled` is `true` (see the
[Configuration reference](CONFIGURATION.md)):

- the FastAPI middleware validates bearer tokens against the realm's JWKS on every
  request, with the standard exclusions (`/auth/*`, `/status/*`, `/docs`,
  `/openapi.json`, `/mcp`, `/static`);
- the `/auth` router exposes login, renewal, profile and a Microsoft Entra ID
  exchange endpoint;
- the [MCP server](MCP.md) authenticates clients through an OAuth proxy backed by
  the same realm, publishing the standard `.well-known` metadata endpoints.

## Configure a realm, client and service account

The steps below use the Keycloak Admin API. Set your admin credentials and endpoint
first:

```bash
export ADMIN_USER=<admin_username>
export ADMIN_PASS=<admin_password>
export ADMIN_TOKEN=$(curl -s -X POST "https://<auth_fqdn>/realms/master/protocol/openid-connect/token" \
    -d "username=${ADMIN_USER}&password=${ADMIN_PASS}&grant_type=password&client_id=admin-cli" | jq -r '.access_token')
```

**Create a realm** (replace `<realm_name>`):

```bash
curl -X POST https://<auth_fqdn>/admin/realms \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{"realm": "<realm_name>", "enabled": true}'
```

**Create a client** for Agent-Lab:

```bash
curl -X POST https://<auth_fqdn>/admin/realms/<realm_name>/clients \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "clientId": "<client_name>",
    "enabled": true,
    "protocol": "openid-connect",
    "publicClient": false,
    "redirectUris": ["https://<agent_lab_fqdn>/*"],
    "standardFlowEnabled": true,
    "clientAuthenticatorType": "client-secret"
  }'
```

**Obtain the client secret:**

```bash
export CLIENT_ID=$(curl -X GET "https://<auth_fqdn>/admin/realms/<realm_name>/clients?clientId=<client_name>" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" | jq -r '.[0].id')

export CLIENT_SECRET=$(curl -X GET "https://<auth_fqdn>/admin/realms/<realm_name>/clients/${CLIENT_ID}/client-secret" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" | jq -r '.value')
```

These values map to the `auth.*` configuration keys (`auth.url`, `auth.realm`,
`auth.client_id`, `auth.client_secret`) — store them in the Vault payload per the
[Configuration reference](CONFIGURATION.md#vault-secret-payload).

**Create a service account user:**

```bash
curl -X POST https://<auth_fqdn>/admin/realms/<realm_name>/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "username": "<username>",
    "enabled": true,
    "email": "<username>@example.com",
    "credentials": [{"type": "password", "value": "<user_password>", "temporary": false}]
  }'
```

Fine-tune roles and mappers in the Keycloak UI if needed.

## Issue and verify tokens

**Get a user token** (password grant — the same flow `POST /auth/login` performs on
the app side):

```bash
export USER_TOKEN=$(curl -s -X POST https://<auth_fqdn>/realms/<realm_name>/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=<client_name>" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "username=<username>" \
  -d "password=<user_password>" | jq -r '.access_token')

curl -s https://<agent_lab_fqdn>/agents/list -H "Authorization: Bearer $USER_TOKEN" | jq
```

Tokens renew via `POST /auth/renew`, and users authenticated in Microsoft Entra ID
can be exchanged for app tokens via `POST /auth/exchange` (PKCE authorization-code
flow, backed by the Entra ID credentials in the configuration).

## Automated provisioning

The Terraform module `terraform/12_agent-lab-auth-realm/` (part of the
[deployment guide](SETUP.md)) provisions the realm, client and service account for
the reference deployment — use it in real environments instead of the manual steps.

---

#### What's next?

| | Page |
|---|---|
| ⬅️ Previous | [Deployment](SETUP.md) |
| ➡️ Next | [Secrets with Vault](VAULT.md) |
