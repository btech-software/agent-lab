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
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0.0"
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

resource "kubernetes_namespace_v1" "litellm" {
  metadata {
    name = "litellm"
  }
}

# Operator-managed Redis (OT container-kit), mirroring the langfuse module.
# Deployed passwordless for LiteLLM coordination (cross-pod rate limits, spend
# tracking, pod lock manager). The chart names the Service `redis` regardless
# of release name, so the coordination endpoint is redis.<ns>.svc.cluster.local.
resource "helm_release" "redis_litellm" {
  name       = "redis-litellm"
  repository = "https://ot-container-kit.github.io/helm-charts/"
  chart      = "redis"
  namespace  = kubernetes_namespace_v1.litellm.metadata[0].name

  set = [{
    name  = "featureGates.GenerateConfigInInitContainer"
    value = "true"
  }]

  depends_on = [kubernetes_namespace_v1.litellm]
}

# Operator-managed PostgreSQL (CloudNativePG), mirroring the langfuse module.
# The operator provisions a `<name>-cluster-app` secret (keys `username`,
# `password`, ...) which the LiteLLM chart consumes via db.secret.
resource "helm_release" "pg_litellm" {
  name       = "pg-litellm"
  repository = "https://cloudnative-pg.github.io/charts"
  chart      = "cluster"
  namespace  = kubernetes_namespace_v1.litellm.metadata[0].name

  values = [
    yamlencode({
      cluster = {
        instances = 1
        imageName = var.pg_image
        storage = {
          size = "5Gi"
        }
      }
    })
  ]

  depends_on = [kubernetes_namespace_v1.litellm]
}

resource "time_sleep" "wait_for_pg_secret" {
  create_duration = "15s"

  depends_on = [helm_release.pg_litellm]
}

# LiteLLM application secrets. The master key is the proxy's admin credential
# (API + UI login); the salt key encrypts provider credentials stored in the
# database and must never be rotated once models are persisted there.
# special = false keeps them safe to embed without URL-encoding.
resource "random_password" "master_key" {
  length  = 32
  special = false
}

resource "random_password" "salt" {
  length  = 32
  special = false
}

# envFrom target for the proxy pods: the salt key, the Langfuse credentials
# read by the langfuse_otel callback, the SMTP settings read by the smtp_email
# callback, PROXY_BASE_URL (public host used in email links such as
# invitations; defaults to http://0.0.0.0:4000), FORWARDED_ALLOW_IPS (lets
# uvicorn honour Traefik's X-Forwarded-Proto so redirects keep https; it
# defaults to 127.0.0.1 only), plus one env var per model
# that declared an upstream api_key. proxy_config references the latter with
# os.environ/<NAME> so keys never land in the rendered ConfigMap.
resource "kubernetes_secret_v1" "litellm_env" {
  metadata {
    name      = "litellm-env"
    namespace = kubernetes_namespace_v1.litellm.metadata[0].name
  }

  data = merge(
    {
      LITELLM_SALT_KEY    = random_password.salt.result
      LANGFUSE_HOST       = var.langfuse_host
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      PROXY_BASE_URL      = "https://${var.litellm_fqdn}"
      FORWARDED_ALLOW_IPS = var.trusted_proxy_cidr
      SMTP_HOST           = var.smtp_host
      SMTP_PORT           = tostring(var.smtp_port)
      SMTP_USERNAME       = var.smtp_username
      SMTP_PASSWORD       = var.smtp_password
      SMTP_SENDER_EMAIL   = var.smtp_sender_email
      SMTP_TLS            = var.smtp_tls ? "True" : "False"
    },
    {
      for name, m in var.models : "UPSTREAM_API_KEY_${upper(replace(name, "/[^A-Za-z0-9_]/", "_"))}" => m.api_key
      if m.api_key != ""
    }
  )
}

