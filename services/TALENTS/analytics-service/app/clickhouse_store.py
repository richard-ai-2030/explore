import json
import os
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect

CLICKHOUSE_ENABLED = os.getenv('CLICKHOUSE_ENABLED', 'true').lower() == 'true'
CLICKHOUSE_HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
CLICKHOUSE_PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
CLICKHOUSE_USER = os.getenv('CLICKHOUSE_USER', 'default')
CLICKHOUSE_PASSWORD = os.getenv('CLICKHOUSE_PASSWORD', '')
CLICKHOUSE_DATABASE = os.getenv('CLICKHOUSE_DATABASE', 'explore')
CLICKHOUSE_EVENTS_TABLE = os.getenv('CLICKHOUSE_EVENTS_TABLE', 'events')

_client: clickhouse_connect.driver.Client | None = None


def enabled() -> bool:
    return CLICKHOUSE_ENABLED


def _parse_occurred_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        normalized = value.replace('Z', '+00:00')
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def get_client() -> clickhouse_connect.driver.Client | None:
    global _client
    if not CLICKHOUSE_ENABLED:
        return None
    if _client is not None:
        return _client
    try:
        _client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD or '',
            database=CLICKHOUSE_DATABASE,
        )
        _client.ping()
        return _client
    except Exception:
        _client = None
        return None


def init_schema() -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.command(f'CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE}')
        client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DATABASE}.{CLICKHOUSE_EVENTS_TABLE} (
              event_id String,
              event_type LowCardinality(String),
              domain LowCardinality(String),
              producer LowCardinality(String),
              aggregate_id String,
              correlation_id String,
              actor String,
              payload String,
              occurred_at DateTime64(3, 'UTC'),
              ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(occurred_at)
            ORDER BY (domain, event_type, occurred_at)
            """
        )
        return True
    except Exception:
        return False


def ping() -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def insert_kafka_event(message: dict[str, Any]) -> bool:
    client = get_client()
    if not client:
        return False
    event_type = message.get('eventType', 'unknown')
    domain = event_type.split('.', 1)[0] if '.' in event_type else 'general'
    payload = message.get('payload', message)
    try:
        client.insert(
            CLICKHOUSE_EVENTS_TABLE,
            [[
                str(message.get('eventId', '')),
                event_type,
                domain,
                str(message.get('producer', '')),
                str(message.get('aggregateId', '')),
                str(message.get('correlationId', '')),
                str(message.get('actor') or ''),
                json.dumps(payload, default=str),
                _parse_occurred_at(message.get('occurredAt')),
            ]],
            column_names=[
                'event_id',
                'event_type',
                'domain',
                'producer',
                'aggregate_id',
                'correlation_id',
                'actor',
                'payload',
                'occurred_at',
            ],
        )
        return True
    except Exception:
        return False


def insert_http_event(
    event_id: str,
    domain: str,
    source: str,
    event: str,
    payload: dict[str, Any],
    created_at: str,
) -> bool:
    return insert_kafka_event({
        'eventId': event_id,
        'eventType': event,
        'producer': source,
        'aggregateId': payload.get('id', event_id),
        'correlationId': payload.get('correlationId', ''),
        'actor': payload.get('actor', ''),
        'payload': payload,
        'occurredAt': created_at,
    })


def query_recent_events(domain: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    client = get_client()
    if not client:
        return []
    where = "WHERE occurred_at >= now() - INTERVAL 7 DAY"
    params: dict[str, Any] = {'limit': limit}
    if domain:
        where += ' AND domain = %(domain)s'
        params['domain'] = domain
    try:
        result = client.query(
            f"""
            SELECT
              event_id,
              event_type,
              domain,
              producer,
              aggregate_id,
              correlation_id,
              actor,
              payload,
              occurred_at
            FROM {CLICKHOUSE_EVENTS_TABLE}
            {where}
            ORDER BY occurred_at DESC
            LIMIT %(limit)s
            """,
            parameters=params,
        )
        rows = []
        for row in result.named_results():
            rows.append({
                'id': row['event_id'],
                'event': row['event_type'],
                'eventType': row['event_type'],
                'domain': row['domain'],
                'source': row['producer'],
                'producer': row['producer'],
                'aggregateId': row['aggregate_id'],
                'correlationId': row['correlation_id'],
                'actor': row['actor'],
                'payload': json.loads(row['payload']) if row['payload'] else {},
                'created_at': row['occurred_at'].isoformat() if hasattr(row['occurred_at'], 'isoformat') else str(row['occurred_at']),
                'occurredAt': row['occurred_at'].isoformat() if hasattr(row['occurred_at'], 'isoformat') else str(row['occurred_at']),
            })
        return rows
    except Exception:
        return []


def close() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
