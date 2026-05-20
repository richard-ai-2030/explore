#!/usr/bin/env bash
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
PGADMIN_DB="${PGADMIN_DB:-postgres}"
export PGPASSWORD

service_dbs=(
  analytics_service
  training_service
  auth_service
  campaign_service
  cost_service
  employees_service
  hot_lead_service
  inventory_service
  invoice_service
  leads_acquisition_service
  logistics_service
  motivation_service
  notification_service
  order_service
  payment_service
  payroll_service
  procurement_service
  quality_service
  quotation_service
  recruitment_service
  revenue_service
  scoring_service
  supplier_service
  tracking_service
)

for db in "${service_dbs[@]}"; do
  if ! psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGADMIN_DB" -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
    echo "Creating database: $db"
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGADMIN_DB" -c "CREATE DATABASE "${db}";"
  else
    echo "Database already exists: $db"
  fi
done
