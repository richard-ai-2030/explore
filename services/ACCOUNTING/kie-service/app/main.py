import json
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from .redis_cache import cache_key, close as close_redis, enabled as redis_enabled, get_json, ping as redis_ping, set_json

SERVICE_NAME = "kie-service"
PORT = int(os.getenv('PORT', '7003'))

app = FastAPI(title=SERVICE_NAME)
REQUESTS = PromCounter('app_http_requests_total', 'Total HTTP requests', ['service', 'method', 'path', 'status'])
LATENCY = Histogram('app_http_request_duration_seconds', 'Request latency', ['service', 'method', 'path'])

class RecordIn(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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

class ExtractIn(BaseModel):
    text: str

@app.post('/extract')
async def extract(body: ExtractIn):
    key = cache_key('extract', body.text[:200])
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    tokens = [token.strip('.,:;!?()[]{}').lower() for token in body.text.split()]
    tokens = [token for token in tokens if token]
    counts = Counter(tokens)
    keywords = [word for word, _ in counts.most_common(8)]
    classification = 'recruitment' if any(word in keywords for word in ['candidate', 'role', 'interview']) else 'sales' if any(word in keywords for word in ['deal', 'lead', 'quote']) else 'operations'
    payload = {
        'keywords': keywords,
        'entities': [{'value': word, 'weight': count} for word, count in counts.most_common(5)],
        'classification': classification,
        'summary': ' '.join(body.text.split()[:30]),
    }
    await set_json(key, payload)
    return {**payload, '_cache': 'miss'}


@app.on_event('shutdown')
async def shutdown_event():
    await close_redis()
