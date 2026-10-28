"""Shared Redis sliding-window rate limiting with a local fallback."""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings


_LIMITS = {
    ("POST", "/api/v1/auth/login"): (5, 60),
    ("POST", "/api/v1/auth/token"): (5, 60),
    ("POST", "/api/v1/auth/register"): (5, 60),
}

_attempts: dict[tuple[str, str, str], deque[float]] = {}
_lock = Lock()


class RateLimitBackendUnavailable(Exception):
    """Raised when the configured shared limiter cannot be reached."""


# Redis uses an atomic Lua script so concurrent API replicas share one limit.
_SLIDING_WINDOW_SCRIPT = """
local time = redis.call('TIME')
local now_ms = (tonumber(time[1]) * 1000)
    + math.floor(tonumber(time[2]) / 1000)

local window_ms = tonumber(ARGV[1])
local max_requests = tonumber(ARGV[2])
local member = ARGV[3]

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])

if count >= max_requests then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local wait_ms = tonumber(oldest[2]) + window_ms - now_ms
    local retry_after = math.max(1, math.ceil(wait_ms / 1000))
    redis.call('PEXPIRE', KEYS[1], window_ms)
    return {1, retry_after}
end

redis.call('ZADD', KEYS[1], now_ms, member)
redis.call('PEXPIRE', KEYS[1], window_ms)
return {0, 0}
"""


_redis = (
    Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        health_check_interval=30,
    )
    if settings.redis_url
    else None
)


def _check_in_memory(
    method: str,
    path: str,
    client_ip: str,
    max_requests: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Development/test fallback; counters are local to this process."""
    now = monotonic()
    key = (method, path, client_ip)

    with _lock:
        if len(_attempts) >= 1024 and key not in _attempts:
            stale_before = now - window_seconds
            stale_keys = [
                existing_key
                for existing_key, timestamps in _attempts.items()
                if not timestamps or timestamps[-1] <= stale_before
            ]
            for stale_key in stale_keys:
                _attempts.pop(stale_key, None)

        timestamps = _attempts.setdefault(key, deque())
        while timestamps and timestamps[0] <= now - window_seconds:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            retry_after = max(
                1,
                ceil(window_seconds - (now - timestamps[0])),
            )
            return True, retry_after

        timestamps.append(now)
        return False, 0


async def check_rate_limit(
    method: str,
    path: str,
    client_ip: str,
) -> tuple[bool, int]:
    """Return (is_limited, retry_after_seconds)."""
    normalized_method = method.upper()
    policy = _LIMITS.get((normalized_method, path))
    if policy is None:
        return False, 0

    max_requests, window_seconds = policy

    if _redis is None:
        if settings.app_env.lower() in {"production", "prod"}:
            raise RateLimitBackendUnavailable(
                "REDIS_URL must be configured when APP_ENV is production."
            )
        return _check_in_memory(
            normalized_method,
            path,
            client_ip,
            max_requests,
            window_seconds,
        )

    key = f"amrutam:rate-limit:{normalized_method}:{path}:{client_ip}"

    try:
        result = await _redis.eval(
            _SLIDING_WINDOW_SCRIPT,
            1,
            key,
            window_seconds * 1000,
            max_requests,
            uuid4().hex,
        )
    except RedisError as exc:
        # Do not silently bypass rate limiting when shared storage is configured.
        raise RateLimitBackendUnavailable from exc

    return bool(int(result[0])), int(result[1])


def reset_rate_limits() -> None:
    """Clear in-memory counters for isolated automated tests."""
    with _lock:
        _attempts.clear()
