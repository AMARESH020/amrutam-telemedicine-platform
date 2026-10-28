import asyncio

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app import rate_limit


class FakeRedis:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def eval(self, script, numkeys, key, window_ms, max_requests, member):
        if self.fail:
            raise RedisConnectionError("simulated Redis outage")
        self.calls += 1
        if self.calls > int(max_requests):
            return [1, 30]
        return [0, 0]


def test_redis_backend_enforces_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_redis", fake)

    async def exercise():
        for _ in range(5):
            assert await rate_limit.check_rate_limit(
                "POST", "/api/v1/auth/login", "test-client"
            ) == (False, 0)

        assert await rate_limit.check_rate_limit(
            "POST", "/api/v1/auth/login", "test-client"
        ) == (True, 30)

    asyncio.run(exercise())
    assert fake.calls == 6


def test_redis_failure_returns_503(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "_redis", FakeRedis(fail=True))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "redis-outage@example.com", "password": "NotARealPassword123!"},
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"] == (
        "Rate limiting service is temporarily unavailable."
    )

def test_production_without_redis_fails_closed(monkeypatch):
    monkeypatch.setattr(rate_limit, "_redis", None)
    monkeypatch.setattr(rate_limit.settings, "app_env", "production")

    async def exercise():
        with pytest.raises(rate_limit.RateLimitBackendUnavailable):
            await rate_limit.check_rate_limit(
                "POST", "/api/v1/auth/login", "test-client"
            )

    asyncio.run(exercise())
