variable "litellm_fqdn" {
  type        = string
  description = "FQDN for LiteLLM access (e.g., litellm.my-domain.com)"
}

variable "pg_image" {
  type        = string
  default     = "bsantanna/cloudnative-pg-vector:17.4"
  description = "PostgreSQL image for the CloudNativePG cluster (adjust if needed)"
}

variable "litellm_chart_version" {
  type        = string
  default     = "1.103.2"
  description = "litellm-helm chart version (OCI: ghcr.io/berriai/litellm-helm)"
}

variable "litellm_image_tag" {
  type        = string
  default     = "v1.103.2"
  description = "LiteLLM proxy image tag (pinned; chart appVersion is 'latest' and must not be relied on)"
}

variable "upstream_api_base" {
  type        = string
  default     = ""
  description = "Default OpenAI-compatible base URL of the upstream (e.g. http://<lan-host>:<port>/v1). Per-model api_base overrides this."
}

variable "models" {
  description = "OpenAI-compatible models exposed by the gateway. Map key is the model_name clients request; the value maps it to the upstream. api_key is optional and lands in the litellm-env secret, referenced from proxy_config via os.environ/."
  sensitive   = true
  type = map(object({
    model    = string
    api_base = optional(string)
    api_key  = optional(string, "")
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
