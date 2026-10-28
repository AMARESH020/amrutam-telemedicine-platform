# API quick reference

Interactive OpenAPI UI: `http://localhost:8000/docs`

- `GET /health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me` (Bearer token)
- `POST /api/v1/doctors` (admin)
- `GET /api/v1/doctors?specialty=...&q=...`
- `POST /api/v1/doctors/{doctor_id}/slots` (doctor/admin)
- `GET /api/v1/doctors/{doctor_id}/slots`
- `POST /api/v1/bookings` (patient; requires `Idempotency-Key`)
- `GET /api/v1/consultations`
- `PATCH /api/v1/consultations/{consultation_id}/status`
- `POST /api/v1/consultations/{consultation_id}/prescriptions` (doctor/admin)
- `GET /api/v1/admin/analytics` (admin)
- `GET /api/v1/admin/audit-logs` (admin)

All timestamps for slot creation must include a timezone. This demo stores slot timestamps as UTC-naive values after normalization.


## Payments (provider-neutral demo)

- `POST /api/v1/consultations/{consultation_id}/payments` (patient; requires `Idempotency-Key`). Creates one pending payment-intent record for a booked or confirmed consultation. The server sets the amount from `AMRUTAM_CONSULTATION_FEE_MINOR` (in paise); the demo default is `50000` (INR 500.00). Replaying the same key and consultation returns the same record; reusing a key for another request returns `409`.
- `GET /api/v1/payments/{payment_id}` (owning patient or admin).
- `PATCH /api/v1/admin/payments/{payment_id}/status` (admin only). Manual reconciliation is audited and state transitions are constrained. A provider reference is required for `succeeded` and `refunded`.

**Payment limitation:** these endpoints do not collect card details, contact a gateway, authorize a payment method, or transfer funds. The admin status endpoint is a controlled demo/manual-reconciliation mechanism, not a substitute for a verified provider webhook. Configure and integrate a real provider before production use.
