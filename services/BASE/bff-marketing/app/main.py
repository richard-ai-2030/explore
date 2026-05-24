import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest

from .redis_cache import cache_key, close as close_redis, delete_prefix, enabled as redis_enabled, get_json, ping as redis_ping, set_json

SERVICE_NAME = "bff-marketing"
PORT = int(os.getenv('PORT', '7010'))

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


SERVICE_URLS = {
    'leads-acquisition': os.getenv('LEADS_ACQUISITION_SERVICE_URL', 'http://leads-acquisition-service:7101'),
    'campaign': os.getenv('CAMPAIGN_SERVICE_URL', 'http://campaign-service:7102'),
    'scoring': os.getenv('SCORING_SERVICE_URL', 'http://scoring-service:7103'),
    'tracking': os.getenv('TRACKING_SERVICE_URL', 'http://tracking-service:7104'),
    'hot-lead': os.getenv('HOT_LEAD_SERVICE_URL', 'http://hot-lead-service:7111'),
    'analytics': os.getenv('ANALYTICS_SERVICE_URL', 'http://analytics-service:7002'),
    'notification': os.getenv('NOTIFICATION_SERVICE_URL', 'http://notification-service:7001'),
}
SUMMARY_PATHS = {
    'leads-acquisition': '/captures/summary',
    'campaign': '/campaigns/summary',
    'scoring': '/scores/summary',
    'tracking': '/events/summary',
    'hot-lead': '/hot-leads/summary',
}
ANALYTICS_URL = SERVICE_URLS['analytics']
NOTIFICATION_URL = SERVICE_URLS['notification']


def forward_headers(request: Request) -> dict[str, str]:
    allowed = ['authorization', 'x-auth-user-id', 'x-auth-user-email', 'x-auth-user-name', 'x-auth-scopes', 'content-type', 'x-correlation-id']
    return {k: v for k, v in request.headers.items() if k.lower() in allowed}


async def require_identity(request: Request):
    if request.headers.get('x-auth-user-id') or request.headers.get('authorization'):
        return
    raise HTTPException(401, 'Authentication required')


async def emit_event(event: str, payload: dict[str, Any]):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{ANALYTICS_URL}/events", json={'domain': 'marketing', 'source': SERVICE_NAME, 'event': event, 'payload': payload})
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.request(request.method, url, headers=forward_headers(request), params=request.query_params, json=body)
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
            analytics = (await client.get(f"{ANALYTICS_URL}/dashboards/marketing")).json()
        except Exception as exc:
            analytics = {'error': str(exc)}
    payload = {'domain': 'marketing', 'cards': cards, 'analytics': analytics}
    await set_json(dashboard_key, payload)
    await emit_event('dashboard_viewed', {'cards': len(cards), 'cache': 'miss'})
    return {**payload, '_cache': 'miss'}


@app.post('/workflows/lead-engagement')
async def lead_engagement(request: Request):
    await require_identity(request)
    body = await request.json()
    lead_payload = body.get('lead', body)
    lead_payload.setdefault('sourceType', 'inbound-form')
    lead_payload.setdefault('channel', 'web')
    lead_payload.setdefault('consent', True)
    event_type = body.get('tracking', {}).get('eventType') or ('form_submitted' if lead_payload.get('sourceType') == 'inbound-form' else 'website_browsed')
    async with httpx.AsyncClient(timeout=8.0) as client:
        lead = (await client.post(SERVICE_URLS['leads-acquisition'] + '/captures', json={'payload': lead_payload}, headers=forward_headers(request))).json()
        tracking_payload = {
            **body.get('tracking', {}),
            'leadId': lead.get('id'),
            'campaignId': body.get('campaignId'),
            'eventType': event_type,
            'landingPage': lead_payload.get('landingPage'),
            'utm': lead_payload.get('utm', {}),
        }
        tracking = (await client.post(SERVICE_URLS['tracking'] + '/events', json={'payload': tracking_payload}, headers=forward_headers(request))).json()
        score_payload = {
            **lead_payload,
            'leadId': lead.get('id'),
            'campaignId': body.get('campaignId'),
            'formSubmits': 1 if event_type == 'form_submitted' else 0,
            'opens': int(body.get('engagement', {}).get('opens', 0)),
            'clicks': int(body.get('engagement', {}).get('clicks', 0)),
            'visits': int(body.get('engagement', {}).get('visits', 1 if event_type == 'website_browsed' else 0)),
            'replies': int(body.get('engagement', {}).get('replies', 0)),
            'unsubscribes': int(body.get('engagement', {}).get('unsubscribes', 1 if event_type == 'unsubscribe_requested' else 0)),
        }
        score = (await client.post(SERVICE_URLS['scoring'] + '/scores', json={'payload': score_payload}, headers=forward_headers(request))).json()
        hot_lead = None
        if int(score.get('score', 0)) >= 70:
            hot_payload = {
                **lead_payload,
                'leadId': lead.get('id'),
                'score': score.get('score'),
                'pricingVisits': int(body.get('engagement', {}).get('pricingVisits', 0)),
                'formSubmits': score_payload['formSubmits'],
                'replies': score_payload['replies'],
                'expectedDeal': float(body.get('expectedDeal', 0) or 0),
            }
            hot_lead = (await client.post(SERVICE_URLS['hot-lead'] + '/hot-leads', json={'payload': hot_payload}, headers=forward_headers(request))).json()
            if hot_lead.get('state') == 'sales-ready':
                await invalidate_domain_cache()
    await notify(
                    lead_payload.get('ownerEmail', 'sales@gmail.com'),
                    f"Hot lead ready: {lead.get('name')}",
                    f"Lead {lead.get('id')} scored {score.get('score')} and needs follow-up.",
                    'sales',
                )
    result = {'lead': lead, 'tracking': tracking, 'score': score, 'hotLead': hot_lead}
    await emit_event('marketing.bff.lead_engagement_completed', {'leadId': lead.get('id'), 'score': score.get('score')})
    return result




@app.post('/workflow/lead-to-order')
async def legacy_lead_to_order(request: Request):
    return await lead_engagement(request)

@app.post('/campaigns/{campaign_id}/launch')
async def launch_campaign(campaign_id: str, request: Request):
    await require_identity(request)
    async with httpx.AsyncClient(timeout=8.0) as client:
        campaign = (await client.post(SERVICE_URLS['campaign'] + f'/campaigns/{campaign_id}/actions/launch', headers=forward_headers(request))).json()
    owner_email = campaign.get('data', {}).get('ownerEmail', request.headers.get('x-auth-user-email', 'marketing@gmail.com'))
    await notify(owner_email, f"Campaign launched: {campaign.get('name')}", f"Campaign {campaign_id} is now live.", 'campaign')
    await emit_event('marketing.bff.campaign_launched', {'campaignId': campaign_id})
    return campaign


from strawberry.fastapi import GraphQLRouter
from .graphql_schema import schema


async def get_graphql_context(request: Request, response=None):
    return {"request": request}


graphql_app = GraphQLRouter(schema, context_getter=get_graphql_context)
app.include_router(graphql_app, prefix="/graphql")

# Promote GraphQL routes to the front so they match before the catch-all proxy
graphql_paths = {"/graphql", "/graphql/"}
for i, r in enumerate(app.router.routes):
    if hasattr(r, "path") and r.path in graphql_paths:
        app.router.routes.insert(0, app.router.routes.pop(i))


@app.api_route('/{service_key}', methods=['GET', 'POST'])
@app.api_route('/{service_key}/{path:path}', methods=['GET', 'POST'])
async def proxy(service_key: str, path: str = "", request: Request = None):
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
