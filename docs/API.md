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
