"""Opt-in API integration test for the real Redis account limiter."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import rate_limit as limiter
from app.db import Base, engine
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION_TESTS") != "1",
    reason="Requires the dedicated Redis integration job.",
)


def test_account_cooldown_through_api_with_real_redis():
    if limiter._sync_redis is None or limiter._redis is None:
        pytest.fail("Both Redis clients must be configured for this test.")

    if engine.url.get_backend_name() != "sqlite":
        pytest.fail("This integration test must use its dedicated SQLite database.")

    db_path = Path(engine.url.database)
    if (
        db_path.parent != Path("/tmp")
        or not db_path.name.startswith("amrutam_redis_ci_")
    ):
        pytest.fail(f"Refusing to use a non-test database path: {db_path}")

    if db_path.exists():
        pytest.fail(f"Refusing to overwrite an existing test database: {db_path}")

    token = uuid4().hex
    email = f"redis-api-{token}@example.invalid"
    password = "Redis-Smoke-Test-482!x"
    wrong_password = "Wrong-Redis-Test-731!x"
    client_ip = f"198.18.{uuid4().int & 255}.{(uuid4().int >> 8) & 255}"

    account_keys = limiter._account_keys(email)
    ip_keys = [
        f"amrutam:rate-limit:POST:/api/v1/auth/register:{client_ip}",
        f"amrutam:rate-limit:POST:/api/v1/auth/login:{client_ip}",
        f"amrutam:rate-limit:POST:/api/v1/auth/token:{client_ip}",
    ]

    try:
        if not limiter._sync_redis.ping():
            pytest.fail("Redis ping failed.")

        assert email not in repr(account_keys)
        Base.metadata.create_all(bind=engine)

        with TestClient(app, client=(client_ip, 53142)) as api:
            registered = api.post(
                "/api/v1/auth/register",
                json={
                    "email": email,
                    "full_name": "Redis API Integration Test",
                    "password": password,
                    "role": "patient",
                },
            )
            assert registered.status_code == 201, registered.text

            # Five failed requests on /login remain within that IP bucket.
            for _ in range(5):
                response = api.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": wrong_password},
                )
                assert response.status_code == 401, response.text

            # A second login endpoint shares the account-level counter.
            response = api.post(
                "/api/v1/auth/token",
                data={"username": email, "password": wrong_password},
            )
            assert response.status_code == 401, response.text

            failure_key, cooldown_key = account_keys
            assert int(limiter._sync_redis.get(failure_key) or 0) == 6
            assert limiter._sync_redis.exists(cooldown_key) == 1

            # Set a deterministic window for the HTTP 429 assertion.
            limiter._sync_redis.set(cooldown_key, "30", ex=30)
            blocked = api.post(
                "/api/v1/auth/token",
                data={"username": email, "password": wrong_password},
            )
            assert blocked.status_code == 429, blocked.text
            assert int(blocked.headers["Retry-After"]) > 0

            # Valid credentials must still succeed and clear account state.
            valid = api.post(
                "/api/v1/auth/token",
                data={"username": email, "password": password},
            )
            assert valid.status_code == 200, valid.text
            assert "access_token" in valid.json()
            assert limiter.check_account_cooldown(email) == 0
            assert limiter._sync_redis.exists(*account_keys) == 0

    finally:
        # Remove only the generated account/IP keys and the dedicated test DB.
        try:
            limiter._sync_redis.delete(*account_keys, *ip_keys)
        finally:
            engine.dispose()
            db_path.unlink(missing_ok=True)
