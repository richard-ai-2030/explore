import httpx
import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info
from typing import Optional
from fastapi import Request

from .main import (
    SERVICE_URLS, SUMMARY_PATHS, ANALYTICS_URL,
    forward_headers, emit_event, notify, cacheable_summary,
    invalidate_domain_cache,
)
from .redis_cache import cache_key, get_json, set_json


async def _require_auth(info: Info):
    request: Request = info.context["request"]
    if not (request.headers.get("x-auth-user-id") or request.headers.get("authorization")):
        raise Exception("Authentication required")


@strawberry.input
class LeadEngagementInput:
    lead: JSON = strawberry.field(default_factory=dict)
    engagement: JSON = strawberry.field(default_factory=dict)
    tracking: JSON = strawberry.field(default_factory=dict)
    campaign_id: Optional[str] = None
    expected_deal: Optional[float] = None


@strawberry.type
class Query:
    @strawberry.field
    async def dashboard(self, info: Info) -> JSON:
        await _require_auth(info)
        request: Request = info.context["request"]
        dashboard_key = cache_key("dashboard")
        cached = await get_json(dashboard_key)
        if cached is not None:
            await emit_event("dashboard_viewed", {"cards": len(cached.get("cards", [])), "cache": "hit"})
            return {**cached, "_cache": "hit"}
        cards = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_key, path in SUMMARY_PATHS.items():
                try:
                    cards.append({"service": service_key, "summary": await cacheable_summary(service_key, path)})
                except Exception as exc:
                    cards.append({"service": service_key, "error": str(exc)})
            try:
                analytics = (await client.get(f"{ANALYTICS_URL}/dashboards/marketing")).json()
            except Exception as exc:
                analytics = {"error": str(exc)}
        payload = {"domain": "marketing", "cards": cards, "analytics": analytics}
        await set_json(dashboard_key, payload)
        await emit_event("dashboard_viewed", {"cards": len(cards), "cache": "miss"})
        return {**payload, "_cache": "miss"}

    @strawberry.field
    async def summary(self, service_key: str, info: Info) -> JSON:
        await _require_auth(info)
        if service_key not in SUMMARY_PATHS:
            raise Exception(f"Unknown service: {service_key}")
        result = await cacheable_summary(service_key, SUMMARY_PATHS[service_key])
        return result


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def lead_engagement(self, input: LeadEngagementInput, info: Info) -> JSON:
        await _require_auth(info)
        request: Request = info.context["request"]
        lead_payload = dict(input.lead) if input.lead else {}
        lead_payload.setdefault("sourceType", "inbound-form")
        lead_payload.setdefault("channel", "web")
        lead_payload.setdefault("consent", True)
        event_type = (input.tracking or {}).get("eventType")
        if not event_type:
            event_type = "form_submitted" if lead_payload.get("sourceType") == "inbound-form" else "website_browsed"
        async with httpx.AsyncClient(timeout=8.0) as client:
            lead = (await client.post(
                SERVICE_URLS["leads-acquisition"] + "/captures",
                json={"payload": lead_payload},
                headers=forward_headers(request),
            )).json()
            tracking_payload = {
                **(input.tracking or {}),
                "leadId": lead.get("id"),
                "campaignId": input.campaign_id,
                "eventType": event_type,
                "landingPage": lead_payload.get("landingPage"),
                "utm": lead_payload.get("utm", {}),
            }
            tracking = (await client.post(
                SERVICE_URLS["tracking"] + "/events",
                json={"payload": tracking_payload},
                headers=forward_headers(request),
            )).json()
            engagement = input.engagement or {}
            score_payload = {
                **lead_payload,
                "leadId": lead.get("id"),
                "campaignId": input.campaign_id,
                "formSubmits": 1 if event_type == "form_submitted" else 0,
                "opens": int(engagement.get("opens", 0)),
                "clicks": int(engagement.get("clicks", 0)),
                "visits": int(engagement.get("visits", 1 if event_type == "website_browsed" else 0)),
                "replies": int(engagement.get("replies", 0)),
                "unsubscribes": int(engagement.get("unsubscribes", 1 if event_type == "unsubscribe_requested" else 0)),
            }
            score = (await client.post(
                SERVICE_URLS["scoring"] + "/scores",
                json={"payload": score_payload},
                headers=forward_headers(request),
            )).json()
            hot_lead = None
            if int(score.get("score", 0)) >= 70:
                hot_payload = {
                    **lead_payload,
                    "leadId": lead.get("id"),
                    "score": score.get("score"),
                    "pricingVisits": int(engagement.get("pricingVisits", 0)),
                    "formSubmits": score_payload["formSubmits"],
                    "replies": score_payload["replies"],
                    "expectedDeal": float(input.expected_deal or 0),
                }
                hot_lead = (await client.post(
                    SERVICE_URLS["hot-lead"] + "/hot-leads",
                    json={"payload": hot_payload},
                    headers=forward_headers(request),
                )).json()
                if hot_lead.get("state") == "sales-ready":
                    await invalidate_domain_cache()
        await notify(
            lead_payload.get("ownerEmail", "sales@gmail.com"),
            f"Hot lead ready: {lead.get('name')}",
            f"Lead {lead.get('id')} scored {score.get('score')} and needs follow-up.",
            "sales",
        )
        result = {"lead": lead, "tracking": tracking, "score": score, "hotLead": hot_lead}
        await emit_event("marketing.bff.lead_engagement_completed", {"leadId": lead.get("id"), "score": score.get("score")})
        return result

    @strawberry.mutation
    async def launch_campaign(self, campaign_id: str, info: Info) -> JSON:
        await _require_auth(info)
        request: Request = info.context["request"]
        async with httpx.AsyncClient(timeout=8.0) as client:
            campaign = (await client.post(
                SERVICE_URLS["campaign"] + f"/campaigns/{campaign_id}/actions/launch",
                headers=forward_headers(request),
            )).json()
        owner_email = campaign.get("data", {}).get("ownerEmail", request.headers.get("x-auth-user-email", "marketing@gmail.com"))
        await notify(owner_email, f"Campaign launched: {campaign.get('name')}", f"Campaign {campaign_id} is now live.", "campaign")
        await emit_event("marketing.bff.campaign_launched", {"campaignId": campaign_id})
        return campaign


schema = strawberry.Schema(query=Query, mutation=Mutation)
