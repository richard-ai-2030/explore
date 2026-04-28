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

SERVICE_NAME = "leads-acquisition-service"
PORT = int(os.getenv('PORT', '7101'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])
RESOURCE = 'captures'
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


def quality_band(score: int) -> str:
    if score >= 85:
        return 'hot'
    if score >= 65:
        return 'warm'
    return 'cold'


def compute(payload: dict[str, Any]) -> dict[str, Any]:
    email = (payload.get('email') or payload.get('workEmail') or '').strip().lower()
    company = payload.get('company') or payload.get('companyName') or 'unknown-company'
    contact_name = payload.get('personName') or payload.get('name') or email or company
    source_type = payload.get('sourceType') or ('inbound-form' if payload.get('formCode') else 'manual')
    channel = payload.get('channel') or ('web' if source_type == 'inbound-form' else 'crm-import')
    fit = int(payload.get('fit', 50))
    intent = int(payload.get('intent', 45))
    urgency = int(payload.get('urgency', 40))
    company_size = int(payload.get('companySize', 80 if payload.get('segment') == 'enterprise' else 35))
    consent = bool(payload.get('consent', True))
    tags = list(dict.fromkeys([str(item).strip() for item in payload.get('tags', []) if str(item).strip()]))
    dedupe_key = email or f"{company.lower()}::{contact_name.lower()}"
    score = min(100, round(fit * 0.30 + intent * 0.30 + urgency * 0.20 + min(company_size, 100) * 0.20))
    if 'decision-maker' in tags:
        score = min(100, score + 5)
    state = 'unsubscribed' if not consent else 'qualified' if score >= 75 else 'captured'
    if score < 45 and consent:
        state = 'nurture'
    segment = payload.get('segment') or ('enterprise' if company_size >= 250 else 'smb')
    owner = payload.get('ownerEmail') or 'growth@gmail.com'
    target_list = payload.get('targetList') or f"{channel}-{quality_band(score)}"
    data = {
        'email': email,
        'company': company,
        'personName': contact_name,
        'sourceType': source_type,
        'channel': channel,
        'formCode': payload.get('formCode'),
        'landingPage': payload.get('landingPage'),
        'consent': consent,
        'tags': tags,
        'segment': segment,
        'companySize': company_size,
        'targetList': target_list,
        'qualityBand': quality_band(score),
        'ownerEmail': owner,
        'dedupeKey': dedupe_key,
        'notes': payload.get('notes'),
    }
    return {
        'name': contact_name,
        'state': state,
        'amount': 0.0,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_state ON records (state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON records (score)")
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
def list_records(state: str | None = None, quality_band_filter: str | None = None):
    with db() as conn:
        rows = conn.execute('SELECT * FROM records ORDER BY created_at DESC').fetchall()
    records = [row_to_record(row) for row in rows]
    if state:
        records = [record for record in records if record['state'] == state]
    if quality_band_filter:
        records = [record for record in records if record['data'].get('qualityBand') == quality_band_filter]
    return records


@app.get('/' + RESOURCE + '/summary')
def summary():
    with db() as conn:
        rows = conn.execute('SELECT * FROM records').fetchall()
    records = [row_to_record(row) for row in rows]
    state_counts = Counter(record['state'] for record in records)
    band_counts = Counter(record['data'].get('qualityBand', 'unknown') for record in records)
    channel_counts = Counter(record['data'].get('channel', 'unknown') for record in records)
    return {
        'service': SERVICE_NAME,
        'resource': RESOURCE,
        'total': len(records),
        'states': dict(state_counts),
        'qualityBands': dict(band_counts),
        'channels': dict(channel_counts),
        'averageScore': round(sum(record['score'] for record in records) / len(records), 2) if records else 0,
    }


@app.post('/' + RESOURCE)
def create_record(body: RecordIn, request: Request):
    require_scope(request, MUTATING_SCOPES)
    computed = compute(body.payload)
    record_id = str(uuid.uuid4())
    now = now_iso()
    event_payload = {
        'id': record_id,
        **computed,
        'createdAt': now,
        'updatedAt': now,
        'resource': RESOURCE,
    }
    with db() as conn:
        conn.execute(
            'INSERT INTO records (id, name, state, amount, score, data, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (record_id, computed['name'], computed['state'], computed['amount'], computed['score'], json.dumps(computed['data']), now, now),
        )
        enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.lead.captured', record_id, event_payload, request_headers=dict(request.headers))
        if computed['state'] == 'unsubscribed':
            enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.lead.unsubscribed', record_id, event_payload, request_headers=dict(request.headers))
        elif computed['state'] == 'qualified':
            enqueue_outbox_event(conn, SERVICE_NAME, 'marketing.lead.qualified', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now}


@app.get('/' + RESOURCE + '/{record_id}')
def get_record(record_id: str):
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Lead not found')
    return row_to_record(row)


@app.post('/' + RESOURCE + '/{record_id}/actions/{action}')
def apply_action(record_id: str, action: str, request: Request):
    require_scope(request, MUTATING_SCOPES)
    transitions = {
        'qualify': 'qualified',
        'nurture': 'nurture',
        'unsubscribe': 'unsubscribed',
        'resubscribe': 'captured',
        'enrich': 'captured',
        'assign': 'captured',
    }
    new_state = transitions.get(action, action.replace('_', '-'))
    now = now_iso()
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Lead not found')
        data = json.loads(row['data'])
        data['lastAction'] = action
        data['qualityBand'] = quality_band(int(row['score']))
        if action == 'unsubscribe':
            data['consent'] = False
        if action == 'resubscribe':
            data['consent'] = True
        conn.execute('UPDATE records SET state = %s, data = %s, updated_at = %s WHERE id = %s', (new_state, json.dumps(data), now, record_id))
        updated = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        event_payload = row_to_record(updated)
        event_payload['action'] = action
        enqueue_outbox_event(conn, SERVICE_NAME, f'marketing.lead.{action.replace("-", "_")}', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return row_to_record(updated)
