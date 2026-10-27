"""In-memory sliding-window rate limiting for authentication endpoints."""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic

_LIMITS = {
    ("POST", "/api/v1/auth/login"): (5, 60),
    ("POST", "/api/v1/auth/token"): (5, 60),
    ("POST", "/api/v1/auth/register"): (5, 60),
}

_attempts: dict[tuple[str, str, str], deque[float]] = {}
_lock = Lock()


def check_rate_limit(
    method: str,
    path: str,
    client_ip: str,
) -> tuple[bool, int]:
    """Return (is_limited, retry_after_seconds)."""
    policy = _LIMITS.get((method.upper(), path))
    if policy is None:
        return False, 0

    max_requests, window_seconds = policy
    now = monotonic()
    key = (method.upper(), path, client_ip)

    with _lock:
        # Occasionally remove stale client keys to bound memory usage.
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


def reset_rate_limits() -> None:
    """Clear counters for isolated automated tests."""
    with _lock:
        _attempts.clear()