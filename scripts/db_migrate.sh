#!/usr/bin/env bash
set -euo pipefail

DB_ENV="${1:-dev}"

DB_USER="atlas"
DB_PASSWORD="atlas"
DB_HOST="127.0.0.1"
DB_PORT="5432"

case "$DB_ENV" in
  dev)
    DB_NAME="atlas_test"
    ;;
  prod)
    DB_NAME="atlas"
    ;;
  *)
    echo "Usage: $0 [dev|prod]"
    exit 1
    ;;
esac

export PGPASSWORD="$DB_PASSWORD"

echo
echo "ATLAS DB MIGRATIONS"
echo "Environment : $DB_ENV"
echo "Database    : $DB_NAME"
echo "User        : $DB_USER"
echo "Host        : $DB_HOST"
echo "Port        : $DB_PORT"
echo

for f in $(ls migrations/*.sql | sort); do
    echo "Applying migration: $f"
    psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -v ON_ERROR_STOP=1 \
        -f "$f"
done

echo
echo "All migrations applied successfully."
echo
