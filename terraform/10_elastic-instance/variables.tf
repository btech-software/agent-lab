variable "elasticsearch_fqdn" {
  type        = string
  description = "FQDN for Elasticsearch access (e.g., elasticsearch.local or a public domain)"
}

variable "kibana_fqdn" {
  type        = string
  description = "FQDN for Kibana access (e.g., kibana.local or a public domain)"
}

variable "apm_fqdn" {
  type        = string
  description = "FQDN for APM Server access (OTLP endpoint used by the OTel collector in the remote cluster)"
}

variable "kibana_enabled" {
  type        = bool
  default     = true
  description = "Whether to deploy Kibana and its ingress"
}
