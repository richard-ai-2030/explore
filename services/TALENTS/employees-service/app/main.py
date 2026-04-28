import json
import os
import psycopg
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from psycopg.rows import dict_row

from .eventing import OutboxRelay, enqueue_outbox_event, init_outbox_table
from .redis_cache import cache_key, close as close_redis, delete_prefix, enabled as redis_enabled, get_json, ping as redis_ping, set_json

SERVICE_NAME = "employees-service"
PORT = int(os.getenv('PORT', '7142'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])

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

@app.middleware('http')
async def metrics_middleware(request: Request, call_next):
    with LATENCY.labels(SERVICE_NAME, request.method, request.url.path).time():
        response = await call_next(request)
    REQUESTS.labels(SERVICE_NAME, request.method, request.url.path, str(response.status_code)).inc()
    response.headers['X-Service-Name'] = SERVICE_NAME
    return response

@app.get('/health')
async def health():
    return {'service': SERVICE_NAME, 'status': 'ok', 'port': PORT, 'redis': {'enabled': redis_enabled(), 'healthy': await redis_ping() if redis_enabled() else False}}

@app.get('/metrics')
def metrics():
    return PlainTextResponse(generate_latest().decode('utf-8'), media_type=CONTENT_TYPE_LATEST)

async def invalidate_resource_cache() -> None:
    await delete_prefix(cache_key(RESOURCE))

def list_cache_key() -> str:
    return cache_key(RESOURCE, 'list')

def summary_cache_key() -> str:
    return cache_key(RESOURCE, 'summary')

def record_cache_key(record_id: str) -> str:
    return cache_key(RESOURCE, record_id)

RESOURCE = "employees"

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
        init_outbox_table(conn)
        conn.commit()

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

