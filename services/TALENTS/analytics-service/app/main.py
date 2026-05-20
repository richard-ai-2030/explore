import json
import os
import psycopg
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from elasticsearch import Elasticsearch
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from psycopg.rows import dict_row

from .clickhouse_store import close as close_clickhouse, init_schema as init_clickhouse, insert_http_event, insert_kafka_event, ping as clickhouse_ping, query_recent_events
from .clickhouse_store import enabled as clickhouse_enabled
from .eventing import KafkaEventConsumer
from .redis_cache import cache_key, close as close_redis, delete_prefix, enabled as redis_enabled, get_json, ping as redis_ping, set_json

SERVICE_NAME = "analytics-service"
PORT = int(os.getenv('PORT', '7002'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))
ELASTICSEARCH_URL = os.getenv('ELASTICSEARCH_URL', 'http://localhost:9200')
ELASTICSEARCH_USERNAME = os.getenv('ELASTICSEARCH_USERNAME', '')
ELASTICSEARCH_PASSWORD = os.getenv('ELASTICSEARCH_PASSWORD', '')
ELASTICSEARCH_EVENTS_INDEX = os.getenv('ELASTICSEARCH_EVENTS_INDEX', 'explore-events-v3')
ELASTICSEARCH_PROJECTION_INDEX = os.getenv('ELASTICSEARCH_PROJECTION_INDEX', 'explore-projections-v3')

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])


class EventIn(BaseModel):
    domain: str = 'marketing'
    source: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        row_factory=dict_row,
    )


def get_es() -> Elasticsearch | None:
    auth = None
    if ELASTICSEARCH_USERNAME and ELASTICSEARCH_PASSWORD:
        auth = (ELASTICSEARCH_USERNAME, ELASTICSEARCH_PASSWORD)
    try:
        client = Elasticsearch(ELASTICSEARCH_URL, basic_auth=auth, request_timeout=3)
        if client.ping():
            return client
    except Exception:
        return None
    return None


