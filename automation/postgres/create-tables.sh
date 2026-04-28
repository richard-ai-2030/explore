#!/usr/bin/env bash
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
export PGPASSWORD

SCHEMA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/schemas" && pwd)"

for schema_file in "$SCHEMA_DIR"/*.sql; do
  db_name="$(basename "$schema_file" .sql)"
  echo "Applying schema to: $db_name"
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db_name" -f "$schema_file"
done
