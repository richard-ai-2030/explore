import json
import os
import psycopg
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from psycopg.rows import dict_row

from .eventing import OutboxRelay, enqueue_outbox_event, init_outbox_table

SERVICE_NAME = "campaign-service"
PORT = int(os.getenv('PORT', '7102'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))
DEFAULT_OWNER_EMAIL = os.getenv('DEFAULT_OWNER_EMAIL', 'marketing@gmail.com')

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])
RESOURCE = 'campaigns'
MUTATING_SCOPES = {'marketing', 'marketing-admin', 'marketing-ops'}

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
    planned_recipients = max(1, int(payload.get('plannedRecipients') or payload.get('targetLeads') or 100))
    budget = round(float(payload.get('budget', 0) or 0), 2)
    send_window_hours = int(payload.get('sendWindowHours', 24))
    template = payload.get('templateCode') or payload.get('template') or 'default-mail'
    content_kind = payload.get('contentKind') or ('inbound' if payload.get('inboundFormCode') else 'outbound')
    scheduled_at = payload.get('scheduledAt') or (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    ready = bool(payload.get('subject') and payload.get('targetListId'))
    state = payload.get('state') or ('ready' if ready else 'draft')
    score = min(100, round((budget / max(planned_recipients, 1)) * 2 + (20 if ready else 0) + min(send_window_hours, 72) / 4))
    data = {
        'subject': payload.get('subject') or payload.get('name') or 'Untitled campaign',
        'templateCode': template,
        'contentKind': content_kind,
        'targetListId': payload.get('targetListId') or payload.get('targetList') or 'default-list',
        'plannedRecipients': planned_recipients,
        'scheduledAt': scheduled_at,
        'sendWindowHours': send_window_hours,
        'ownerEmail': payload.get('ownerEmail') or DEFAULT_OWNER_EMAIL,
        'inboundFormCode': payload.get('inboundFormCode'),
        'utm': payload.get('utm', {}),
        'stats': {
            'sentCount': int(payload.get('sentCount', 0)),
            'openCount': int(payload.get('openCount', 0)),
            'clickCount': int(payload.get('clickCount', 0)),
            'unsubscribeCount': int(payload.get('unsubscribeCount', 0)),
        },
        'expectedCpl': round(budget / max(planned_recipients, 1), 2) if planned_recipients else 0,
    }
    return {
        'name': payload.get('name') or payload.get('title') or data['subject'],
        'state': state,
        'amount': budget,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_state ON records (state)")
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
    sent = sum(int(record['data'].get('stats', {}).get('sentCount', 0)) for record in records)
    opens = sum(int(record['data'].get('stats', {}).get('openCount', 0)) for record in records)
    clicks = sum(int(record['data'].get('stats', {}).get('clickCount', 0)) for record in records)
    unsubscribes = sum(int(record['data'].get('stats', {}).get('unsubscribeCount', 0)) for record in records)
    return {
        'service': SERVICE_NAME,
        'resource': RESOURCE,
        'total': len(records),
        'states': dict(counts),
        'budgetTotal': round(sum(record['amount'] for record in records), 2),
        'plannedRecipients': sum(int(record['data'].get('plannedRecipients', 0)) for record in records),
        'sentCount': sent,
        'openRate': round((opens / sent) * 100, 2) if sent else 0,
        'clickRate': round((clicks / sent) * 100, 2) if sent else 0,
        'unsubscribeRate': round((unsubscribes / sent) * 100, 2) if sent else 0,
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
        enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.campaign.created', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now}


@app.get('/' + RESOURCE + '/{record_id}')
def get_record(record_id: str):
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Campaign not found')
    return row_to_record(row)


@app.post('/' + RESOURCE + '/{record_id}/actions/{action}')
def apply_action(record_id: str, action: str, request: Request):
    require_scope(request, MUTATING_SCOPES)
    transitions = {
        'confirm': 'confirmed',
        'schedule': 'scheduled',
        'launch': 'live',
        'pause': 'paused',
        'complete': 'completed',
        'cancel': 'cancelled',
    }
    new_state = transitions.get(action, action.replace('_', '-'))
    now = now_iso()
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Campaign not found')
        data = json.loads(row['data'])
        data['lastAction'] = action
        stats = data.get('stats', {})
        if action == 'launch':
            stats['sentCount'] = max(int(stats.get('sentCount', 0)), int(data.get('plannedRecipients', 0)))
            data['launchedAt'] = now
        if action == 'complete' and int(stats.get('sentCount', 0)) > 0:
            stats['openCount'] = max(int(stats.get('openCount', 0)), round(int(stats.get('sentCount', 0)) * 0.32))
            stats['clickCount'] = max(int(stats.get('clickCount', 0)), round(int(stats.get('sentCount', 0)) * 0.09))
        data['stats'] = stats
        conn.execute('UPDATE records SET state = %s, data = %s, updated_at = %s WHERE id = %s', (new_state, json.dumps(data), now, record_id))
        updated = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        event_payload = row_to_record(updated)
        event_payload['action'] = action
        enqueue_outbox_event(conn, SERVICE_NAME, f'marketing.campaign.{action.replace("-", "_")}', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return row_to_record(updated)
