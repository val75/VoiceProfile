#!/usr/bin/env bash
# Deploy one VoiceProfile image, by git SHA, on this host.
#
#   /srv/voiceprofile/deploy.sh <full-40-char-git-sha>
#
# 1. Downloads deploy/compose/compose.yml at that SHA (the repo is public).
# 2. Pulls ghcr.io/val75/voiceprofile:<sha> (built by GitHub Actions).
# 3. Only after both succeed: records the SHA in .env, runs migrations,
#    starts the new container and waits for it to be healthy.
#
# Rollback: run it again with the previous SHA (printed at the end).
# Migrations are not reversed by a rollback: an older image runs against the
# newer schema, which is fine for additive migrations. Check before rolling
# back across a migration that drops or renames something.
set -euo pipefail

VP_DIR="${VP_DIR:-/srv/voiceprofile}"
REPO_RAW="https://raw.githubusercontent.com/val75/VoiceProfile"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5001/healthz}"

sha="${1:-}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <full 40-char git sha>" >&2
  exit 2
fi

cd "$VP_DIR"
if [[ ! -f app.env ]]; then
  echo "missing $VP_DIR/app.env (create it from the host's .env, mode 600)" >&2
  exit 1
fi

prev="$(sed -n 's/^VP_TAG=//p' .env 2>/dev/null || true)"

echo "[deploy] fetching compose.yml at ${sha:0:12}"
curl -fsSL "$REPO_RAW/$sha/deploy/compose/compose.yml" -o compose.yml.new

echo "[deploy] pulling image ${sha:0:12}"
VP_TAG="$sha" docker compose -f compose.yml.new pull app

# Both downloads worked: switch to the new SHA.
mv compose.yml.new compose.yml
printf 'VP_TAG=%s\n' "$sha" > .env.new && mv .env.new .env

echo "[deploy] migrating"
docker compose run --rm app flask db upgrade

echo "[deploy] starting"
docker compose up -d --wait --wait-timeout 120 app

curl -fsS -m 5 "$HEALTH_URL"
echo
echo "[deploy] OK: ${sha} is live (previous: ${prev:-none})"
if [[ -n "$prev" && "$prev" != "$sha" ]]; then
  echo "[deploy] rollback: $0 $prev"
fi
