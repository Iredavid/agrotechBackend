"""
app/geo_cache.py
-----------------
Tiny in-memory TTL cache keyed on rounded (lat, lon).

Rainfall climatology, admin state, and soil texture don't meaningfully
change between two farms 1-2km apart, or between two requests an hour
apart. Rounding the coordinates turns "every farmer's exact GPS pin"
into a much smaller set of cache keys, so repeat/nearby requests skip
the network call entirely.

Swap this for Redis in production (multi-worker deployments won't share
this dict across processes) -- the interface is intentionally tiny so
that's a drop-in change later.
"""
import time
from typing import Any, Callable, Awaitable

_store: dict[str, tuple[float, Any]] = {}


def _key(prefix: str, lat: float, lon: float, precision: int) -> str:
    return f"{prefix}:{round(lat, precision)}:{round(lon, precision)}"


async def cached(
    prefix: str,
    lat: float,
    lon: float,
    fetch: Callable[[], Awaitable[Any]],
    ttl_seconds: int,
    precision: int = 2,  # ~1.1km grid at the equator
) -> Any:
    key = _key(prefix, lat, lon, precision)
    now = time.monotonic()

    hit = _store.get(key)
    if hit is not None:
        expires_at, value = hit
        if now < expires_at:
            return value

    value = await fetch()
    _store[key] = (now + ttl_seconds, value)
    return value


def clear_cache() -> None:
    _store.clear()
