#!/usr/bin/env bash
# PostgreSQL backup — pg_dump (custom format, compressed) + retention prune.
# Run from cron/systemd-timer on the Linux host, e.g. hourly:
#   0 * * * * /app/scripts/backup.sh >> /var/log/aurelius-backup.log 2>&1
#
# Reads DB config from the same env the app uses (DATABASE_* / PGPASSWORD).
# ponytail: local filesystem + retention only. Pipe BACKUP_DIR to S3/object
# storage (aws s3 cp / restic) when you need off-host durability.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aurelius}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-aurelius_dev}"
DB_USER="${DATABASE_USER:-aurelius}"
export PGPASSWORD="${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/${DB_NAME}_${stamp}.dump"

echo "[backup] dumping $DB_NAME -> $out"
pg_dump --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
        --format=custom --compress=9 --file="$out" "$DB_NAME"

# verify the dump is readable before we trust it and prune old ones
pg_restore --list "$out" > /dev/null
echo "[backup] verified $out ($(du -h "$out" | cut -f1))"

echo "[backup] pruning backups older than ${RETENTION_DAYS}d"
find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" -mtime "+${RETENTION_DAYS}" -delete
echo "[backup] done"
