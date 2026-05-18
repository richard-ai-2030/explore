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
from .redis_cache import (
  cache_key, close as close_redis, delete_prefix,
  enabled as redis_enabled, get_json, ping as redis_ping, set_json
)

SERVICE_NAME = "auth-service"
PORT = int(os.getenv('PORT', '7000'))
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

import base64
import hashlib
import hmac
import jwt

JWT_SECRET = os.getenv('JWT_SECRET', 'v3-jwt-4f7c2a9e1b6d8f0c-secure-rotated-2026-04')
JWT_ISSUER = 'Richard-AI-explore'
VERIFY_CACHE_TTL_SECONDS = int(os.getenv('VERIFY_CACHE_TTL_SECONDS', '300'))
DEFAULT_ROLE = os.getenv('DEFAULT_ROLE', 'marketing').strip() or 'marketing'

class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    roles: list[str] = Field(default_factory=lambda: [DEFAULT_ROLE])

class LoginIn(BaseModel):
    email: str
    password: str

def hash_password(password: str, salt: str | None = None) -> str:
    salt_bytes = os.urandom(16) if salt is None else base64.b64decode(salt)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt_bytes, 120000)
    return f"{base64.b64encode(salt_bytes).decode()}:{base64.b64encode(digest).decode()}"

def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(':', 1)
    candidate = hash_password(password, salt).split(':', 1)[1]
    return hmac.compare_digest(candidate, expected)

def make_token(account: dict[str, Any]) -> str:
    payload = {
        'sub': account['id'],
        'email': account['email'],
        'name': account['name'],
        'roles': account['roles'],
        'scopes': account['roles'],
        'iss': JWT_ISSUER,
        'exp': datetime.now(timezone.utc) + timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=['HS256'], issuer=JWT_ISSUER)

def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              roles TEXT NOT NULL,
              created_at TEXT NOT NULL
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

def account_by_email(email: str):
    with db() as conn:
        row = conn.execute('SELECT * FROM accounts WHERE lower(email) = lower(%s)', (email,)).fetchone()
    return dict(row) if row else None

def auth_context(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get('authorization', '')
    if not auth_header.lower().startswith('bearer '):
        raise HTTPException(401, 'Missing bearer token')
    token = auth_header.split(' ', 1)[1]
    try:
        return decode_token(token)
    except Exception as exc:
        raise HTTPException(401, f'Invalid token: {exc}')

@app.post('/register')
async def register(body: RegisterIn, request: Request):
    if account_by_email(body.email):
        raise HTTPException(409, 'Account already exists')
    account = {
        'id': str(uuid.uuid4()),
        'name': body.name,
        'email': body.email.lower(),
        'roles': body.roles or [DEFAULT_ROLE],
    }
    password_hash = hash_password(body.password)
    now = now_iso()
    with db() as conn:
        conn.execute(
            'INSERT INTO accounts (id, name, email, password_hash, roles, created_at) VALUES (%s, %s, %s, %s, %s, %s)',
            (account['id'], account['name'], account['email'], password_hash, json.dumps(account['roles']), now),
        )
        enqueue_outbox_event(
            conn,
            SERVICE_NAME,
            'auth.user.registered',
            account['id'],
            {'account': account, 'createdAt': now},
            request_headers=dict(request.headers),
        )
        conn.commit()
    if redis_enabled():
      key = cache_key("register", account['email'])
      await set_json(key, {"status": "created"})
      print("REDIS WRITE:", redis_enabled(), key)
    token = make_token(account)
    return {'token': token, 'account': account}

@app.post('/login')
def login(body: LoginIn, request: Request):
    account = account_by_email(body.email)
    if not account or not verify_password(body.password, account['password_hash']):
        raise HTTPException(401, 'Invalid credentials')
    normalized = {
        'id': account['id'],
        'email': account['email'],
        'name': account['name'],
        'roles': json.loads(account['roles']),
    }
    token = make_token(normalized)
    with db() as conn:
        enqueue_outbox_event(
            conn,
            SERVICE_NAME,
            'auth.user.logged_in',
            normalized['id'],
            {'user': normalized, 'loggedInAt': now_iso()},
            request_headers=dict(request.headers),
        )
        conn.commit()
    return {'token': token, 'user': normalized}

@app.get('/verify')
async def verify(request: Request):
    auth_header = request.headers.get('authorization', '')
    cache_token = auth_header.removeprefix('Bearer ').strip()
    if cache_token:
        cached = await get_json(cache_key('verify', cache_token))
        if cached is not None:
            return {**cached, '_cache': 'hit'}
    claims = auth_context(request)
    return {'id': claims['sub'], 'email': claims['email'], 'name': claims.get('name'), 'roles': claims.get('roles', []), 'scopes': claims.get('scopes', [])}

@app.get('/ingress/auth')
def ingress_auth(request: Request):
    claims = auth_context(request)
    response = JSONResponse({'status': 'ok', 'subject': claims['sub']})
    response.headers['X-Auth-User-Id'] = claims['sub']
    response.headers['X-Auth-User-Email'] = claims['email']
    response.headers['X-Auth-User-Name'] = claims.get('name', '')
    response.headers['X-Auth-Scopes'] = ','.join(claims.get('scopes', []))
    response.headers['X-Auth-Identity-Source'] = 'jwt'
    return response


@app.on_event('shutdown')
async def shutdown_event():
    await close_redis()
