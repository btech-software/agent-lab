variable "otlp_http_endpoint" {
  type        = string
  default     = "https://elastic-eck-apm-server-apm-http.elastic.svc:8200"
  description = "Endpoint for OTLP HTTP exporter"
}
