# Amrutam Telemedicine Backend — Architecture

## Scope and design
The API is a modular monolith built with FastAPI and PostgreSQL. Modules cover identity, doctor directory and availability, booking, consultation lifecycle, prescriptions, audit, and admin analytics. A modular monolith is a deliberate first release choice: it reduces operational overhead while keeping boundaries clear enough to split high-load components later.

## High-level flow
Client → TLS-terminating load balancer/API gateway → FastAPI application → PostgreSQL. Authentication uses short-lived signed JWT access tokens. Write workflows use database transactions; booking accepts an `Idempotency-Key`. Audit events are persisted with the corresponding business transaction. For production, add Redis for rate-limit counters/cache and a durable queue (e.g. managed queue) for notifications and other non-critical asynchronous work.

## Booking sequence
1. Patient authenticates and sends `POST /api/v1/bookings` with `Idempotency-Key`.
2. API validates role and request; looks up a prior response for the same key.
3. API locks the slot row where supported, checks availability and start time, then creates the consultation and marks the slot booked in one transaction.
4. A unique constraint on `consultations.slot_id` and a unique idempotency key provide additional race protection.
5. The API records an audit event and commits. Repeated same-user requests return the saved response.

## Data model
`users` 1—0..1 `doctors`; `doctors` 1—many `availability_slots`; `availability_slots` 1—0..1 `consultations`; `users` (patient) 1—many `consultations`; `consultations` 1—many `prescriptions`; `users` 1—many `audit_logs`; `users` 1—many `idempotency_records`.

## Reliability and concurrency
Use bounded retries with exponential backoff and jitter only for transient failures and only when the operation is safe to retry. Do not blindly retry non-idempotent writes. The current synchronous API relies on database transactions and constraints; PostgreSQL row locks serialize competing bookings. SQLite is only a local smoke-test fallback and does not provide equivalent row-lock semantics. Add deadlock/serialization retry middleware for production and monitor conflict rates.

## Scaling and partitioning
100k consultations/day averages about 1.16 consultations/second; peak traffic may be many times higher. Scale stateless API replicas horizontally behind a load balancer. Index foreign keys, status and time-based lookup fields. Begin with a properly sized PostgreSQL primary plus read replicas for read-heavy traffic. Consider monthly range partitioning of consultations/audit logs only after query plans and table growth justify it. Use Redis for cacheable doctor directory reads, with short TTLs and explicit invalidation on profile changes. Never cache private medical records without a reviewed access-control and invalidation design.

## Transactions and sagas
Booking is a single local transaction. Payment, notification and video-provider integrations are external side effects: use an outbox table plus worker, idempotent consumers, bounded retries and a saga/state machine for compensation (e.g. release a slot if payment fails). Do not hold a database transaction open while calling external services.

## Security and privacy
Public registration only creates patient accounts. Staff accounts must be provisioned through a trusted administrative process. Enforce RBAC and ownership checks, parameterized ORM queries, input constraints, TLS in transit, encrypted storage/backups, secret-manager storage, rotation, least privilege, rate limiting and dependency/image scanning. Never log passwords, tokens, payment details or clinical notes. Apply data minimization and retention rules; verify applicable Indian healthcare/privacy requirements with qualified counsel before production. TOTP MFA with encrypted secrets, one-time recovery codes and replay protection is implemented; key rotation and recovery procedures still need operational runbooks.

## Observability
Add structured request logs with request IDs; collect RED metrics (rate, errors, duration), DB pool saturation, booking conflicts, auth failures and queue lag. Expose Prometheus metrics in production and propagate trace context via OpenTelemetry. Alert on error budget burn, elevated p95, database saturation and failed backups. The included CI installs a test suite; deployment pipeline should add image scanning, migration checks and environment approval.

## Availability, backup and disaster recovery
99.95% availability permits about 21.6 minutes of downtime in a 30-day month. Use multi-zone application/database deployment, automated encrypted backups, point-in-time recovery, regular restore drills, documented RPO/RTO, and a tested regional recovery plan. Actual targets must be measured in a deployed environment.


## Payment records

The payment table stores a server-priced, provider-neutral intent and manual reconciliation state. It stores no cardholder data. The configured demo amount is `AMRUTAM_CONSULTATION_FEE_MINOR` in paise (default 50000 = INR 500.00); a patient cannot submit the amount. Unique idempotency keys and a partial unique index prevent duplicate active payment records for a consultation. Admin reconciliation is authenticated, transition-checked and audited. No payment gateway, signed webhook, real collection, refund execution or settlement is implemented; these require a selected provider and provider-verified events before production.
