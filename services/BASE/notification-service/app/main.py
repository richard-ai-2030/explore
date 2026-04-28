import json
import os
import psycopg
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from psycopg.rows import dict_row
from .redis_cache import cache_key, close as close_redis, delete_prefix, enabled as redis_enabled, get_json, ping as redis_ping, set_json

from .eventing import KafkaEventConsumer

SERVICE_NAME = "notification-service"
PORT = int(os.getenv('PORT', '7001'))
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
POSTGRES_DB = os.getenv('POSTGRES_DB', SERVICE_NAME.replace('-', '_'))
NOTIFICATION_EVENT_TYPES = {item.strip() for item in os.getenv('NOTIFICATION_EVENT_TYPES', 'auth.user.registered,marketing.campaign.launch,marketing.hot_lead.raised,marketing.lead.unsubscribed').split(',') if item.strip()}

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])

class NotificationIn(BaseModel):
    channel: str = 'email'
    recipient: str
    subject: str
    message: str
    category: str = 'general'


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


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id TEXT PRIMARY KEY,
              channel TEXT NOT NULL,
              recipient TEXT NOT NULL,
              subject TEXT NOT NULL,
              message TEXT NOT NULL,
              category TEXT NOT NULL,
              status TEXT NOT NULL,
              source_event_id TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()



def create_notification(channel: str, recipient: str, subject: str, message: str, category: str, source_event_id: str | None = None) -> dict[str, Any]:
    record_id = str(uuid.uuid4())
    now = now_iso()
    with db() as conn:
        conn.execute(
            'INSERT INTO notifications (id, channel, recipient, subject, message, category, status, source_event_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source_event_id) DO NOTHING',
            (record_id, channel, recipient, subject, message, category, 'queued', source_event_id, now),
        )
        conn.commit()
    return {'id': record_id, 'status': 'queued', 'preview': f'[{channel}] {subject} -> {recipient}'}


def event_to_notification(message: dict[str, Any]) -> dict[str, str] | None:
    event_type = message.get('eventType', '')
    payload = message.get('payload', {})
    data = payload.get('data', {}) if isinstance(payload, dict) else {}
    if event_type == 'auth.user.registered':
        account = payload.get('account', {})
        return {
            'channel': 'email',
            'recipient': account.get('email', 'ops@example.com'),
            'subject': f"Welcome {account.get('name', 'user')}",
            'message': 'Your Agency Assist workspace account is ready to use.',
            'category': 'auth',
        }
    if event_type == 'marketing.hot_lead.raised':
        return {
            'channel': 'email',
            'recipient': data.get('ownerEmail', 'sales@gmail.com'),
            'subject': f"Hot lead ready: {payload.get('name', 'lead')}",
            'message': json.dumps({'score': payload.get('score'), 'priority': data.get('priority'), 'recommendedAction': data.get('recommendedAction')}),
            'category': 'sales',
        }
    if event_type == 'marketing.lead.unsubscribed':
        return {
            'channel': 'email',
            'recipient': 'marketing-ops@gmail.com',
            'subject': f"Lead unsubscribed: {payload.get('name', 'lead')}",
            'message': json.dumps({'leadId': payload.get('id'), 'email': data.get('email'), 'sourceType': data.get('sourceType')}),
            'category': 'compliance',
        }
    if event_type == 'marketing.campaign.launch':
        return {
            'channel': 'email',
            'recipient': data.get('ownerEmail', 'marketing@gmail.com'),
            'subject': f"Campaign launched: {payload.get('name', 'campaign')}",
            'message': json.dumps({'campaignId': payload.get('id'), 'plannedRecipients': data.get('plannedRecipients'), 'subject': data.get('subject')}),
            'category': 'campaign',
        }
    return {
        'channel': 'email',
        'recipient': 'ops@example.com',
        'subject': f"{event_type} received",
        'message': json.dumps(payload),
        'category': event_type.split('.', 1)[0] if '.' in event_type else 'general',
    }


def handle_kafka_event(message: dict[str, Any]) -> None:
    notification = event_to_notification(message)
    if not notification:
        return
    create_notification(
        notification['channel'],
        notification['recipient'],
        notification['subject'],
        notification['message'],
        notification['category'],
        source_event_id=message.get('eventId'),
    )


@app.on_event('startup')
async def startup_event():
    init_db()
    app.state.kafka_consumer = KafkaEventConsumer(SERVICE_NAME, handle_kafka_event)
    app.state.kafka_consumer.start()


@app.on_event('shutdown')
def shutdown_event():
    consumer = getattr(app.state, 'kafka_consumer', None)
    if consumer:
        consumer.stop()


@app.get('/health')
async def health():
    return {'service': SERVICE_NAME, 'status': 'ok', 'port': PORT, 'redis': {'enabled': redis_enabled(), 'healthy': await redis_ping() if redis_enabled() else False}}


@app.get('/metrics')
def metrics():
    return PlainTextResponse(generate_latest().decode('utf-8'), media_type=CONTENT_TYPE_LATEST)


@app.post('/notifications/send')
async def send_notification(body: NotificationIn):
    await delete_prefix(cache_key('notifications'))
    await delete_prefix(cache_key('notifications'))
    return create_notification(body.channel, body.recipient, body.subject, body.message, body.category)


@app.get('/notifications')
async def list_notifications():
    with db() as conn:
        rows = conn.execute('SELECT * FROM notifications ORDER BY created_at DESC').fetchall()
    return [dict(row) for row in rows]


@app.on_event('shutdown')
async def shutdown_event():
    await close_redis()
