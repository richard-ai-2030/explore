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

from .redis_cache import cache_key, close as close_redis, delete_prefix, enabled as redis_enabled, get_json, ping as redis_ping, set_json

SERVICE_NAME = "bff-talents"
PORT = int(os.getenv('PORT', '7012'))

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

import httpx

DOMAIN = "talents"
SERVICE_URLS = {
    "recruitment": "http://recruitment-service:7141",
    "employees": "http://employees-service:7142",
    "attendance": "http://attendance-service:7143",
    "motivation": "http://motivation-service:7144"
}
SUMMARY_PATHS = {
    "recruitment": "/candidates/summary",
    "employees": "/employees/summary",
    "attendance": "/records/summary",
    "motivation": "/pulses/summary"
}
ANALYTICS_URL = os.getenv('ANALYTICS_SERVICE_URL', 'http://analytics-service:7002')
NOTIFICATION_URL = os.getenv('NOTIFICATION_SERVICE_URL', 'http://notification-service:7001')
WORKFLOW_PATH = "/workflow/hire-to-engage"
RETENTION_PATH = "/workflow/talent-retention-loop"

async def require_identity(request: Request):
    if request.headers.get('x-auth-user-id') or request.headers.get('authorization'):
        return
    raise HTTPException(401, 'Authentication required')

async def emit_event(event: str, payload: dict[str, Any]):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{ANALYTICS_URL}/events", json={'domain': DOMAIN, 'source': f'bff-{DOMAIN}', 'event': event, 'payload': payload})
        except Exception:
            pass

