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
This is a focused assignment implementation, not a production-certified telemedicine platform. TOTP MFA is implemented; centralized rate limiting, real payment/video-provider integrations, durable async jobs, secret-manager/key rotation, full migration workflow, load testing and verified disaster recovery remain production hardening tasks. The payment API currently records provider-neutral intents and audited manual reconciliation only; it does not collect or transfer funds. See `docs/ARCHITECTURE.md` and `docs/SECURITY_THREAT_MODEL.md`.
