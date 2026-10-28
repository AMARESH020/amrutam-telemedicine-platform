import asyncio

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app import routes, rate_limit


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
def test_account_failures_trigger_progressive_cooldown_and_reset(monkeypatch):
    monkeypatch.setattr(rate_limit, '_sync_redis', None)
    monkeypatch.setattr(rate_limit.settings, "app_env", "test")
    clock = [1000.0]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: clock[0])

    email = "progressive-account@example.com"
    rate_limit.clear_account_auth_failures(email)

    for _ in range(5):
        assert rate_limit.record_account_auth_failure(email) == 0

    assert rate_limit.record_account_auth_failure(email) == 1
    assert rate_limit.check_account_cooldown(email) == 1

    # Simulate the first cooldown expiring without actually sleeping.
    clock[0] += 1.1
    assert rate_limit.check_account_cooldown(email) == 0
    assert rate_limit.record_account_auth_failure(email) == 2
    assert rate_limit.check_account_cooldown(email) == 2

    rate_limit.clear_account_auth_failures(email)
    assert rate_limit.check_account_cooldown(email) == 0
    assert rate_limit.record_account_auth_failure(email) == 0


def test_account_limiter_requires_redis_in_production(monkeypatch):
    monkeypatch.setattr(rate_limit, '_sync_redis', None)
    monkeypatch.setattr(rate_limit.settings, "app_env", "production")

    with pytest.raises(rate_limit.RateLimitBackendUnavailable):
        rate_limit.check_account_cooldown("production-account@example.com")


def test_account_cooldown_is_enforced_for_both_login_endpoints(
    client, monkeypatch
):
    monkeypatch.setattr(
        routes, "check_account_cooldown", lambda email: 17
    )

    json_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "cooldown-check@example.com",
            "password": "WrongPassword123!",
        },
    )
    form_login = client.post(
        "/api/v1/auth/token",
        data={
            "username": "cooldown-check@example.com",
            "password": "WrongPassword123!",
        },
    )

    for response in (json_login, form_login):
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "17"

def test_valid_login_succeeds_during_account_cooldown(client, monkeypatch):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "cooldown-valid-user@example.com",
            "full_name": "Cooldown Test User",
            "password": "correct-horse-battery-staple",
            "role": "patient",
        },
    )
    assert registered.status_code == 201, registered.text

    monkeypatch.setattr(
        routes, "check_account_cooldown", lambda email: 17
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "cooldown-valid-user@example.com",
            "password": "correct-horse-battery-staple",
        },
    )

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()

class FakeSyncRedis:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.deleted = ()

    def eval(self, script, numkeys, *keys_and_args):
        if self.fail:
            raise RedisConnectionError("simulated Redis outage")

        self.calls.append((script, numkeys, keys_and_args))
        if "PTTL" in script:
            return 1100

        return [6, 1]

    def delete(self, *keys):
        self.deleted = tuple(keys)
        return len(keys)


def test_account_limiter_redis_backend_hashes_keys_and_clears_state(monkeypatch):
    fake = FakeSyncRedis()
    monkeypatch.setattr(rate_limit, "_sync_redis", fake)
    monkeypatch.setattr(rate_limit.settings, "app_env", "production")

    email = "redis-account@example.com"

    assert rate_limit.record_account_auth_failure(email) == 1
    assert fake.calls[-1][1] == 2
    assert email not in repr(fake.calls[-1][2])

    assert rate_limit.check_account_cooldown(email) == 2
    assert email not in repr(fake.calls[-1][2])

    rate_limit.clear_account_auth_failures(email)
    assert len(fake.deleted) == 2
    assert email not in repr(fake.deleted)


def test_account_limiter_redis_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(
        rate_limit, "_sync_redis", FakeSyncRedis(fail=True)
    )
    monkeypatch.setattr(rate_limit.settings, "app_env", "production")

    with pytest.raises(rate_limit.RateLimitBackendUnavailable):
        rate_limit.check_account_cooldown("redis-outage@example.com")
