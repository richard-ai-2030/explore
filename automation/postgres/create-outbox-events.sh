#!/usr/bin/env bash
set -euo pipefail

PGHOST=${PGHOST:-localhost}
PGPORT=${PGPORT:-5432}
PGUSER=${PGUSER:-postgres}
PGPASSWORD=${PGPASSWORD:-postgres}

PRODUCER_DATABASES=(
  auth_service
  hot_lead_service
  campaign_service
  scoring_service
  quotation_service
  order_service
  payment_service
  supplier_service
  procurement_service
  inventory_service
  logistics_service
  quality_service
  invoice_service
  revenue_service
  cost_service
  recruitment_service
  employees_service
  attendance_service
  motivation_service
  payroll_service
)

export PGPASSWORD

echo "== Creating outbox_events in producer databases =="

for db in "${PRODUCER_DATABASES[@]}"; do
  echo "-> $db"
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" <<'SQL'
DROP TABLE IF EXISTS outbox_events;
CREATE TABLE IF NOT EXISTS outbox_events (
  id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  event_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload TEXT NOT NULL,
  headers TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status);
CREATE INDEX IF NOT EXISTS idx_outbox_created_at ON outbox_events(created_at);
SQL
done

echo "All tables created successfully"