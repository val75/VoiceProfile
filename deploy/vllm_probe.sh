#!/usr/bin/env bash
# vLLM uptime probe for VoiceProfile, run every 5 minutes on the app server by
# vllm-probe.timer.
#
# Asks the LLM the app uses (LLM_URL, with the app's LLM_API_KEY) for its model
# list and checks that LLM_MODEL is in it: the same network path, key and model
# that profile extraction needs. Reports to healthchecks.io (VLLM_HEALTHCHECK_URL
# in the app's .env):
#   healthy     -> success ping
#   not healthy -> a "log" ping with the reason, which leaves the check's status
#                  alone. healthchecks.io emails once no success ping has arrived
#                  for Period + Grace, so a planned vLLM restart (a few minutes'
#                  model load) stays quiet but a real outage doesn't.
# Exits non-zero when unhealthy either way, so the journal shows it too.
#
# See docs/deployment/production-deployment.md (vLLM uptime check).
set -euo pipefail

APP_DIR="${APP_DIR:-/home/cato-user/VoiceProfile}"

# Prints KEY's value from the app's .env, unquoted; empty if absent.
env_value() {
  [[ -f "$APP_DIR/.env" ]] || return 0
  local v
  v="$(grep -E "^$1=" "$APP_DIR/.env" | head -1 | cut -d= -f2- || true)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

# Same defaults as config.py, so this probes exactly what the app would call.
LLM_URL="$(env_value LLM_URL)"
LLM_URL="${LLM_URL:-http://localhost:11434/v1}"
LLM_URL="${LLM_URL%/}"
LLM_MODEL="$(env_value LLM_MODEL)"
LLM_MODEL="${LLM_MODEL:-mistral:7b-instruct}"
LLM_API_KEY="$(env_value LLM_API_KEY)"
LLM_API_KEY="${LLM_API_KEY:-ollama}"

# Kept in .env, not the unit: whoever has the URL can fake "OK" pings.
VLLM_HEALTHCHECK_URL="${VLLM_HEALTHCHECK_URL:-$(env_value VLLM_HEALTHCHECK_URL)}"
VLLM_HEALTHCHECK_URL="${VLLM_HEALTHCHECK_URL%/}"

# ping SUFFIX [BODY]: "" = success, "/log" = record BODY without a status change.
ping() {
  [[ -n "$VLLM_HEALTHCHECK_URL" ]] || return 0
  # A failed ping doesn't fail the probe: the missing ping alerts anyway.
  curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "${2:-}" "$VLLM_HEALTHCHECK_URL$1" \
    || echo "[vllm-probe] WARNING: healthcheck ping failed" >&2
}

reason=""
# The key goes in on stdin (-H @-), not as an argument, which `ps` would show.
if ! body="$(printf 'Authorization: Bearer %s\n' "$LLM_API_KEY" \
              | curl -fsS -m 20 -H @- "$LLM_URL/models" 2>&1)"; then
  reason="cannot list models at $LLM_URL: $body"
elif ! python3 -I -c '
import json, sys
try:
    ids = [m["id"] for m in json.load(sys.stdin)["data"]]
except Exception:
    sys.exit(1)
sys.exit(0 if sys.argv[1] in ids else 1)
' "$LLM_MODEL" <<<"$body"; then
  reason="$LLM_MODEL not in the model list from $LLM_URL: $(head -c 300 <<<"$body")"
fi

if [[ -n "$reason" ]]; then
  echo "[vllm-probe] FAIL: $reason" >&2
  ping /log "$reason"
  exit 1
fi

echo "[vllm-probe] OK: $LLM_MODEL at $LLM_URL"
ping ""
