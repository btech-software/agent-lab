variable "litellm_fqdn" {
  type        = string
  description = "FQDN for LiteLLM access (e.g., litellm.my-domain.com)"
}

variable "trusted_proxy_cidr" {
  type        = string
  default     = "10.1.0.0/16"
  description = "Pod CIDR that the ingress controller (Traefik) connects from; uvicorn trusts X-Forwarded-* headers only from it (docker-desktop default)"
}

variable "pg_image" {
  type        = string
  default     = "bsantanna/cloudnative-pg-vector:17.4"
  description = "PostgreSQL image for the CloudNativePG cluster (adjust if needed)"
}

variable "litellm_chart_version" {
  type        = string
  default     = "1.106.2"
  description = "litellm-helm chart version (OCI: ghcr.io/berriai/litellm-helm). Do NOT use 1.107.0: that release was compromised (supply-chain attack, pulled from PyPI/GHCR/Docker Hub on 2026-10-21)."
}

variable "litellm_image_tag" {
  type        = string
  default     = "v1.106.2"
  description = "LiteLLM proxy image tag (pinned; chart appVersion is 'latest' and must not be relied on). Do NOT use v1.107.0 or :latest/:main-stable: compromised 2026-10-21, see docs.litellm.ai/blog/security-incident-oct-21-2026."
}

variable "upstream_api_base" {
  type        = string
  default     = ""
  description = "Default OpenAI-compatible base URL of the upstream (e.g. http://<lan-host>:<port>/v1). Per-model api_base overrides this."
}

variable "models" {
  description = "OpenAI-compatible models exposed by the gateway. Map key is the model_name clients request; the value maps it to the upstream. api_key is optional and lands in the litellm-env secret, referenced from proxy_config via os.environ/. Decision models (Cloudflare Clef, TypeSafe Jev, vLLM/SGLang structured-decisions servers) need provider = \"hosted_vllm\" and mode = \"evaluation\": the Admin UI lists only model groups whose model_info.mode is evaluation as decision models, and only the hosted_vllm decisions transform speaks System One against a self-hosted api_base (docs.litellm.ai/docs/decisions/providers)."
  sensitive   = true
  type = map(object({
    model    = string
    api_base = optional(string)
    api_key  = optional(string, "")
    provider = optional(string, "openai")
    mode     = optional(string, "")
  }))
  default = {}

  validation {
    condition     = length(var.models) > 0
    error_message = "At least one model is required — the LiteLLM proxy refuses to start with an empty model_list."
  }

  validation {
    condition     = alltrue([for name, m in var.models : can(regex("^[A-Za-z0-9._-]+$", name))])
    error_message = "Model names (map keys) may only contain letters, digits, dots, dashes and underscores."
  }

  validation {
    condition     = alltrue([for m in var.models : coalesce(m.api_base, "") != "" || var.upstream_api_base != ""])
    error_message = "Every model needs an api_base, or the upstream_api_base variable must be set."
  }

  validation {
    condition = length(distinct(
      [for name, m in var.models : upper(replace(name, "/[^A-Za-z0-9_]/", "_"))]
    )) == length(var.models)
    error_message = "Two model names normalize to the same UPSTREAM_API_KEY_* env var; rename them so each stays distinct."
  }
}

variable "langfuse_host" {
  description = "Base URL of the Langfuse instance (e.g. https://langfuse.my-domain.com)"
  type        = string
}

variable "langfuse_public_key" {
  description = "Langfuse project public key (pk-lf-...)"
  type        = string
  sensitive   = true
}

variable "langfuse_secret_key" {
  description = "Langfuse project secret key (sk-lf-...)"
  type        = string
  sensitive   = true
}

variable "smtp_host" {
  description = "SMTP server host used by the smtp_email callback (e.g. smtp.my-domain.com)"
  type        = string
}

variable "smtp_port" {
  description = "SMTP server port. 465 uses implicit TLS (SMTP_SSL); other ports connect plain and upgrade via STARTTLS when smtp_tls is true."
  type        = number
  default     = 465
}

variable "smtp_username" {
  description = "SMTP authentication username"
  type        = string
  sensitive   = true
}

variable "smtp_password" {
  description = "SMTP authentication password"
  type        = string
  sensitive   = true
}

variable "smtp_sender_email" {
  description = "From address of LiteLLM notification emails"
  type        = string
}

variable "smtp_tls" {
  description = "Upgrade the connection via STARTTLS. Ignored on port 465, which is already TLS."
  type        = bool
  default     = true
}
