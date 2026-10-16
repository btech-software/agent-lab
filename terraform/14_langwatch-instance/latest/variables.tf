variable "langwatch_fqdn" {
  type        = string
  description = "FQDN for LangWatch access (e.g., langwatch.local or a public domain)"
}

variable "pg_image" {
  type        = string
  default     = "bsantanna/cloudnative-pg-vector:17.4"
  description = "PostgreSQL image with pgvector (adjust if needed)"
}
