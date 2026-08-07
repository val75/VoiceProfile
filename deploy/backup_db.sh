#!/usr/bin/env bash
# Nightly PostgreSQL backup for VoiceProfile.
#
# Dumps the database (custom compressed format — includes the photo blobs),
# prunes old local dumps, and copies the new dump off-box to the DGX over the
# private network. Invoked by voiceprofile-backup.timer.
#
# Reads DATABASE_URL from the app's .env. Runs as a user that can read .env and
# has SSH key access to the DGX. Requires postgresql-client (pg_dump) on the box.
#
# See docs/deployment/production-deployment.md (Section 5) for setup + restore.
set -euo pipefail

# --- Config (override via the systemd unit's Environment=) ------------------
APP_DIR="${APP_DIR:-/home/cato-user/VoiceProfile}"
BACKUP_DIR="${BACKUP_DIR:-/home/cato-user/backups/voiceprofile}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# Off-box copy to the DGX (private network). Leave DGX_HOST empty to skip it
# (local-only backup — not protected against disk failure).
DGX_HOST="${DGX_HOST:-}"
DGX_USER="${DGX_USER:-cato-user}"
DGX_DIR="${DGX_DIR:-/data/backups/voiceprofile}"
SSH_KEY="${SSH_KEY:-/home/cato-user/.ssh/voiceprofile_backup}"

# --- Read DATABASE_URL from .env -------------------------------------------
if [[ -f "$APP_DIR/.env" ]]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' "$APP_DIR/.env" | head -1 | cut -d= -f2-)"
  DATABASE_URL="${DATABASE_URL%\"}"; DATABASE_URL="${DATABASE_URL#\"}"
  DATABASE_URL="${DATABASE_URL%\'}"; DATABASE_URL="${DATABASE_URL#\'}"
fi
: "${DATABASE_URL:?DATABASE_URL not found in $APP_DIR/.env}"

# pg_dump doesn't understand SQLAlchemy's +driver suffix; strip it.
PG_URL="${DATABASE_URL/+psycopg2:/:}"

# --- Dump ------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/voiceprofile_${STAMP}.dump"

echo "[backup] dumping -> $OUT"
pg_dump --format=custom --no-owner --no-privileges --file="$OUT" "$PG_URL"
echo "[backup] dump complete ($(du -h "$OUT" | cut -f1))"

# --- Prune old local dumps -------------------------------------------------
find "$BACKUP_DIR" -name 'voiceprofile_*.dump' -mtime +"$RETENTION_DAYS" -delete
echo "[backup] pruned local dumps older than ${RETENTION_DAYS}d"

# --- Off-box copy to the DGX -----------------------------------------------
if [[ -n "$DGX_HOST" ]]; then
  SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes)
  echo "[backup] copying -> ${DGX_USER}@${DGX_HOST}:${DGX_DIR}"
  ssh "${SSH_OPTS[@]}" "${DGX_USER}@${DGX_HOST}" "mkdir -p '$DGX_DIR'"
  rsync -a -e "ssh ${SSH_OPTS[*]}" "$OUT" "${DGX_USER}@${DGX_HOST}:${DGX_DIR}/"
  ssh "${SSH_OPTS[@]}" "${DGX_USER}@${DGX_HOST}" \
    "find '$DGX_DIR' -name 'voiceprofile_*.dump' -mtime +${RETENTION_DAYS} -delete"
  echo "[backup] off-box copy done"
else
  echo "[backup] DGX_HOST empty — LOCAL ONLY (not disk-failure safe)"
fi

echo "[backup] OK"
