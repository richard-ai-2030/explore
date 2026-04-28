import json
import os
import psycopg
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from psycopg.rows import dict_row

from .eventing import OutboxRelay, enqueue_outbox_event, init_outbox_table

SERVICE_NAME = "tracking-service"
PORT = int(os.getenv('PORT', '7104'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])
RESOURCE = 'events'
MUTATING_SCOPES = {'marketing', 'marketing-admin', 'marketing-ops', 'sales'}
EVENT_WEIGHTS = {
    'email_opened': 5,
    'link_clicked': 15,
    'website_browsed': 8,
    'form_submitted': 30,
    'reply_received': 40,
    'unsubscribe_requested': -50,
}

class RecordIn(BaseModel):
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


def request_scopes(request: Request) -> set[str]:
    return {item.strip() for item in request.headers.get('x-auth-scopes', '').split(',') if item.strip()}


def require_scope(request: Request, allowed: set[str]) -> None:
    scopes = request_scopes(request)
    if scopes and not scopes.intersection(allowed):
        raise HTTPException(403, 'Forbidden for supplied role scopes')


def row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
    return {
        'id': row['id'],
        'name': row['name'],
        'state': row['state'],
        'amount': float(row['amount']),
        'score': int(row['score']),
        'data': data,
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


def compute(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = payload.get('eventType') or payload.get('type') or 'website_browsed'
    lead_id = payload.get('leadId') or payload.get('captureId') or payload.get('contactId')
    campaign_id = payload.get('campaignId')
    url = payload.get('url') or payload.get('landingPage') or payload.get('page')
    weight = EVENT_WEIGHTS.get(event_type, 1)
    state = 'negative' if weight < 0 else 'engaged' if weight >= 15 else 'observed'
    data = {
        'eventType': event_type,
        'leadId': lead_id,
        'campaignId': campaign_id,
        'url': url,
        'utm': payload.get('utm', {}),
        'ip': payload.get('ip'),
        'userAgent': payload.get('userAgent'),
        'referrer': payload.get('referrer'),
        'metadata': payload.get('metadata', {}),
    }
    return {
        'name': event_type,
        'state': state,
        'amount': float(payload.get('revenue', 0) or 0),
        'score': max(0, min(100, 50 + weight)),
        'data': data,
    }


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              state TEXT NOT NULL,
              amount REAL NOT NULL DEFAULT 0,
              score INTEGER NOT NULL DEFAULT 0,
              data TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_name ON records (name)")
        init_outbox_table(conn)
        conn.commit()


@app.middleware('http')
async def metrics_middleware(request: Request, call_next):
    with LATENCY.labels(SERVICE_NAME, request.method, request.url.path).time():
        response = await call_next(request)
    REQUESTS.labels(SERVICE_NAME, request.method, request.url.path, str(response.status_code)).inc()
    response.headers['X-Service-Name'] = SERVICE_NAME
    return response


@app.on_event('startup')
async def startup_event():
    init_db()
    app.state.outbox_relay = OutboxRelay(SERVICE_NAME, db)
    app.state.outbox_relay.start()


@app.on_event('shutdown')
def shutdown_event():
    relay = getattr(app.state, 'outbox_relay', None)
    if relay:
        relay.stop()


@app.get('/health')
def health():
    return {'service': SERVICE_NAME, 'status': 'ok', 'port': PORT}


@app.get('/metrics')
def metrics():
    return PlainTextResponse(generate_latest().decode('utf-8'), media_type=CONTENT_TYPE_LATEST)


@app.get('/' + RESOURCE)
def list_records(event_type: str | None = None, lead_id: str | None = None):
    with db() as conn:
        rows = conn.execute('SELECT * FROM records ORDER BY created_at DESC').fetchall()
    records = [row_to_record(row) for row in rows]
    if event_type:
        records = [record for record in records if record['data'].get('eventType') == event_type]
    if lead_id:
        records = [record for record in records if record['data'].get('leadId') == lead_id]
    return records


@app.get('/' + RESOURCE + '/summary')
def summary():
    with db() as conn:
        rows = conn.execute('SELECT * FROM records').fetchall()
    records = [row_to_record(row) for row in rows]
    by_event = Counter(record['data'].get('eventType', record['name']) for record in records)
    by_state = Counter(record['state'] for record in records)
    return {
        'service': SERVICE_NAME,
        'resource': RESOURCE,
        'total': len(records),
        'states': dict(by_state),
        'eventTypes': dict(by_event),
        'negativeEvents': by_event.get('unsubscribe_requested', 0),
        'engagedEvents': sum(1 for record in records if record['state'] == 'engaged'),
    }


@app.post('/' + RESOURCE)
def create_record(body: RecordIn, request: Request):
    require_scope(request, MUTATING_SCOPES)
    computed = compute(body.payload)
    record_id = str(uuid.uuid4())
    now = now_iso()
    event_payload = {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now, 'resource': RESOURCE}
    with db() as conn:
        conn.execute(
            'INSERT INTO records (id, name, state, amount, score, data, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (record_id, computed['name'], computed['state'], computed['amount'], computed['score'], json.dumps(computed['data']), now, now),
        )
        enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.tracking.recorded', record_id, event_payload, request_headers=dict(request.headers))
        if computed['data'].get('eventType') == 'unsubscribe_requested':
            enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.lead.unsubscribed', computed['data'].get('leadId') or record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now}


@app.get('/' + RESOURCE + '/{record_id}')
def get_record(record_id: str):
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Tracking event not found')
    return row_to_record(row)