def compute(payload: dict[str, Any]) -> dict[str, Any]:
    base_name = payload.get('title') or payload.get('name') or payload.get('company') or payload.get('employeeName') or payload.get('candidateName') or SERVICE_NAME
    amount = float(payload.get('amount') or payload.get('budget') or payload.get('value') or payload.get('price') or payload.get('salary') or payload.get('cost') or 0)
    score = int(payload.get('score') or 0)
    state = payload.get('state') or 'draft'
    insights: dict[str, Any] = {}

    if SERVICE_NAME == 'leads-acquisition-service':
        fit = int(payload.get('fit', 50))
        intent = int(payload.get('intent', 50))
        urgency = int(payload.get('urgency', 40))
        score = min(100, round(fit * 0.45 + intent * 0.35 + urgency * 0.20))
        state = 'qualified' if score >= 75 else 'nurture'
        insights = {'channel': payload.get('channel', 'organic'), 'qualityBand': 'hot' if score >= 85 else 'warm' if score >= 65 else 'cold'}
    elif SERVICE_NAME == 'campaign-service':
        budget = float(payload.get('budget', amount or 5000))
        target = int(payload.get('targetLeads', 100))
        amount = budget
        score = min(100, round((budget / max(target, 1)) / 5 * 10))
        state = 'launch-ready' if budget > 0 else 'draft'
        insights = {'targetLeads': target, 'expectedCpl': round(budget / max(target, 1), 2)}
    elif SERVICE_NAME == 'scoring-service':
        fit = int(payload.get('fit', 50))
        intent = int(payload.get('intent', 50))
        urgency = int(payload.get('urgency', 50))
        score = min(100, round(fit * 0.5 + intent * 0.3 + urgency * 0.2))
        state = 'hot' if score >= 80 else 'warm' if score >= 60 else 'cold'
        insights = {'recommendation': 'route to sales' if score >= 80 else 'continue nurture'}
    elif SERVICE_NAME == 'tracking-service':
        touches = int(payload.get('touches', 1))
        conversions = int(payload.get('conversions', 0))
        revenue = float(payload.get('revenue', 0))
        score = min(100, conversions * 25 + touches * 3)
        amount = revenue
        state = 'converted' if conversions else 'observing'
        insights = {'touches': touches, 'conversions': conversions}
    elif SERVICE_NAME == 'hot-lead-service':
        score = int(payload.get('score', 70))
        amount = float(payload.get('expectedDeal', amount or 10000))
        state = 'engaged' if score >= 80 else 'triage'
        insights = {'slaHours': 4 if score >= 90 else 24, 'segment': payload.get('segment', 'mid-market')}
    elif SERVICE_NAME == 'quotation-service':
        items = payload.get('items', [])
        if items:
            amount = round(sum(float(item.get('qty', 1)) * float(item.get('price', 0)) for item in items), 2)
        approval_limit = float(payload.get('approvalLimit', 5000))
        score = 90 if amount <= approval_limit else 60
        state = 'approved' if amount <= approval_limit else 'pending-approval'
        insights = {'lineItems': len(items), 'approvalRequired': amount > approval_limit}
    elif SERVICE_NAME == 'order-service':
        quantity = int(payload.get('quantity', 1))
        unit_price = float(payload.get('unitPrice', amount or 100))
        amount = round(quantity * unit_price, 2)
        score = min(100, 50 + quantity * 5)
        state = 'allocated' if quantity <= int(payload.get('availableStock', 10)) else 'backorder'
        insights = {'quantity': quantity, 'priority': payload.get('priority', 'standard')}
    elif SERVICE_NAME == 'payment-service':
        amount = float(payload.get('amount', amount or 0))
        received = float(payload.get('received', amount))
        score = 100 if received >= amount else max(0, round((received / max(amount, 1)) * 100))
        state = 'captured' if received >= amount else 'partial'
        insights = {'method': payload.get('method', 'card'), 'received': received}
    elif SERVICE_NAME == 'supplier-service':
        reliability = int(payload.get('reliability', 70))
        compliance = int(payload.get('compliance', 70))
        score = round(reliability * 0.6 + compliance * 0.4)
        state = 'preferred' if score >= 85 else 'approved' if score >= 65 else 'review'
        insights = {'country': payload.get('country', 'unknown'), 'category': payload.get('category', 'general')}
    elif SERVICE_NAME == 'procurement-service':
        amount = float(payload.get('amount', amount or 1000))
        score = 95 if amount < 10000 else 70
        state = 'approved' if amount < 10000 else 'board-review'
        insights = {'neededBy': payload.get('neededBy', (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat())}
    elif SERVICE_NAME == 'inventory-service':
        on_hand = int(payload.get('onHand', 0))
        reserved = int(payload.get('reserved', 0))
        reorder_point = int(payload.get('reorderPoint', 10))
        available = on_hand - reserved
        score = max(0, min(100, available * 5))
        state = 'reorder' if available <= reorder_point else 'healthy'
        insights = {'onHand': on_hand, 'reserved': reserved, 'available': available}
    elif SERVICE_NAME == 'logistics-service':
        delay_risk = int(payload.get('delayRisk', 20))
        score = 100 - min(100, delay_risk)
        state = 'on-track' if delay_risk < 35 else 'watch'
        insights = {'etaDays': int(payload.get('etaDays', 5)), 'carrier': payload.get('carrier', 'internal')}
    elif SERVICE_NAME == 'quality-service':
        defects = int(payload.get('defects', 0))
        sample = max(1, int(payload.get('sampleSize', 10)))
        defect_rate = defects / sample
        score = max(0, 100 - round(defect_rate * 100))
        state = 'pass' if defect_rate <= 0.05 else 'hold'
        insights = {'defects': defects, 'sampleSize': sample, 'defectRate': round(defect_rate, 3)}
    elif SERVICE_NAME == 'invoice-service':
        amount = float(payload.get('amount', amount or 0))
        due_days = int(payload.get('dueDays', 30))
        score = 100 if amount < 5000 else 75
        state = 'issued'
        insights = {'dueDate': (datetime.now(timezone.utc) + timedelta(days=due_days)).date().isoformat(), 'customer': payload.get('customer', 'unknown')}
    elif SERVICE_NAME == 'revenue-service':
        amount = float(payload.get('amount', amount or 0))
        months = max(1, int(payload.get('months', 12)))
        score = min(100, months * 5)
        state = 'scheduled'
        insights = {'monthlyRecognition': round(amount / months, 2), 'months': months}
    elif SERVICE_NAME == 'cost-service':
        budget = float(payload.get('budget', amount or 0))
        actual = float(payload.get('actual', budget))
        variance = actual - budget
        amount = actual
        score = max(0, 100 - int(abs(variance) / max(budget, 1) * 100))
        state = 'within-budget' if variance <= 0 else 'overrun'
        insights = {'budget': budget, 'variance': round(variance, 2)}
    elif SERVICE_NAME == 'payroll-service':
        gross = float(payload.get('gross', amount or 0))
        deductions = float(payload.get('deductions', gross * 0.2))
        net = gross - deductions
        amount = net
        score = 100
        state = 'ready'
        insights = {'gross': gross, 'deductions': deductions, 'net': net, 'employeeId': payload.get('employeeId')}
    elif SERVICE_NAME == 'recruitment-service':
        fit = int(payload.get('fit', 60))
        availability = int(payload.get('availability', 60))
        score = round(fit * 0.7 + availability * 0.3)
        state = 'interview' if score >= 70 else 'sourced'
        insights = {'role': payload.get('role', 'generalist'), 'source': payload.get('source', 'referral')}
    elif SERVICE_NAME == 'employees-service':
        level = payload.get('level', 'L2')
        score = {'L1': 45, 'L2': 60, 'L3': 75, 'L4': 90}.get(level, 55)
        amount = float(payload.get('salary', amount or 0))
        state = 'active'
        insights = {'department': payload.get('department', 'general'), 'manager': payload.get('manager', 'unassigned')}
    elif SERVICE_NAME == 'attendance-service':
        hours = float(payload.get('hours', 8))
        late_minutes = int(payload.get('lateMinutes', 0))
        score = max(0, 100 - late_minutes)
        state = 'present' if hours >= 4 else 'absence-review'
        insights = {'hours': hours, 'lateMinutes': late_minutes, 'workMode': payload.get('workMode', 'onsite')}
    elif SERVICE_NAME == 'motivation-service':
        mood = int(payload.get('mood', 70))
        recognition = int(payload.get('recognition', 70))
        workload = int(payload.get('workload', 50))
        score = round(mood * 0.45 + recognition * 0.35 + (100 - workload) * 0.20)
        state = 'healthy' if score >= 70 else 'needs-attention'
        insights = {'recommendedAction': 'manager follow-up' if score < 70 else 'keep momentum'}

    return {
        'name': base_name,
        'amount': round(amount, 2),
        'score': int(score),
        'state': state,
        'data': {**payload, **insights},
    }

def row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': row['id'],
        'name': row['name'],
        'state': row['state'],
        'amount': row['amount'],
        'score': row['score'],
        'data': json.loads(row['data']),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }

