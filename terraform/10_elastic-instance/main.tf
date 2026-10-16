terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = ">= 3.0.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.0.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.9.0"
    }
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

provider "helm" {
  kubernetes = {
    config_path = "~/.kube/config"
  }
}

resource "kubernetes_namespace_v1" "elastic" {
  metadata {
    name = "elastic"
  }
}

resource "kubernetes_manifest" "elastic_servers_transport" {
  manifest = {
    apiVersion = "traefik.io/v1alpha1"
    kind       = "ServersTransport"

    metadata = {
      name      = "elastic-backend-tls"
      namespace = kubernetes_namespace_v1.elastic.metadata[0].name
    }

    spec = {
      insecureSkipVerify = true
    }
  }

  depends_on = [kubernetes_namespace_v1.elastic]
}

locals {
  traefik_servers_transport = "${kubernetes_namespace_v1.elastic.metadata[0].name}-elastic-backend-tls@kubernetescrd"

  elasticsearch_values = {
    enabled          = true
    fullnameOverride = "elasticsearch"

    http = {
      tls = {
        selfSignedCertificate = {
          disabled = false
        }
      }
      service = {
        metadata = {
          annotations = {
            "traefik.ingress.kubernetes.io/service.serversscheme"    = "https"
            "traefik.ingress.kubernetes.io/service.serverstransport" = local.traefik_servers_transport
          }
        }
      }
    }

    ingress = {
      enabled = false
    }
  }
}

resource "helm_release" "elastic" {
  name       = "elastic"
  repository = "https://helm.elastic.co"
  chart      = "eck-stack"
  version    = "0.20.0"
  namespace  = kubernetes_namespace_v1.elastic.metadata[0].name

  values = [var.kibana_enabled ? yamlencode({
    eck-elasticsearch = local.elasticsearch_values

    eck-kibana = {
      enabled          = true
      fullnameOverride = "kibana"

      config = {
        xpack = {
          fleet = {
            packages = [
              {
                name    = "apm"
                version = "latest"
              }
            ]
          }
        }
      }

      http = {
        tls = {
          selfSignedCertificate = {
            disabled = false
          }
        }
        service = {
          metadata = {
            annotations = {
              "traefik.ingress.kubernetes.io/service.serversscheme"    = "https"
              "traefik.ingress.kubernetes.io/service.serverstransport" = local.traefik_servers_transport
            }
          }
        }
      }

      ingress = {
        enabled = false
      }
    }

    eck-apm-server = {
      enabled          = true
      fullnameOverride = "apm-server"

      elasticsearchRef = {
        name = "elasticsearch"
      }

      kibanaRef = {
        name = "kibana"
      }

      http = {
        service = {
          metadata = {
            annotations = {
              "traefik.ingress.kubernetes.io/service.serversscheme"    = "https"
              "traefik.ingress.kubernetes.io/service.serverstransport" = local.traefik_servers_transport
            }
          }
        }
      }
    }
  }) : yamlencode({
    eck-elasticsearch = local.elasticsearch_values

    eck-kibana = {
      enabled = false
    }

    eck-apm-server = {
      enabled          = true
      fullnameOverride = "apm-server"

      elasticsearchRef = {
        name = "elasticsearch"
      }

      http = {
        service = {
          metadata = {
            annotations = {
              "traefik.ingress.kubernetes.io/service.serversscheme"    = "https"
              "traefik.ingress.kubernetes.io/service.serverstransport" = local.traefik_servers_transport
            }
          }
        }
      }
    }
  })]

  depends_on = [
    kubernetes_namespace_v1.elastic,
    kubernetes_manifest.elastic_servers_transport
  ]
}


resource "time_sleep" "wait_for_elastic" {
  create_duration = "15s"

  depends_on = [helm_release.elastic]
}

# Custom Traefik Ingress for Elasticsearch
resource "kubernetes_ingress_v1" "elasticsearch" {
  metadata {
    name      = "elasticsearch"
    namespace = kubernetes_namespace_v1.elastic.metadata[0].name

    annotations = {
      "cert-manager.io/cluster-issuer"                          = "letsencrypt-prod"
      "traefik.ingress.kubernetes.io/router.entrypoints"        = "websecure"
      "traefik.ingress.kubernetes.io/router.tls"                = "true"
    }
  }

  spec {
    ingress_class_name = "traefik"

    tls {
      hosts       = [var.elasticsearch_fqdn]
      secret_name = "elasticsearch-tls"
    }

    rule {
      host = var.elasticsearch_fqdn

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = "elasticsearch-es-http"
              port {
                number = 9200
              }
            }
          }
        }
      }
    }
  }

  depends_on = [time_sleep.wait_for_elastic, kubernetes_manifest.elastic_servers_transport]
}

# Custom Traefik Ingress for Kibana
resource "kubernetes_ingress_v1" "kibana" {
  count = var.kibana_enabled ? 1 : 0

  metadata {
    name      = "kibana"
    namespace = kubernetes_namespace_v1.elastic.metadata[0].name

    annotations = {
      "cert-manager.io/cluster-issuer"                          = "letsencrypt-prod"
      "traefik.ingress.kubernetes.io/router.entrypoints"        = "websecure"
      "traefik.ingress.kubernetes.io/router.tls"                = "true"
    }
  }

  spec {
    ingress_class_name = "traefik"

    tls {
      hosts       = [var.kibana_fqdn]
      secret_name = "kibana-tls"
    }

    rule {
      host = var.kibana_fqdn

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = "kibana-kb-http"
              port {
                number = 5601
              }
            }
          }
        }
      }
    }
  }

  depends_on = [time_sleep.wait_for_elastic, kubernetes_manifest.elastic_servers_transport]
}

# Custom Traefik Ingress for APM Server (OTLP endpoint for the remote OTel collector)
resource "kubernetes_ingress_v1" "apm" {
  metadata {
    name      = "apm"
    namespace = kubernetes_namespace_v1.elastic.metadata[0].name

    annotations = {
      "cert-manager.io/cluster-issuer"                   = "letsencrypt-prod"
      "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
      "traefik.ingress.kubernetes.io/router.tls"         = "true"
    }
  }

  spec {
    ingress_class_name = "traefik"

    tls {
      hosts       = [var.apm_fqdn]
      secret_name = "apm-tls"
    }

    rule {
      host = var.apm_fqdn

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = "apm-server-apm-http"
              port {
                number = 8200
              }
            }
          }
        }
      }
    }
  }

  depends_on = [time_sleep.wait_for_elastic, kubernetes_manifest.elastic_servers_transport]
}
