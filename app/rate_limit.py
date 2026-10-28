"""Shared Redis sliding-window rate limiting with a local fallback."""

from collections import deque
from hashlib import sha256
import hmac
from math import ceil
from threading import Lock
from time import monotonic
from uuid import uuid4

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings


_LIMITS = {
    ("POST", "/api/v1/auth/login"): (5, 60),
    ("POST", "/api/v1/auth/token"): (5, 60),
    ("POST", "/api/v1/auth/register"): (5, 60),
}

_attempts: dict[tuple[str, str, str], deque[float]] = {}
_account_failures: dict[str, tuple[int, float]] = {}
_account_cooldowns: dict[str, float] = {}
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


_sync_redis = (
    SyncRedis.from_url(
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



_ACCOUNT_FAILURE_WINDOW_SECONDS = 900
_ACCOUNT_COOLDOWN_AFTER_FAILURES = 6
_ACCOUNT_MAX_COOLDOWN_SECONDS = 30

_ACCOUNT_FAILURE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])

local delay = 0
local threshold = tonumber(ARGV[2])
if count >= threshold then
    local exponent = math.min(count - threshold, 5)
    delay = math.min(2 ^ exponent, tonumber(ARGV[3]))
    redis.call('SET', KEYS[2], tostring(delay), 'EX', delay)
end

return {count, delay}
"""

_ACCOUNT_COOLDOWN_SCRIPT = """
return redis.call('PTTL', KEYS[1])
"""

def _account_digest(email: str) -> str:
    normalized_email = email.strip().lower().encode("utf-8")
    secret = settings.jwt_secret.encode("utf-8")
    return hmac.new(secret, normalized_email, sha256).hexdigest()


def _account_keys(email: str) -> tuple[str, str]:
    digest = _account_digest(email)
    prefix = f"amrutam:auth-account:{digest}"
    return f"{prefix}:failures", f"{prefix}:cooldown"


def check_account_cooldown(email: str) -> int:
    """Return the remaining account cooldown in seconds, or zero."""
    failure_key, cooldown_key = _account_keys(email)

    if _sync_redis is not None:
        try:
            remaining_ms = int(
                _sync_redis.eval(_ACCOUNT_COOLDOWN_SCRIPT, 1, cooldown_key)
            )
        except RedisError as exc:
            raise RateLimitBackendUnavailable from exc
        return max(0, ceil(remaining_ms / 1000)) if remaining_ms > 0 else 0

    if settings.app_env.lower() in {"production", "prod"}:
        raise RateLimitBackendUnavailable(
            "REDIS_URL must be configured when APP_ENV is production."
        )

    now = monotonic()
    digest = _account_digest(email)
    with _lock:
        expiry = _account_cooldowns.get(digest, 0.0)
        if expiry <= now:
            _account_cooldowns.pop(digest, None)
            return 0
        return max(1, ceil(expiry - now))


def record_account_auth_failure(email: str) -> int:
    """Record a failed factor and return any newly applied cooldown."""
    failure_key, cooldown_key = _account_keys(email)

    if _sync_redis is not None:
        try:
            result = _sync_redis.eval(
                _ACCOUNT_FAILURE_SCRIPT,
                2,
                failure_key,
                cooldown_key,
                _ACCOUNT_FAILURE_WINDOW_SECONDS,
                _ACCOUNT_COOLDOWN_AFTER_FAILURES,
                _ACCOUNT_MAX_COOLDOWN_SECONDS,
            )
        except RedisError as exc:
            raise RateLimitBackendUnavailable from exc
        return int(result[1])

    if settings.app_env.lower() in {"production", "prod"}:
        raise RateLimitBackendUnavailable(
            "REDIS_URL must be configured when APP_ENV is production."
        )

    digest = _account_digest(email)
    now = monotonic()

    with _lock:
        previous = _account_failures.get(digest)
        if previous is None or previous[1] <= now:
            count = 1
        else:
            count = previous[0] + 1

        _account_failures[digest] = (
            count,
            now + _ACCOUNT_FAILURE_WINDOW_SECONDS,
        )

        delay = 0
        if count >= _ACCOUNT_COOLDOWN_AFTER_FAILURES:
            exponent = min(count - _ACCOUNT_COOLDOWN_AFTER_FAILURES, 5)
            delay = min(2 ** exponent, _ACCOUNT_MAX_COOLDOWN_SECONDS)
            _account_cooldowns[digest] = now + delay

        return delay


def clear_account_auth_failures(email: str) -> None:
    """Clear failure and cooldown state after successful authentication."""
    failure_key, cooldown_key = _account_keys(email)

    if _sync_redis is not None:
        try:
            _sync_redis.delete(failure_key, cooldown_key)
        except RedisError as exc:
            raise RateLimitBackendUnavailable from exc
        return

    if settings.app_env.lower() in {"production", "prod"}:
        raise RateLimitBackendUnavailable(
            "REDIS_URL must be configured when APP_ENV is production."
        )

    digest = _account_digest(email)
    with _lock:
        _account_failures.pop(digest, None)
        _account_cooldowns.pop(digest, None)


def reset_rate_limits() -> None:
    """Clear in-memory counters for isolated automated tests."""
    with _lock:
        _attempts.clear()
        _account_failures.clear()
        _account_cooldowns.clear()