@app.get('/' + RESOURCE)
async def list_records():
    cached = await get_json(list_cache_key())
    if cached is not None:
        return {**cached, '_cache': 'hit'} if isinstance(cached, dict) else cached
    with db() as conn:
        rows = conn.execute('SELECT * FROM records ORDER BY created_at DESC').fetchall()
    return [row_to_record(row) for row in rows]

@app.get('/' + RESOURCE + '/summary')
async def summary():
    cached = await get_json(summary_cache_key())
    if cached is not None:
        return {**cached, '_cache': 'hit'} if isinstance(cached, dict) else cached
    with db() as conn:
        rows = conn.execute('SELECT * FROM records').fetchall()
    records = [row_to_record(row) for row in rows]
    counts = Counter(record['state'] for record in records)
    return {
        'service': SERVICE_NAME,
        'resource': RESOURCE,
        'total': len(records),
        'states': dict(counts),
        'amountTotal': round(sum(float(record['amount']) for record in records), 2),
        'averageScore': round(sum(int(record['score']) for record in records) / len(records), 2) if records else 0,
    }

@app.post('/' + RESOURCE)
def create_record(body: RecordIn, request: Request):
    computed = compute(body.payload)
    record_id = str(uuid.uuid4())
    now = now_iso()
    with db() as conn:
        conn.execute(
            'INSERT INTO records (id, name, state, amount, score, data, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (record_id, computed['name'], computed['state'], computed['amount'], computed['score'], json.dumps(computed['data']), now, now),
        )
        event_payload = {
            'id': record_id,
            **computed,
            'createdAt': now,
            'updatedAt': now,
            'resource': RESOURCE,
        }
        enqueue_outbox_event(conn, SERVICE_NAME, f'{SERVICE_NAME}.record.created', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return {'id': record_id, **computed, 'createdAt': now, 'updatedAt': now, 'actor': request.headers.get('x-auth-user-email')}

@app.get('/' + RESOURCE + '/{record_id}')
async def get_record(record_id: str):
    cached = await get_json(record_cache_key(record_id))
    if cached is not None:
        return {**cached, '_cache': 'hit'} if isinstance(cached, dict) else cached
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Record not found')
    return row_to_record(row)

@app.post('/' + RESOURCE + '/{record_id}/actions/{action}')
def apply_action(record_id: str, action: str, request: Request):
    transitions = {
        'approve': 'approved',
        'launch': 'live',
        'ship': 'shipped',
        'complete': 'completed',
        'pay': 'paid',
        'activate': 'active',
        'hold': 'hold',
        'follow-up': 'follow-up',
    }
    new_state = transitions.get(action, action.replace('_', '-'))
    now = now_iso()
    with db() as conn:
        row = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Record not found')
        data = json.loads(row['data'])
        data['lastAction'] = action
        conn.execute('UPDATE records SET state = %s, data = %s, updated_at = %s WHERE id = %s', (new_state, json.dumps(data), now, record_id))
        updated = conn.execute('SELECT * FROM records WHERE id = %s', (record_id,)).fetchone()
        event_payload = row_to_record(updated)
        event_payload['action'] = action
        event_payload['resource'] = RESOURCE
        enqueue_outbox_event(conn, SERVICE_NAME, f'{SERVICE_NAME}.record.{action.replace('-', '_')}', record_id, event_payload, request_headers=dict(request.headers))
        conn.commit()
    return row_to_record(updated)
