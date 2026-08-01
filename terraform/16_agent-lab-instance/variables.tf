variable "agent_lab_namespace" {
  description = "Kubernetes namespace for app deployment"
  type        = string
  default     = "agent-lab"
}

variable "agent_lab_chart_version" {
  description = "Helm chart version for agent-lab"
  type        = string
  default     = "1.16.1"
}

variable "agent_lab_fqdn" {
  description = "Fully qualified domain name for agent-lab ingress"
  type        = string
}

variable "telemetry_endpoint" {
  description = "OpenTelemetry collector endpoint URL"
  type        = string
  default     = "http://otel-collector-opentelemetry-collector.otel.svc.cluster.local:4318"
}

variable "embeddings_endpoint" {
  description = "OpenAI-compatible embeddings server endpoint URL"
  type        = string
  default     = ""
}
