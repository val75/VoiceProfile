#!/usr/bin/env bash
# Whisper uptime probe for VoiceProfile, run every 5 minutes on the app server
# by whisper-probe.timer.
#
# Sends a short silent clip to WHISPER_URL the way the app sends audio (the
# app's WHISPER_API_KEY, a "file" form field) and expects a transcript back. A
# real clip rather than an empty request, so a broken model, or a disk too full
# to take a 1 MB upload (as on 2026-10-25), counts as down. Reports to healthchecks.io
# (WHISPER_HEALTHCHECK_URL in the app's .env):
#   healthy     -> success ping
#   not healthy -> a "log" ping with the reason (Whisper's own error text when it
#                  gives one), which leaves the check's status alone.
#                  healthchecks.io emails once no success ping has arrived for
#                  Period + Grace, so a brief restart stays quiet.
# Exits non-zero when unhealthy either way, so the journal shows it too.
#
# See docs/deployment/production-deployment.md (Whisper uptime check).
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

WHISPER_URL="$(env_value WHISPER_URL)"
WHISPER_API_KEY="$(env_value WHISPER_API_KEY)"

# Kept in .env, not the unit: whoever has the URL can fake "OK" pings.
WHISPER_HEALTHCHECK_URL="${WHISPER_HEALTHCHECK_URL:-$(env_value WHISPER_HEALTHCHECK_URL)}"
WHISPER_HEALTHCHECK_URL="${WHISPER_HEALTHCHECK_URL%/}"

# ping SUFFIX [BODY]: "" = success, "/log" = record BODY without a status change.
ping() {
  [[ -n "$WHISPER_HEALTHCHECK_URL" ]] || return 0
  # A failed ping doesn't fail the probe: the missing ping alerts anyway.
  curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "${2:-}" "$WHISPER_HEALTHCHECK_URL$1" \
    || echo "[whisper-probe] WARNING: healthcheck ping failed" >&2
}

fail() {
  echo "[whisper-probe] FAIL: $1" >&2
  ping /log "$1"
  exit 1
}

[[ -n "$WHISPER_URL" ]] || fail "WHISPER_URL is not set in $APP_DIR/.env"
[[ -n "$WHISPER_API_KEY" ]] || fail "WHISPER_API_KEY is not set in $APP_DIR/.env"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# 6 s of 48 kHz stereo silence: about 1.1 MB, just over the 1 MiB that
# Starlette keeps in memory, so Whisper also writes it to /tmp while parsing
# the form, as it does big recordings. Whisper works in 30 s windows, so this
# costs no more GPU time than a 1 s clip.
python3 -I -c '
import sys, wave
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(48000)
    w.writeframes(b"\0\0\0\0" * 48000 * 6)
' "$work/probe.wav"

# The key goes in on stdin (-H @-), not as an argument, which `ps` would show.
# No -f: on an error we want Whisper's body, which says why. -m matches the
# app's timeout: Whisper transcribes one request at a time, so the probe can
# queue behind a worker's recording.
rc=0
code="$(printf 'X-API-Key: %s\n' "$WHISPER_API_KEY" \
         | curl -sS -m 90 -o "$work/body" -w '%{http_code}' -H @- \
                -F "file=@$work/probe.wav;type=audio/wav" "$WHISPER_URL" \
                2>"$work/err")" || rc=$?
if [[ "$rc" == 28 ]]; then
  # Connected (or tried to) but no answer in time: a hung model or GPU, not the network.
  fail "no response within 90 s from $WHISPER_URL: $(head -c 300 "$work/err")"
elif [[ "$rc" != 0 ]]; then
  fail "cannot reach Whisper at $WHISPER_URL: $(head -c 300 "$work/err")"
fi
if [[ "$code" != 200 ]]; then
  fail "HTTP $code from $WHISPER_URL: $(head -c 300 "$work/body" 2>/dev/null || true)"
fi
if ! python3 -I -c '
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(data, dict) and data.get("text") is not None else 1)
' "$work/body"; then
  fail "no transcript from $WHISPER_URL: $(head -c 300 "$work/body")"
fi

echo "[whisper-probe] OK: transcribed a test clip at $WHISPER_URL"
ping ""
