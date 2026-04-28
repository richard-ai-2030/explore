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

SERVICE_NAME = "hot-lead-service"
PORT = int(os.getenv('PORT', '7111'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])
RESOURCE = 'hot-leads'
MUTATING_SCOPES = {'marketing', 'marketing-admin', 'marketing-ops', 'sales'}

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
    score = int(payload.get('score', 0))
    pricing_visits = int(payload.get('pricingVisits', 0))
    replies = int(payload.get('replies', 0))
    form_submits = int(payload.get('formSubmits', 0))
    expected_deal = round(float(payload.get('expectedDeal', 0) or 0), 2)
    unsubscribed = bool(payload.get('unsubscribed', False))
    if unsubscribed:
        state = 'suppressed'
    elif score >= 85 or replies > 0 or form_submits > 0 or pricing_visits >= 2:
        state = 'sales-ready'
    elif score >= 70:
        state = 'engaged'
    elif score >= 55:
        state = 'monitor'
    else:
        state = 'nurture'
    priority = 'p1' if state == 'sales-ready' and expected_deal >= 15000 else 'p2' if state == 'sales-ready' else 'p3'
    sla_hours = 1 if priority == 'p1' else 4 if state == 'sales-ready' else 24 if state == 'engaged' else 72
    data = {
        'leadId': payload.get('leadId') or payload.get('captureId'),
        'company': payload.get('company'),
        'segment': payload.get('segment', 'mid-market'),
        'ownerEmail': payload.get('ownerEmail') or 'sales@gmail.com',
        'pricingVisits': pricing_visits,
        'replies': replies,
        'formSubmits': form_submits,
        'priority': priority,
        'slaHours': sla_hours,
        'recommendedAction': 'call-now' if state == 'sales-ready' else 'personalized-follow-up' if state == 'engaged' else 'nurture-track',
    }
    return {
        'name': payload.get('personName') or payload.get('name') or payload.get('company') or 'hot-lead',
        'state': state,
        'amount': expected_deal,
        'score': score,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hot_state ON records (state)")
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
def list_records(state: str | None = None):
    with db() as conn:
        rows = conn.execute('SELECT * FROM records ORDER BY created_at DESC').fetchall()
    records = [row_to_record(row) for row in rows]
    if state:
        records = [record for record in records if record['state'] == state]
    return records


@app.get('/' + RESOURCE + '/summary')
def summary():
    with db() as conn:
        rows = conn.execute('SELECT * FROM records').fetchall()
    records = [row_to_record(row) for row in rows]
    counts = Counter(record['state'] for record in records)
    return {
        'service': SERVICE_NAME,
        'resource': RESOURCE,
        'total': len(records),
        'states': dict(counts),
        'salesReady': counts.get('sales-ready', 0),
        'pipelineValue': round(sum(record['amount'] for record in records if record['state'] in {'sales-ready', 'engaged'}), 2),
    }


@app.post('/' + RESOURCE)
def create_record(body: RecordIn, request: Request):
    require_scope(request, MUTATING_SCOPES)
    computed = compute(body.payload)
    record_id = str(uuid.uuid4())
    now = now_iso()
    event_payload = {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now, 'resource': RESOURCE}
    event_type = 'marketing.hot_lead.raised' if computed['state'] == 'sales-ready' else 'marketing.hot_lead.evaluated'
    with db() as conn:
        conn.execute(
            'INSERT INTO records (id, name, state, amount, score, data, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (record_id, computed['name'], computed['state'], computed['amount'], computed['score'], json.dumps(computed['data']), now, now),
        )
        enqueue_outbox_event(conn, SERVICE_NAME, event_type, record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now}


@app.get('/' + RESOURCE + '/{record_id}')
def get_record(record_id: str):
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Hot lead record not found')
    return row_to_record(row)
