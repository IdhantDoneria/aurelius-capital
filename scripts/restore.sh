#!/usr/bin/env bash
# Restore a PostgreSQL backup produced by backup.sh.
#   ./scripts/restore.sh /var/backups/mentisrex/mentisrex_dev_20260727T120000Z.dump
# DESTRUCTIVE: --clean drops existing objects before recreating them. Restore
# into a scratch DB first if you are unsure.
set -euo pipefail

DUMP="${1:?usage: restore.sh <path-to.dump>}"
DB_HOST="${DATABASE_HOST:-localhost}"
DB_PORT="${DATABASE_PORT:-5432}"
DB_NAME="${DATABASE_NAME:-mentisrex_dev}"
DB_USER="${DATABASE_USER:-mentisrex}"
export PGPASSWORD="${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"

echo "[restore] restoring $DUMP into $DB_NAME (existing objects will be dropped)"
pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
           --dbname="$DB_NAME" --clean --if-exists --no-owner "$DUMP"
echo "[restore] done"
