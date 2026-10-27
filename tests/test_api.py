from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import User, Doctor, AvailabilitySlot
from app.security import hash_password
def register(client, email="patient@example.com", role="patient"):
    return client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Test Patient", "password": "correct-horse-battery-staple",
        "role": role
    })

def login(client, email="patient@example.com"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"

def test_register_login_me(client):
    response = register(client)
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    headers = login(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "patient"

def test_public_registration_cannot_assign_admin(client):
    response = register(client, "attacker@example.com", "admin")
    assert response.status_code == 400

def test_duplicate_email_rejected(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409

def test_admin_endpoint_requires_auth(client):
    assert client.get("/api/v1/admin/analytics").status_code == 401
def test_booking_idempotency_and_duplicate_slot(client):
    # Register and authenticate a patient.
    assert register(client).status_code == 201
    patient_headers = login(client)

    # Prepare a doctor and a future availability slot.
    db = SessionLocal()
    try:
        doctor_user = User(
            email="doctor-booking@example.com",
            full_name="Test Doctor",
            password_hash=hash_password("doctor-test-password"),
            role="doctor",
        )
        db.add(doctor_user)
        db.flush()

        doctor = Doctor(
            user_id=doctor_user.id,
            specialty="General Medicine",
            bio="Test doctor",
        )
        db.add(doctor)
        db.flush()

        starts_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) + timedelta(days=1)

        slot = AvailabilitySlot(
            doctor_id=doctor.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            is_booked=False,
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
        slot_id = slot.id
    finally:
        db.close()

    payload = {
        "slot_id": slot_id,
        "reason": "Routine consultation",
    }
    headers = {
        **patient_headers,
        "Idempotency-Key": "booking-idempotency-test-001",
    }

    # First request should create a consultation.
    first = client.post(
        "/api/v1/bookings",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201, first.text

    # Retrying with the same key should return the same consultation.
    retry = client.post(
        "/api/v1/bookings",
        json=payload,
        headers=headers,
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]

    # A different key must not book the occupied slot again.
    duplicate_headers = {
        **patient_headers,
        "Idempotency-Key": "booking-idempotency-test-002",
    }
    duplicate = client.post(
        "/api/v1/bookings",
        json=payload,
        headers=duplicate_headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    # Confirm that only one consultation exists for the patient.
    consultations = client.get(
        "/api/v1/consultations",
        headers=patient_headers,
    )
    assert consultations.status_code == 200
    assert len(consultations.json()) == 1
    # Verify consultation status transitions.
    doctor_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "doctor-booking@example.com",
            "password": "doctor-test-password",
        },
    )
    assert doctor_login.status_code == 200, doctor_login.text

    doctor_headers = {
        "Authorization": (
            f"Bearer {doctor_login.json()['access_token']}"
        )
    }
    consultation_id = first.json()["id"]

    # A doctor must not skip directly from booked to completed.
    invalid_transition = client.patch(
        f"/api/v1/consultations/{consultation_id}/status",
        json={"status": "completed"},
        headers=doctor_headers,
    )
    assert invalid_transition.status_code == 409

    # The consultation must follow the valid sequence.
    for next_status in ["confirmed", "in_progress", "completed"]:
        response = client.patch(
            f"/api/v1/consultations/{consultation_id}/status",
            json={"status": next_status},
            headers=doctor_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == next_status

    # A completed consultation must remain terminal.
    terminal_transition = client.patch(
        f"/api/v1/consultations/{consultation_id}/status",
        json={"status": "confirmed"},
        headers=doctor_headers,
    )
    assert terminal_transition.status_code == 409

def test_cancelled_slot_can_be_rebooked(client):
    # Register and authenticate a patient.
    assert register(client).status_code == 201
    patient_headers = login(client)

    # Create a doctor and a future availability slot.
    db = SessionLocal()
    try:
        doctor_user = User(
            email="doctor-rebook@example.com",
            full_name="Rebooking Test Doctor",
            password_hash=hash_password("doctor-test-password"),
            role="doctor",
        )
        db.add(doctor_user)
        db.flush()

        doctor = Doctor(
            user_id=doctor_user.id,
            specialty="General Medicine",
            bio="Rebooking test doctor",
        )
        db.add(doctor)
        db.flush()

        starts_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(days=1)
        )

        slot = AvailabilitySlot(
            doctor_id=doctor.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            is_booked=False,
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
        slot_id = slot.id
    finally:
        db.close()

    payload = {
        "slot_id": slot_id,
        "reason": "Routine consultation",
    }

    # First patient books the slot.
    first = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={
            **patient_headers,
            "Idempotency-Key": "rebook-test-key-001",
        },
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # The patient cancels the consultation.
    cancelled = client.patch(
        f"/api/v1/consultations/{first_id}/status",
        json={"status": "cancelled"},
        headers=patient_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # The same slot can now be booked using a new idempotency key.
    second = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={
            **patient_headers,
            "Idempotency-Key": "rebook-test-key-002",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first_id

    # Both records should remain, preserving cancellation history.
    consultations = client.get(
        "/api/v1/consultations",
        headers=patient_headers,
    )
    assert consultations.status_code == 200

    records = consultations.json()
    assert len(records) == 2

    statuses = {record["id"]: record["status"] for record in records}
    assert statuses[first_id] == "cancelled"
    assert statuses[second.json()["id"]] == "booked"

def test_login_rate_limit_returns_429(client):
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "rate-limit-missing@example.com",
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "rate-limit-missing@example.com",
            "password": "WrongPassword123!",
        },
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_token_endpoint_rate_limit_returns_429(client):
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/token",
            data={
                "username": "rate-limit-missing@example.com",
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401

    response = client.post(
        "/api/v1/auth/token",
        data={
            "username": "rate-limit-missing@example.com",
            "password": "WrongPassword123!",
        },
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_registration_rate_limit_returns_429(client):
    for attempt in range(5):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"rate-limit-{attempt}@example.com",
                "full_name": f"Rate Limit Patient {attempt}",
                "password": "StrongTestPassword123!",
                "role": "patient",
            },
        )
        assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "rate-limit-sixth@example.com",
            "full_name": "Rate Limit Patient Sixth",
            "password": "StrongTestPassword123!",
            "role": "patient",
        },
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0