@app.middleware('http')
async def metrics_middleware(request: Request, call_next):
    with LATENCY.labels(SERVICE_NAME, request.method, request.url.path).time():
        response = await call_next(request)
    REQUESTS.labels(SERVICE_NAME, request.method, request.url.path, str(response.status_code)).inc()
    response.headers['X-Service-Name'] = SERVICE_NAME
    return response


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              domain TEXT NOT NULL,
              source TEXT NOT NULL,
              event TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_projections (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              state TEXT NOT NULL,
              score INTEGER NOT NULL DEFAULT 0,
              hot_state TEXT,
              source TEXT,
              channel TEXT,
              email TEXT,
              company TEXT,
              touch_count INTEGER NOT NULL DEFAULT 0,
              data TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_projections (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              state TEXT NOT NULL,
              budget REAL NOT NULL DEFAULT 0,
              planned_recipients INTEGER NOT NULL DEFAULT 0,
              sent_count INTEGER NOT NULL DEFAULT 0,
              open_count INTEGER NOT NULL DEFAULT 0,
              click_count INTEGER NOT NULL DEFAULT 0,
              unsubscribe_count INTEGER NOT NULL DEFAULT 0,
              data TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS production_projections (
              id TEXT PRIMARY KEY,
              resource TEXT NOT NULL,
              name TEXT NOT NULL,
              state TEXT NOT NULL,
              amount REAL NOT NULL DEFAULT 0,
              score INTEGER NOT NULL DEFAULT 0,
              domain TEXT NOT NULL DEFAULT 'production',
              data TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS talent_projections (
              id TEXT PRIMARY KEY,
              resource TEXT NOT NULL,
              name TEXT NOT NULL,
              state TEXT NOT NULL,
              amount REAL NOT NULL DEFAULT 0,
              score INTEGER NOT NULL DEFAULT 0,
              domain TEXT NOT NULL DEFAULT 'talents',
              data TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def init_search() -> None:
    es = get_es()
    if not es:
        return
    mappings = {
        'properties': {
            'id': {'type': 'keyword'},
            'domain': {'type': 'keyword'},
            'resource': {'type': 'keyword'},
            'state': {'type': 'keyword'},
            'source': {'type': 'keyword'},
            'event': {'type': 'keyword'},
            'name': {'type': 'text'},
            'updatedAt': {'type': 'date'},
            'createdAt': {'type': 'date'},
            'amount': {'type': 'float'},
            'score': {'type': 'integer'},
            'payload': {'type': 'flattened'},
            'data': {'type': 'flattened'},
        }
    }
    for index_name in [ELASTICSEARCH_EVENTS_INDEX, ELASTICSEARCH_PROJECTION_INDEX]:
        try:
            if not es.indices.exists(index=index_name):
                es.indices.create(index=index_name, mappings=mappings)
        except Exception:
            pass


def infer_domain(event_type: str) -> str:
    return event_type.split('.', 1)[0] if '.' in event_type else 'general'


def search_index(doc_id: str, body: dict[str, Any], suffix: str) -> None:
    es = get_es()
    if not es:
        return
    index_name = ELASTICSEARCH_EVENTS_INDEX if suffix == 'event' else ELASTICSEARCH_PROJECTION_INDEX
    try:
        es.index(index=index_name, id=doc_id, document=body, refresh=False)
    except Exception:
        pass


def store_event(source: str, event: str, payload: dict[str, Any], event_id: str | None = None, created_at: str | None = None) -> str:
    event_id = event_id or str(uuid.uuid4())
    created_at = created_at or now_iso()
    domain = infer_domain(event)
    with db() as conn:
        conn.execute(
            'INSERT INTO events (id, domain, source, event, payload, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING',
            (event_id, domain, source, event, json.dumps(payload), created_at),
        )
        conn.commit()
    search_index(event_id, {
        'id': event_id,
        'domain': domain,
        'source': source,
        'event': event,
        'payload': payload,
        'createdAt': created_at,
    }, 'event')
    return event_id


def _merge_json(existing: Any, patch: dict[str, Any]) -> dict[str, Any]:
    current = json.loads(existing) if isinstance(existing, str) else (existing or {})
    current.update(patch or {})
    return current


def upsert_lead(conn, lead_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute('SELECT * FROM lead_projections WHERE id = %s', (lead_id,)).fetchone()
    current = dict(row) if row else None
    record = {
        'id': lead_id,
        'name': defaults.get('name') or (current['name'] if current else 'lead'),
        'state': defaults.get('state') or (current['state'] if current else 'captured'),
        'score': int(defaults.get('score', current['score'] if current else 0)),
        'hot_state': defaults.get('hot_state') or (current['hot_state'] if current else None),
        'source': defaults.get('source') or (current['source'] if current else None),
        'channel': defaults.get('channel') or (current['channel'] if current else None),
        'email': defaults.get('email') or (current['email'] if current else None),
        'company': defaults.get('company') or (current['company'] if current else None),
        'touch_count': int(defaults.get('touch_count', current['touch_count'] if current else 0)),
        'data': _merge_json(current['data'] if current else {}, defaults.get('data', {})),
        'updated_at': defaults.get('updated_at', now_iso()),
    }
    conn.execute(
        """
        INSERT INTO lead_projections (id, name, state, score, hot_state, source, channel, email, company, touch_count, data, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
          name = EXCLUDED.name,
          state = EXCLUDED.state,
          score = EXCLUDED.score,
          hot_state = EXCLUDED.hot_state,
          source = EXCLUDED.source,
          channel = EXCLUDED.channel,
          email = EXCLUDED.email,
          company = EXCLUDED.company,
          touch_count = EXCLUDED.touch_count,
          data = EXCLUDED.data,
          updated_at = EXCLUDED.updated_at
        """,
        (record['id'], record['name'], record['state'], record['score'], record['hot_state'], record['source'], record['channel'], record['email'], record['company'], record['touch_count'], json.dumps(record['data']), record['updated_at']),
    )
    search_index(lead_id, {
        'id': lead_id,
        'domain': 'marketing',
        'resource': 'lead',
        'name': record['name'],
        'state': record['state'],
        'score': record['score'],
        'data': record['data'],
        'updatedAt': record['updated_at'],
    }, 'projection')
    return record


def upsert_campaign(conn, campaign_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute('SELECT * FROM campaign_projections WHERE id = %s', (campaign_id,)).fetchone()
    current = dict(row) if row else None
    record = {
        'id': campaign_id,
        'name': defaults.get('name') or (current['name'] if current else 'campaign'),
        'state': defaults.get('state') or (current['state'] if current else 'draft'),
        'budget': float(defaults.get('budget', current['budget'] if current else 0)),
        'planned_recipients': int(defaults.get('planned_recipients', current['planned_recipients'] if current else 0)),
        'sent_count': int(defaults.get('sent_count', current['sent_count'] if current else 0)),
        'open_count': int(defaults.get('open_count', current['open_count'] if current else 0)),
        'click_count': int(defaults.get('click_count', current['click_count'] if current else 0)),
        'unsubscribe_count': int(defaults.get('unsubscribe_count', current['unsubscribe_count'] if current else 0)),
        'data': _merge_json(current['data'] if current else {}, defaults.get('data', {})),
        'updated_at': defaults.get('updated_at', now_iso()),
    }
    conn.execute(
        """
        INSERT INTO campaign_projections (id, name, state, budget, planned_recipients, sent_count, open_count, click_count, unsubscribe_count, data, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
          name = EXCLUDED.name,
          state = EXCLUDED.state,
          budget = EXCLUDED.budget,
          planned_recipients = EXCLUDED.planned_recipients,
          sent_count = EXCLUDED.sent_count,
          open_count = EXCLUDED.open_count,
          click_count = EXCLUDED.click_count,
          unsubscribe_count = EXCLUDED.unsubscribe_count,
          data = EXCLUDED.data,
          updated_at = EXCLUDED.updated_at
        """,
        (record['id'], record['name'], record['state'], record['budget'], record['planned_recipients'], record['sent_count'], record['open_count'], record['click_count'], record['unsubscribe_count'], json.dumps(record['data']), record['updated_at']),
    )
    search_index(campaign_id, {
        'id': campaign_id,
        'domain': 'marketing',
        'resource': 'campaign',
        'name': record['name'],
        'state': record['state'],
        'amount': record['budget'],
        'score': int(record['click_count']),
        'data': record['data'],
        'updatedAt': record['updated_at'],
    }, 'projection')
    return record


def upsert_domain_projection(conn, table: str, record_id: str, resource: str, domain: str, defaults: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(f'SELECT * FROM {table} WHERE id = %s', (record_id,)).fetchone()
    current = dict(row) if row else None
    record = {
        'id': record_id,
        'resource': resource,
        'domain': domain,
        'name': defaults.get('name') or (current['name'] if current else resource),
        'state': defaults.get('state') or (current['state'] if current else 'new'),
        'amount': float(defaults.get('amount', current['amount'] if current else 0)),
        'score': int(defaults.get('score', current['score'] if current else 0)),
        'data': _merge_json(current['data'] if current else {}, defaults.get('data', {})),
        'updated_at': defaults.get('updated_at', now_iso()),
    }
    conn.execute(
        f"""
        INSERT INTO {table} (id, resource, name, state, amount, score, domain, data, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
          resource = EXCLUDED.resource,
          name = EXCLUDED.name,
          state = EXCLUDED.state,
          amount = EXCLUDED.amount,
          score = EXCLUDED.score,
          domain = EXCLUDED.domain,
          data = EXCLUDED.data,
          updated_at = EXCLUDED.updated_at
        """,
        (record['id'], record['resource'], record['name'], record['state'], record['amount'], record['score'], record['domain'], json.dumps(record['data']), record['updated_at']),
    )
    search_index(record_id, {
        'id': record_id,
        'domain': domain,
        'resource': resource,
        'name': record['name'],
        'state': record['state'],
        'amount': record['amount'],
        'score': record['score'],
        'data': record['data'],
        'updatedAt': record['updated_at'],
    }, 'projection')
    return record


def project_event(message: dict[str, Any]) -> None:
    event_type = message.get('eventType', 'unknown')
    payload = message.get('payload', {})
    created_at = message.get('occurredAt') or now_iso()
    with db() as conn:
        if event_type.startswith('marketing.lead.'):
            lead_id = payload.get('id') or payload.get('data', {}).get('leadId')
            if lead_id:
                data = payload.get('data', {})
                upsert_lead(conn, lead_id, {
                    'name': payload.get('name'),
                    'state': payload.get('state'),
                    'score': payload.get('score', 0),
                    'source': data.get('sourceType'),
                    'channel': data.get('channel'),
                    'email': data.get('email'),
                    'company': data.get('company'),
                    'data': data,
                    'updated_at': created_at,
                })
        elif event_type.startswith('marketing.score.'):
            data = payload.get('data', {})
            lead_id = data.get('leadId')
            if lead_id:
                upsert_lead(conn, lead_id, {
                    'name': payload.get('name'),
                    'state': payload.get('state'),
                    'score': payload.get('score', 0),
                    'data': {'band': data.get('band'), 'recommendation': data.get('recommendation')},
                    'updated_at': created_at,
                })
        elif event_type.startswith('marketing.hot_lead.'):
            data = payload.get('data', {})
            lead_id = data.get('leadId')
            if lead_id:
                upsert_lead(conn, lead_id, {
                    'name': payload.get('name'),
                    'state': payload.get('state'),
                    'score': payload.get('score', 0),
                    'hot_state': payload.get('state'),
                    'data': {'priority': data.get('priority'), 'recommendedAction': data.get('recommendedAction'), 'slaHours': data.get('slaHours')},
                    'updated_at': created_at,
                })
        elif event_type.startswith('marketing.campaign.'):
            data = payload.get('data', {})
            stats = data.get('stats', {})
            campaign_id = payload.get('id')
            if campaign_id:
                upsert_campaign(conn, campaign_id, {
                    'name': payload.get('name'),
                    'state': payload.get('state'),
                    'budget': payload.get('amount', 0),
                    'planned_recipients': data.get('plannedRecipients', 0),
                    'sent_count': stats.get('sentCount', 0),
                    'open_count': stats.get('openCount', 0),
                    'click_count': stats.get('clickCount', 0),
                    'unsubscribe_count': stats.get('unsubscribeCount', 0),
                    'data': {'ownerEmail': data.get('ownerEmail'), 'subject': data.get('subject'), 'targetListId': data.get('targetListId')},
                    'updated_at': created_at,
                })
        elif event_type == 'marketing.tracking.recorded':
            data = payload.get('data', {})
            lead_id = data.get('leadId')
            campaign_id = data.get('campaignId')
            event_name = data.get('eventType')
            if lead_id:
                row = conn.execute('SELECT * FROM lead_projections WHERE id = %s', (lead_id,)).fetchone()
                touch_count = int(row['touch_count']) + 1 if row else 1
                upsert_lead(conn, lead_id, {
                    'touch_count': touch_count,
                    'updated_at': created_at,
                    'data': {'lastEventType': event_name, 'lastCampaignId': campaign_id},
                })
            if campaign_id:
                row = conn.execute('SELECT * FROM campaign_projections WHERE id = %s', (campaign_id,)).fetchone()
                if row:
                    current = dict(row)
                    upsert_campaign(conn, campaign_id, {
                        'name': current['name'],
                        'state': current['state'],
                        'budget': current['budget'],
                        'planned_recipients': current['planned_recipients'],
                        'sent_count': int(current['sent_count']),
                        'open_count': int(current['open_count']) + (1 if event_name == 'email_opened' else 0),
                        'click_count': int(current['click_count']) + (1 if event_name == 'link_clicked' else 0),
                        'unsubscribe_count': int(current['unsubscribe_count']) + (1 if event_name == 'unsubscribe_requested' else 0),
                        'updated_at': created_at,
                    })
        else:
            domain = infer_domain(event_type)
            resource = payload.get('resource') or event_type.split('.', 1)[0]
            projection_payload = {
                'name': payload.get('name') or payload.get('candidateName') or payload.get('employeeName') or payload.get('customer') or resource,
                'state': payload.get('state', 'new'),
                'amount': payload.get('amount', 0),
                'score': payload.get('score', 0),
                'data': payload.get('data', payload),
                'updated_at': created_at,
            }
            record_id = payload.get('id')
            if record_id and domain == 'production':
                upsert_domain_projection(conn, 'production_projections', record_id, resource, domain, projection_payload)
            elif record_id and domain == 'talents':
                upsert_domain_projection(conn, 'talent_projections', record_id, resource, domain, projection_payload)
        conn.commit()


def handle_kafka_event(message: dict[str, Any]) -> None:
    insert_kafka_event(message)
    store_event(
        source=message.get('producer', 'unknown'),
        event=message.get('eventType', 'unknown'),
        payload=message,
        event_id=message.get('eventId'),
        created_at=message.get('occurredAt'),
    )
    project_event(message)


@app.on_event('startup')
async def startup_event():
    init_db()
    init_search()
    init_clickhouse()
    app.state.kafka_consumer = KafkaEventConsumer(SERVICE_NAME, handle_kafka_event)
    app.state.kafka_consumer.start()


@app.get('/health')
def health():
    return {
        'service': SERVICE_NAME,
        'status': 'ok',
        'port': PORT,
        'clickhouse': {'enabled': clickhouse_enabled(), 'healthy': clickhouse_ping()},
        'elasticsearch': bool(get_es()),
    }


@app.get('/metrics')
def metrics():
    return PlainTextResponse(generate_latest().decode('utf-8'), media_type=CONTENT_TYPE_LATEST)


@app.post('/events')
async def emit_event(body: EventIn):
    created_at = now_iso()
    event_id = store_event(body.source, body.event, body.payload, created_at=created_at)
    insert_http_event(event_id, infer_domain(body.event), body.source, body.event, body.payload, created_at)
    project_event({'eventId': event_id, 'producer': body.source, 'eventType': body.event, 'payload': body.payload, 'occurredAt': created_at})
    return {'id': event_id, 'stored': True}


def _analytics_backends() -> dict[str, bool]:
    return {
        'postgres': True,
        'clickhouse': clickhouse_ping(),
        'elasticsearch': bool(get_es()),
    }


def _query_domain_events(domain: str, size: int = 20) -> list[dict[str, Any]]:
    if clickhouse_ping():
        rows = query_recent_events(domain, size)
        if rows:
            return rows
    es = get_es()
    if es:
        try:
            response = es.search(index=ELASTICSEARCH_EVENTS_INDEX, size=size, sort=[{'createdAt': {'order': 'desc'}}], query={'term': {'domain': domain}})
            return [hit['_source'] for hit in response['hits']['hits']]
        except Exception:
            pass
    with db() as conn:
        rows = conn.execute('SELECT * FROM events WHERE domain = %s ORDER BY created_at DESC LIMIT %s', (domain, size)).fetchall()
    return [dict(row) for row in rows]


def _query_domain_projections(domain: str, resource: str | None = None, size: int = 200) -> list[dict[str, Any]]:
    es = get_es()
    if es:
        filters = [{'term': {'domain': domain}}]
        if resource:
            filters.append({'term': {'resource': resource}})
        try:
            response = es.search(index=ELASTICSEARCH_PROJECTION_INDEX, size=size, sort=[{'updatedAt': {'order': 'desc'}}], query={'bool': {'filter': filters}})
            return [hit['_source'] for hit in response['hits']['hits']]
        except Exception:
            pass
    table = 'production_projections' if domain == 'production' else 'talent_projections'
    with db() as conn:
        if domain == 'marketing':
            if resource == 'campaign':
                rows = conn.execute('SELECT * FROM campaign_projections ORDER BY updated_at DESC').fetchall()
            else:
                rows = conn.execute('SELECT * FROM lead_projections ORDER BY updated_at DESC').fetchall()
            out = []
            for row in rows:
                rec = dict(row)
                rec['data'] = json.loads(rec['data']) if isinstance(rec.get('data'), str) else rec.get('data', {})
                out.append(rec)
            return out
        if resource:
            rows = conn.execute(f'SELECT * FROM {table} WHERE resource = %s ORDER BY updated_at DESC LIMIT %s', (resource, size)).fetchall()
        else:
            rows = conn.execute(f'SELECT * FROM {table} ORDER BY updated_at DESC LIMIT %s', (size,)).fetchall()
    out = []
    for row in rows:
        rec = dict(row)
        rec['data'] = json.loads(rec['data']) if isinstance(rec.get('data'), str) else rec.get('data', {})
        out.append(rec)
    return out


@app.get('/dashboards/{domain}')
async def dashboard(domain: str):
    key = cache_key('dashboard', domain)
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    events = _query_domain_events(domain, 20)
    event_types = Counter(event.get('event') or event.get('eventType') for event in events)
    if domain == 'marketing':
        campaign_rows = _query_domain_projections(domain, 'campaign')
        lead_rows = _query_domain_projections(domain, 'lead')
        sent_total = sum(int(row.get('sent_count', row.get('data', {}).get('sentCount', 0) or 0)) for row in campaign_rows)
        open_total = sum(int(row.get('open_count', row.get('data', {}).get('openCount', 0) or 0)) for row in campaign_rows)
        click_total = sum(int(row.get('click_count', row.get('data', {}).get('clickCount', 0) or 0)) for row in campaign_rows)
        return {
            'domain': domain,
            'events': len(events),
            'eventTypes': dict(event_types),
            'pipeline': {
                'campaigns': len(campaign_rows),
                'liveCampaigns': sum(1 for row in campaign_rows if row.get('state') == 'live'),
                'sentTotal': sent_total,
                'openRate': round((open_total / sent_total) * 100, 2) if sent_total else 0,
                'clickRate': round((click_total / sent_total) * 100, 2) if sent_total else 0,
                'knownLeads': len(lead_rows),
                'hotLeads': sum(1 for row in lead_rows if row.get('hot_state') == 'sales-ready' or row.get('state') == 'hot'),
            },
            'recent': events[:10],
            'backends': _analytics_backends(),
        }
    rows = _query_domain_projections(domain)
    state_counts = Counter(row.get('state', 'unknown') for row in rows)
    resource_counts = Counter(row.get('resource', 'unknown') for row in rows)
    total_amount = round(sum(float(row.get('amount', 0) or 0) for row in rows), 2)
    avg_score = round(sum(int(row.get('score', 0) or 0) for row in rows) / len(rows), 2) if rows else 0
    summary = {
        'domain': domain,
        'events': len(events),
        'eventTypes': dict(event_types),
        'totals': {
            'records': len(rows),
            'resources': dict(resource_counts),
            'states': dict(state_counts),
            'amountTotal': total_amount,
            'averageScore': avg_score,
        },
        'recent': events[:10],
        'backends': _analytics_backends(),
    }
    if domain == 'production':
        summary['operations'] = {
            'readyToShip': sum(1 for row in rows if row.get('resource') == 'shipments' and row.get('state') in {'on-track', 'shipped'}),
            'qualityHolds': sum(1 for row in rows if row.get('resource') == 'inspections' and row.get('state') == 'hold'),
            'reorderSignals': sum(1 for row in rows if row.get('resource') == 'items' and row.get('state') == 'reorder'),
        }
    elif domain == 'talents':
        summary['people'] = {
            'activeEmployees': sum(1 for row in rows if row.get('resource') == 'employees' and row.get('state') == 'active'),
            'needsAttention': sum(1 for row in rows if row.get('resource') == 'pulses' and row.get('state') == 'needs-attention'),
            'interviewsInFlight': sum(1 for row in rows if row.get('resource') == 'candidates' and row.get('state') == 'interview'),
        }
    return summary


@app.get('/reports/campaigns')
async def campaign_report():
    key = cache_key('report:campaigns')
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    rows = _query_domain_projections('marketing', 'campaign')
    result = []
    for record in rows:
        sent = int(record.get('sent_count', 0) or 0)
        opens = int(record.get('open_count', 0) or 0)
        clicks = int(record.get('click_count', 0) or 0)
        record['openRate'] = round((opens / sent) * 100, 2) if sent else 0
        record['clickRate'] = round((clicks / sent) * 100, 2) if sent else 0
        result.append(record)
    return result


@app.get('/reports/leads')
async def lead_report():
    key = cache_key('report:leads')
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    return _query_domain_projections('marketing', 'lead')


@app.get('/reports/production')
async def production_report():
    key = cache_key('report:production')
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    return _query_domain_projections('production')


@app.get('/reports/talents')
async def talent_report():
    key = cache_key('report:talents')
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    return _query_domain_projections('talents')


@app.on_event('shutdown')
async def shutdown_event():
    consumer = getattr(app.state, 'kafka_consumer', None)
    if consumer:
        consumer.stop()
    close_clickhouse()
    await close_redis()
