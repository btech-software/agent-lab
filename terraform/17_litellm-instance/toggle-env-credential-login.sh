#!/usr/bin/env bash
# Toggles general_settings.disable_env_credential_login in the LiteLLM proxy
# config (Admin UI "Deployment health" warning: Environment-credential login is
# enabled). true blocks UI sign-in with UI_USERNAME/UI_PASSWORD or the master
# key; API calls with the master key keep working.
#
# Before setting true, create a regular admin account with its own password,
# otherwise nobody can sign in to the Admin UI.
#
# Patches the Helm-rendered litellm-config ConfigMap in place, so a later
# `terraform apply` of this module reverts it.
#
# Usage: ./toggle-env-credential-login.sh true|false
set -euo pipefail

VALUE="${1:-}"
if [[ "$VALUE" != "true" && "$VALUE" != "false" ]]; then
  echo "Usage: $0 true|false" >&2
  exit 1
fi

KUBECTL=(kubectl --context "${KUBE_CONTEXT:-docker-desktop}" -n litellm)
KEY="disable_env_credential_login"

current="$("${KUBECTL[@]}" get configmap litellm-config -o jsonpath='{.data.config\.yaml}')"

# Drop any existing entry under general_settings, then insert the new one
# right after the general_settings: header (children are indented 2 spaces).
updated="$(printf '%s\n' "$current" | awk -v key="$KEY" -v val="$VALUE" '
  /^[^[:space:]]/ { in_gs = ($0 == "general_settings:") }
  in_gs && $0 ~ "^  " key ":" { next }
  { print }
  $0 == "general_settings:" { print "  " key ": " val }
')"

if ! grep -q '^general_settings:' <<<"$updated"; then
  updated="$(printf 'general_settings:\n  %s: %s\n%s' "$KEY" "$VALUE" "$current")"
fi

if [[ "$updated" == "$current" ]]; then
  echo "$KEY already $VALUE; nothing to do."
  exit 0
fi

patch="$(python3 -c 'import json,sys; print(json.dumps({"data": {"config.yaml": sys.stdin.read()}}))' <<<"$updated")"
"${KUBECTL[@]}" patch configmap litellm-config --type merge -p "$patch"

# The proxy reads config.yaml only at startup.
"${KUBECTL[@]}" rollout restart deployment/litellm
"${KUBECTL[@]}" rollout status deployment/litellm --timeout=300s

echo "general_settings.$KEY set to $VALUE."
