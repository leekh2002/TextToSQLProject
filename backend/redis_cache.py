import json
import os
import time
from typing import Any

import redis

_memory_cache: dict[str, tuple[float, Any]] = {}


def _get_client():
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        client = redis.Redis.from_url(url)
        client.ping()
        return client
    except Exception:
        return None

def get_cache(key):
    client = _get_client()
    if client is not None:
        val = client.get(key)
        if val:
            return json.loads(val)
        return None

    now = time.time()
    item = _memory_cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < now:
        _memory_cache.pop(key, None)
        return None
    return value

def set_cache(key, value):
    client = _get_client()
    if client is not None:
        client.setex(key, 300, json.dumps(value))  # 5분 캐싱
        return

    _memory_cache[key] = (time.time() + 300, value)