# LiteLLM proxy (open-source, monolithic mode) from the official chart.
# The chart's migration Job is disabled: with DATABASE_URL set the proxy applies
# the prisma schema itself at startup (single replica, so no race). Under
# Terraform the Job would run concurrently with the Deployment, not before it.
# Chart >= 1.x also drops 0.1.100's hardcoded db-ready init container, which
# pulled docker.io/bitnami/postgresql (tag since removed from that repo).
resource "helm_release" "litellm" {
  name       = "litellm"
  repository = "oci://ghcr.io/berriai"
  chart      = "litellm-helm"
  version    = var.litellm_chart_version
  namespace  = kubernetes_namespace_v1.litellm.metadata[0].name

  values = [
    yamlencode({
      replicaCount = 1

      # envFrom is only read at pod start: hashing the secret into the pod
      # template rolls the pods whenever litellm-env changes.
      podAnnotations = {
        "checksum/litellm-env" = sha256(jsonencode(kubernetes_secret_v1.litellm_env.data))
      }

      image = {
        repository = "ghcr.io/berriai/litellm"
        # Pinned explicitly rather than inherited from the chart appVersion,
        # keeping rollbacks deterministic (docs: never run :latest or a moving tag).
        tag        = var.litellm_image_tag
        pullPolicy = "IfNotPresent"
      }

      # The chart creates the <fullname>-masterkey secret and wires
      # PROXY_MASTER_KEY to it; the key is supplied via the masterkey value so
      # it stays deterministic and owned by Terraform state.
      masterkey = random_password.master_key.result

      migrationJob = {
        enabled = false
      }

      environmentSecrets = [kubernetes_secret_v1.litellm_env.metadata[0].name]

      # Ingress is provisioned below, mirroring the langfuse module.
      ingress = {
        enabled = false
      }

      # External Postgres provisioned by CloudNativePG. Username/database are
      # the operator's defaults (`app`); both are read from the operator
      # secret. db.url is left at the chart default, which composes
      # postgresql://$(DATABASE_USERNAME):$(DATABASE_PASSWORD)@$(DATABASE_HOST)/$(DATABASE_NAME)
      # from the env vars the chart injects from these fields.
      db = {
        useExisting      = true
        deployStandalone = false
        endpoint         = "${helm_release.pg_litellm.name}-cluster-rw.${kubernetes_namespace_v1.litellm.metadata[0].name}.svc.cluster.local"
        database         = "app"
        secret = {
          name        = "${helm_release.pg_litellm.name}-cluster-app"
          usernameKey = "username"
          passwordKey = "password"
        }
      }

      # External Redis provisioned by the OT operator (chart's bundled Redis
      # subchart stays off). Coordination is wired through proxy_config below,
      # replicating exactly the block the chart renders for its bundled Redis.
      redis = {
        enabled = false
      }

      proxy_config = {
        model_list = [
          for name, m in var.models : {
            model_name = name
            litellm_params = merge(
              {
                model    = "openai/${m.model}"
                api_base = m.api_base != "" && m.api_base != null ? m.api_base : var.upstream_api_base
              },
              m.api_key != "" ? { api_key = "os.environ/UPSTREAM_API_KEY_${upper(replace(name, "/[^A-Za-z0-9_]/", "_"))}" } : {}
            )
          }
        ]

        # langfuse_otel exports via LiteLLM's OTLP pipeline to
        # <LANGFUSE_HOST>/api/public/otel (Langfuse >= v3). The plain `langfuse`
        # callback is avoided: it needs the v4 SDK, the image bundles v2.
        # smtp_email sends proxy notifications (key created, budget alerts)
        # through the SMTP_* settings in the litellm-env secret.
        litellm_settings = {
          callbacks = ["langfuse_otel", "smtp_email"]
        }

        general_settings = {
          master_key = "os.environ/PROXY_MASTER_KEY"

          coordination_redis = {
            host = "redis.${kubernetes_namespace_v1.litellm.metadata[0].name}.svc.cluster.local"
            port = 6379
          }
        }
      }

      # Modest LAN sizing. The chart warns a DB-connected proxy needs about
      # 1 CPU / 4Gi per worker at production steady state; the prisma engine's
      # memory ratchets upward, so widen the limit before raising workers.
      resources = {
        requests = { cpu = "500m", memory = "1Gi" }
        limits   = { cpu = "1", memory = "2Gi" }
      }
    })
  ]

  timeout = 600

  depends_on = [
    time_sleep.wait_for_pg_secret,
    helm_release.redis_litellm
  ]
}

resource "kubernetes_ingress_v1" "litellm" {
  metadata {
    name      = "litellm"
    namespace = kubernetes_namespace_v1.litellm.metadata[0].name

    annotations = {
      "cert-manager.io/cluster-issuer"                   = "letsencrypt-prod"
      "traefik.ingress.kubernetes.io/router.entrypoints" = "websecure"
      "traefik.ingress.kubernetes.io/router.tls"         = "true"
    }
  }

  spec {
    ingress_class_name = "traefik"

    tls {
      hosts       = [var.litellm_fqdn]
      secret_name = "litellm-tls"
    }

    rule {
      host = var.litellm_fqdn

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = "litellm"
              port {
                number = 4000
              }
            }
          }
        }
      }
    }
  }

  depends_on = [helm_release.litellm]
}
