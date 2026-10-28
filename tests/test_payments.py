from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import AvailabilitySlot, Consultation, Doctor, Payment, User
from app.security import hash_password


API = "/api/v1"
PATIENT_PASSWORD = "test-payment-password-123"
ADMIN_PASSWORD = "test-admin-password-123"


def _register_and_login(client, email: str, password: str = PATIENT_PASSWORD):
    register = client.post(
        f"{API}/auth/register",
        json={"email": email, "full_name": "Payment Test User", "password": password, "role": "patient"},
    )
    assert register.status_code == 201, register.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_consultation(email: str, suffix: str) -> int:
    with Session(engine) as db:
        patient = db.scalar(select(User).where(User.email == email))
        assert patient is not None
        doctor_user = User(
            email=f"doctor-payment-{suffix}@example.com",
            full_name="Payment Test Doctor",
            password_hash=hash_password("unused-doctor-password-123"),
            role="doctor",
        )
        db.add(doctor_user)
        db.flush()
        doctor = Doctor(user_id=doctor_user.id, specialty="General Medicine", bio="")
        db.add(doctor)
        db.flush()
        starts_at = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None)
        slot = AvailabilitySlot(
            doctor_id=doctor.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            is_booked=True,
        )
        db.add(slot)
        db.flush()
        consultation = Consultation(
            patient_id=patient.id,
            doctor_id=doctor.id,
            slot_id=slot.id,
            status="booked",
            reason="Payment workflow test",
        )
        db.add(consultation)
        db.commit()
        return consultation.id


def _create_intent(client, consultation_id: int, headers, key: str = "payment-intent-test-001"):
    return client.post(
        f"{API}/consultations/{consultation_id}/payments",
        headers={**headers, "Idempotency-Key": key},
    )


def test_payment_intent_uses_server_amount_and_is_idempotent(client, monkeypatch):
    monkeypatch.setenv("AMRUTAM_CONSULTATION_FEE_MINOR", "12500")
    email = "payment-patient-one@example.com"
    headers = _register_and_login(client, email)
    consultation_id = _seed_consultation(email, "intent")

    created = _create_intent(client, consultation_id, headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount_minor"] == 12500
    assert body["currency"] == "INR"
    assert body["status"] == "pending"
    assert body["provider"] == "unconfigured"

    retry = _create_intent(client, consultation_id, headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == body["id"]

    fetched = client.get(f"{API}/payments/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_payment_idempotency_key_cannot_be_reused_for_another_consultation(client):
    email = "payment-patient-two@example.com"
    headers = _register_and_login(client, email)
    first_consultation = _seed_consultation(email, "key-a")
    second_consultation = _seed_consultation(email, "key-b")

    first = _create_intent(client, first_consultation, headers, "payment-shared-key-001")
    assert first.status_code == 201, first.text
    second = _create_intent(client, second_consultation, headers, "payment-shared-key-001")
    assert second.status_code == 409, second.text


def test_patient_cannot_create_or_read_another_patients_payment(client):
    owner_email = "payment-owner@example.com"
    other_email = "payment-other@example.com"
    owner_headers = _register_and_login(client, owner_email)
    other_headers = _register_and_login(client, other_email)
    consultation_id = _seed_consultation(owner_email, "private")

    created = _create_intent(client, consultation_id, owner_headers, "payment-private-key-001")
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]

    other_create = _create_intent(client, consultation_id, other_headers, "payment-other-key-001")
    assert other_create.status_code == 404
    other_read = client.get(f"{API}/payments/{payment_id}", headers=other_headers)
    assert other_read.status_code == 404


def test_admin_manual_reconciliation_is_audited_and_enforces_transitions(client):
    email = "payment-reconcile-patient@example.com"
    patient_headers = _register_and_login(client, email)
    consultation_id = _seed_consultation(email, "reconcile")
    created = _create_intent(client, consultation_id, patient_headers, "payment-reconcile-key-001")
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]

    with Session(engine) as db:
        admin = User(
            email="payment-admin@example.com",
            full_name="Payment Admin",
            password_hash=hash_password(ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)
        db.commit()

    login = client.post(f"{API}/auth/login", json={"email": "payment-admin@example.com", "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    completed = client.patch(
        f"{API}/admin/payments/{payment_id}/status",
        headers=admin_headers,
        json={"status": "succeeded", "provider_reference": "manual-reconcile-ref-123"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"

    invalid_transition = client.patch(
        f"{API}/admin/payments/{payment_id}/status",
        headers=admin_headers,
        json={"status": "failed"},
    )
    assert invalid_transition.status_code == 409, invalid_transition.text

    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        assert payment is not None and payment.status == "succeeded"
        from app.models import AuditLog
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "payment.status_reconciled"))
        assert audit is not None
