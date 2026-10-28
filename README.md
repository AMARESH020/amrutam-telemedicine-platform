# Amrutam Telemedicine Backend

A submission-oriented FastAPI/PostgreSQL backend demonstrating authentication, role checks, doctor search, availability, idempotent booking, consultation status, prescriptions, audit logs, admin analytics, Docker and CI.

## Requirements
Python 3.12+ and Docker Desktop with Compose. The API can run on SQLite for a quick local smoke test; use PostgreSQL for realistic booking concurrency checks.

## Run locally (fastest)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# For SQLite smoke tests, set DATABASE_URL=sqlite:///./amrutam.db in .env
uvicorn app.main:app --reload
```
Open `http://localhost:8000/docs`, `http://localhost:8000/health`, `http://localhost:8000/metrics`, and `http://localhost:16686` (Jaeger UI when using Docker Compose).

## Run with Docker Compose
1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` and `JWT_SECRET` to strong unique values in your shell/environment.
3. Run `docker compose up --build`.
4. Open `http://localhost:8000/docs`.
5. Open `http://localhost:16686` to inspect OpenTelemetry traces in Jaeger. The Compose stack exports FastAPI and SQLAlchemy spans to Jaeger over OTLP/HTTP.

Do not use example secrets outside local development. Do not commit `.env`.

## Seed local demo staff accounts (development only)
PowerShell example (choose your own strong demo-only passwords):
```powershell
$env:DEMO_ADMIN_PASSWORD = "Choose-A-Strong-Local-Admin-Password"
$env:DEMO_DOCTOR_PASSWORD = "Choose-A-Strong-Local-Doctor-Password"
python -m scripts.seed_demo
```
This creates `admin.demo@example.com` and `doctor.demo@example.com` plus a General Medicine doctor profile. Never run demo seeding in production.

## Tests
```powershell
pytest -q
```

## Demo flow
1. Register a patient at `/api/v1/auth/register`.
2. Log in at `/api/v1/auth/login`; copy `access_token`.
3. Click **Authorize** in Swagger and enter `Bearer <token>`.
4. For a full booking demo, provision doctor/staff records in the development database, create a doctor profile, add a future availability slot, then book it with a unique `Idempotency-Key`.
5. Demonstrate consultation status and prescription endpoints, then admin analytics/audit endpoints using a provisioned admin account.

For local-only demo seeding, use a temporary script or database console; never expose a public admin-registration endpoint.

## Scope and limitations
This is a focused assignment implementation, not a production-certified telemedicine platform. TOTP MFA and Redis-backed shared IP rate limiting for login, token, and registration are implemented. Broader gateway/WAF protections, production validation and tuning of account-aware cooldowns, real payment/video-provider integrations, durable async jobs, managed secret/key rotation, production load testing, and verified disaster recovery remain production hardening tasks. The payment API currently records provider-neutral intents and audited manual reconciliation only; it does not collect or transfer funds. See `docs/ARCHITECTURE.md` and `docs/SECURITY_THREAT_MODEL.md`.

## Account-aware authentication cooldown

In addition to Redis-backed IP rate limiting, password and MFA failures are
tracked per account. Account identifiers are HMAC-SHA256 digests derived from
the normalized email address and the configured JWT secret; raw email
addresses are not included in the account-limiter Redis keys.

The failure counter expires after 15 minutes of inactivity. Beginning with
the sixth failed password or MFA attempt, the limiter applies progressively
longer cooldowns: 1, 2, 4, 8, and 16 seconds, then a maximum of 30 seconds.
A successful authentication clears the account failure state. Missing and
invalid MFA codes are counted as failed authentication attempts.

The policy does not permanently lock accounts. A complete valid credential
sequence can still succeed during a cooldown, preventing an attacker from
using the cooldown as a simple account-lockout mechanism. Failed attempts
during an active cooldown receive HTTP 429 with a Retry-After header.
If Redis is unavailable, or Redis is not configured in production, the
account limiter fails closed with HTTP 503.

Operational limitations: account cooldowns do not replace IP throttling,
MFA, monitoring, or gateway/WAF protections. The cooldown check for an
incorrect password occurs after password verification, so it does not by
itself eliminate password-hashing CPU costs. Account-specific Redis behavior has unit coverage using a fake Redis client
and passed a smoke test against the Docker Redis service covering hashed keys,
progressive cooldowns, and reset behavior. Production load, multi-replica abuse
scenarios, and broader operational behavior remain to be validated. Keep the
production JWT secret strong and stable:
rotating it changes account-key digests, so prior counters remain under their
old keys until they expire.
