variable "langwatch_fqdn" {
  type        = string
  description = "FQDN for LangWatch access (e.g., langwatch.local or a public domain)"
}

variable "pg_image" {
  type        = string
  default     = "bsantanna/cloudnative-pg-vector:17.4"
  description = "PostgreSQL image with pgvector (adjust if needed)"
}

variable "auth_url" {
  type        = string
  description = "Public Keycloak URL, e.g. https://keycloak.example.com (must match the hostname Keycloak stamps as token issuer)"
}

variable "auth_realm" {
  type        = string
  description = "Keycloak realm hosting the LangWatch SSO client"
  default     = "agent-lab"
}

variable "auth_admin_username" {
  type        = string
  description = "Keycloak admin username used to provision the LangWatch client"
  sensitive   = true
}

variable "auth_admin_secret" {
  type        = string
  description = "Keycloak admin password used to provision the LangWatch client"
  sensitive   = true
}

variable "auth_client_id" {
  type        = string
  description = "Keycloak OIDC client ID for LangWatch"
  default     = "langwatch"
}
