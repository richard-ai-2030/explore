import json
import os
from typing import Any

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover
    redis = None

REDIS_URL = os.getenv("REDIS_URL", "redis://172.19.0.6:6379/0")
REDIS_PREFIX = os.getenv("REDIS_PREFIX", "service")
DEFAULT_CACHE_TTL_SECONDS = int(os.getenv("DEFAULT_CACHE_TTL_SECONDS", "60"))

_client = None

def enabled() -> bool:
    return redis is not None

def get_client():
    global _client
    if redis is None:
        return None
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client

def cache_key(*parts: str) -> str:
    normalized = [str(part).strip("/").replace("/", ":") for part in parts if part is not None and str(part) != ""]
    return ":".join([REDIS_PREFIX, *normalized])

async def get_json(key: str) -> Any | None:
    client = get_client()
    if client is None:
        return None
    try:
        value = await client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None

async def set_json(key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    client = get_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value), ex=max(1, ttl_seconds))
    except Exception:
        return

async def delete_prefix(prefix: str) -> None:
    client = get_client()
    if client is None:
        return
    try:
        cursor = 0
        pattern = f"{prefix}*"
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        return

async def ping() -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:
        return False

async def close() -> None:
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    except Exception:
        pass
    _client = None