async def notify(recipient: str, subject: str, message: str, category: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{NOTIFICATION_URL}/notifications/send", json={'recipient': recipient, 'subject': subject, 'message': message, 'category': category})
        except Exception:
            pass

async def cacheable_summary(service_key: str, path: str) -> dict[str, Any]:
    key = cache_key('summary', service_key)
    cached = await get_json(key)
    if cached is not None:
        return {**cached, '_cache': 'hit'}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(SERVICE_URLS[service_key] + path)
        payload = response.json()
    await set_json(key, payload)
    return {**payload, '_cache': 'miss'}

async def invalidate_domain_cache() -> None:
    await delete_prefix(cache_key('dashboard'))
    await delete_prefix(cache_key('summary'))

async def proxy_request(service_key: str, path: str, request: Request, body: Any = None):
    if service_key not in SERVICE_URLS:
        raise HTTPException(404, 'Unknown service route')
    url = SERVICE_URLS[service_key] + ('/' + path if path else '')
    headers = {k: v for k, v in request.headers.items() if k.lower() in ['authorization', 'x-auth-user-id', 'x-auth-user-email', 'x-auth-user-name', 'x-auth-scopes', 'content-type']}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.request(request.method, url, headers=headers, params=request.query_params, json=body)
    try:
        payload = response.json() if response.content else {}
    except Exception:
        payload = {'raw': response.text}
    return JSONResponse(payload, status_code=response.status_code)

@app.get('/dashboard')
async def dashboard(request: Request):
    await require_identity(request)
    dashboard_key = cache_key('dashboard')
    cached_dashboard = await get_json(dashboard_key)
    if cached_dashboard is not None:
        await emit_event('dashboard_viewed', {'cards': len(cached_dashboard.get('cards', [])), 'cache': 'hit'})
        return {**cached_dashboard, '_cache': 'hit'}
    cards = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for service_key, path in SUMMARY_PATHS.items():
            try:
                cards.append({'service': service_key, 'summary': await cacheable_summary(service_key, path)})
            except Exception as exc:
                cards.append({'service': service_key, 'error': str(exc)})
        try:
            analytics = (await client.get(f"{ANALYTICS_URL}/dashboards/talents")).json()
        except Exception as exc:
            analytics = {'error': str(exc)}
    payload = {'domain': 'talents', 'cards': cards, 'analytics': analytics}
    await set_json(dashboard_key, payload)
    await emit_event('dashboard_viewed', {'cards': len(cards), 'cache': 'miss'})
    return {**payload, '_cache': 'miss'}

@app.post(RETENTION_PATH)
async def talent_retention_loop(request: Request):
    await require_identity(request)
    body = await request.json()
    user_email = request.headers.get('x-auth-user-email', 'ops@gmail.com')
    async with httpx.AsyncClient(timeout=8.0) as client:
        employee = (await client.post(SERVICE_URLS['employees'] + '/employees', json={'payload': body.get('employee', {'employeeName': 'Retention Candidate', 'department': 'Operations', 'level': 'L3', 'salary': 72000})})).json()
        attendance = (await client.post(SERVICE_URLS['attendance'] + '/records', json={'payload': body.get('attendance', {'employeeId': employee.get('id'), 'hours': 7.5, 'lateMinutes': 4, 'workMode': 'hybrid'})})).json()
        pulse = (await client.post(SERVICE_URLS['motivation'] + '/pulses', json={'payload': body.get('pulse', {'employeeId': employee.get('id'), 'mood': 61, 'recognition': 58, 'workload': 78})})).json()
        recruitment = (await client.post(SERVICE_URLS['recruitment'] + '/candidates', json={'payload': body.get('benchCandidate', {'candidateName': 'Bench Successor', 'fit': 76, 'availability': 82, 'role': 'Ops backup'})})).json()
    await invalidate_domain_cache()
    await notify(user_email, 'Talent retention loop updated', f"Employee {employee.get('id')} pulse {pulse.get('state')}", 'talent')
    await invalidate_domain_cache()
    await emit_event('workflow_completed', {'workflow': RETENTION_PATH, 'records': 4})
    return {'employee': employee, 'attendance': attendance, 'pulse': pulse, 'benchCandidate': recruitment}

@app.post(WORKFLOW_PATH)
async def workflow_handler(request: Request):
    await require_identity(request)
    body = await request.json()
    user_email = request.headers.get('x-auth-user-email', 'ops@gmail.com')
    async with httpx.AsyncClient(timeout=8.0) as client:
        if DOMAIN == 'marketing':
            lead = (await client.post(SERVICE_URLS['leads-acquisition'] + '/captures', json={'payload': body.get('lead', body)})).json()
            score = (await client.post(SERVICE_URLS['scoring'] + '/scores', json={'payload': body.get('lead', body)})).json()
            hot_lead = None
            if int(score.get('score', 0)) >= 80:
                hot_lead = (await client.post(SERVICE_URLS['hot-lead'] + '/hot-leads', json={'payload': {**body.get('lead', body), 'score': score.get('score'), 'expectedDeal': body.get('quotation', {}).get('amount', 12000)}})).json()
            quotation = (await client.post(SERVICE_URLS['quotation'] + '/quotations', json={'payload': body.get('quotation', {'items': [{'qty': 1, 'price': 12000}]})})).json()
            order = (await client.post(SERVICE_URLS['order'] + '/orders', json={'payload': body.get('order', {'quantity': 1, 'unitPrice': quotation.get('amount', 12000)})})).json()
            payment = (await client.post(SERVICE_URLS['payment'] + '/payments', json={'payload': {'amount': order.get('amount', quotation.get('amount', 0)), 'received': order.get('amount', quotation.get('amount', 0)), 'method': 'invoice'}})).json()
            await notify(user_email, 'Marketing workflow completed', f"Lead-to-order created payment {payment.get('id')}", 'marketing')
            result = {'lead': lead, 'score': score, 'hotLead': hot_lead, 'quotation': quotation, 'order': order, 'payment': payment}
        elif DOMAIN == 'production':
            supplier = (await client.post(SERVICE_URLS['supplier'] + '/suppliers', json={'payload': body.get('supplier', {'name': 'Preferred Supplier', 'reliability': 88, 'compliance': 91})})).json()
            procurement = (await client.post(SERVICE_URLS['procurement'] + '/procurements', json={'payload': body.get('procurement', {'amount': 4500, 'neededBy': '2026-04-15'})})).json()
            inventory = (await client.post(SERVICE_URLS['inventory'] + '/items', json={'payload': body.get('inventory', {'name': 'Batch A', 'onHand': 120, 'reserved': 20, 'reorderPoint': 15})})).json()
            quality = (await client.post(SERVICE_URLS['quality'] + '/inspections', json={'payload': body.get('quality', {'sampleSize': 25, 'defects': 1})})).json()
            logistics = (await client.post(SERVICE_URLS['logistics'] + '/shipments', json={'payload': body.get('logistics', {'etaDays': 4, 'delayRisk': 25})})).json()
            invoice = (await client.post(SERVICE_URLS['invoice'] + '/invoices', json={'payload': body.get('invoice', {'amount': procurement.get('amount', 4500), 'customer': supplier.get('name', 'supplier')})})).json()
            result = {'supplier': supplier, 'procurement': procurement, 'inventory': inventory, 'quality': quality, 'logistics': logistics, 'invoice': invoice}
        else:
            candidate = (await client.post(SERVICE_URLS['recruitment'] + '/candidates', json={'payload': body.get('candidate', {'candidateName': 'New Hire', 'fit': 84, 'availability': 78, 'role': 'Operations Specialist'})})).json()
            employee = (await client.post(SERVICE_URLS['employees'] + '/employees', json={'payload': body.get('employee', {'employeeName': candidate.get('name', 'New Hire'), 'department': 'Talent', 'level': 'L2', 'salary': 64000})})).json()
            attendance = (await client.post(SERVICE_URLS['attendance'] + '/records', json={'payload': body.get('attendance', {'employeeId': employee.get('id'), 'hours': 8, 'lateMinutes': 0})})).json()
            pulse = (await client.post(SERVICE_URLS['motivation'] + '/pulses', json={'payload': body.get('pulse', {'employeeId': employee.get('id'), 'mood': 82, 'recognition': 76, 'workload': 42})})).json()
            await notify(user_email, 'Talent workflow completed', f"Hire-to-engage created employee {employee.get('id')}", 'talent')
            payroll = {'service': 'payroll-service', 'status': 'not-linked-in-talents-bff', 'recommendedDomain': 'production'}
            result = {'candidate': candidate, 'employee': employee, 'attendance': attendance, 'pulse': pulse, 'payrollHint': payroll}
    await emit_event('workflow_completed', {'workflow': WORKFLOW_PATH})
    return result

@app.api_route('/{service_key}', methods=['GET', 'POST'])
@app.api_route('/{service_key}/{path:path}', methods=['GET', 'POST'])
async def proxy(service_key: str, path: str, request: Request = None):
    await require_identity(request)
    body = None
    if request.method != 'GET':
        body = await request.json()
    if request.method == 'GET' and path.endswith('/summary'):
        service_payload = await cacheable_summary(service_key, '/' + path)
        await emit_event('proxy_call', {'service': service_key, 'path': path, 'method': request.method, 'cache': service_payload.get('_cache', 'unknown')})
        return JSONResponse(service_payload)
    if request.method != 'GET':
        await invalidate_domain_cache()
    await emit_event('proxy_call', {'service': service_key, 'path': path, 'method': request.method})
    return await proxy_request(service_key, path, request, body)

@app.on_event('shutdown')
async def shutdown_event():
    await close_redis()
