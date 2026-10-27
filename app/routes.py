import json
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Form, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, Doctor, AvailabilitySlot, Consultation, Prescription, AuditLog, IdempotencyRecord
from app.schemas import RegisterIn, LoginIn, UserOut, TokenOut, DoctorCreate, SlotCreate, SlotOut, BookingIn, ConsultationOut, StatusIn, PrescriptionIn, MFASetupIn, MFACodeIn, MFADisableIn
from app.security import hash_password, verify_password, create_access_token, get_current_user, require_roles
from app.mfa import encrypt_mfa_secret, decrypt_mfa_secret, generate_totp_secret, get_totp_provisioning_uri, verify_totp_secret, generate_recovery_codes, verify_user_mfa_code

router = APIRouter()

def audit(db: Session, actor_id: int | None, action: str, resource_type: str, resource_id: str, details: str = ""):
    db.add(AuditLog(actor_user_id=actor_id, action=action, resource_type=resource_type, resource_id=str(resource_id), details=details))

@router.post("/auth/register", response_model=UserOut, status_code=201, tags=["auth"])
def register(data: RegisterIn, db: Session = Depends(get_db)):
    # Public self-registration is limited to patient accounts; staff roles must be provisioned by an admin.
    if data.role != "patient":
        raise HTTPException(400, "Public registration can only create patient accounts")
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise HTTPException(409, "Email already registered")
    user = User(email=data.email.lower(), full_name=data.full_name, password_hash=hash_password(data.password), role="patient")
    db.add(user); db.flush()
    audit(db, user.id, "user.registered", "user", user.id)
    db.commit(); db.refresh(user)
    return user

def _authenticate_password_login(
    db: Session,
    email: str,
    password: str,
    mfa_code: str | None,
) -> dict:
    user = db.scalar(select(User).where(User.email == email.lower()).with_for_update())

    if (
        not user
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.mfa_enabled:
        if not mfa_code:
            raise HTTPException(
                status_code=401,
                detail="MFA code required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        valid, recovery_used = verify_user_mfa_code(user, mfa_code)

        if not valid:
            raise HTTPException(
                status_code=401,
                detail="Invalid email, password, or MFA code",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if recovery_used:
            audit(
                db,
                user.id,
                "auth.mfa_recovery_used",
                "user",
                user.id,
            )

        # Persist the new TOTP counter or consumed recovery code before
        # returning an access token.
        db.commit()

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
    }


@router.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(data: LoginIn, db: Session = Depends(get_db)):
    return _authenticate_password_login(
        db, data.email, data.password, data.mfa_code
    )


@router.post("/auth/token", response_model=TokenOut, tags=["auth"])
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    mfa_code: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    return _authenticate_password_login(
        db, form_data.username, form_data.password, mfa_code
    )

@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/auth/mfa/enroll", tags=["auth"])
def enroll_mfa(
    data: MFASetupIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid password")

    secret = generate_totp_secret()
    user.mfa_secret_encrypted = encrypt_mfa_secret(secret)
    user.mfa_recovery_codes = None

    audit(db, user.id, "auth.mfa_enrollment_started", "user", user.id)
    db.commit()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return {
        "secret": secret,
        "provisioning_uri": get_totp_provisioning_uri(secret, user.email),
        "message": "Add this account to your authenticator, then confirm with /auth/mfa/enable.",
    }


@router.post("/auth/mfa/enable", tags=["auth"])
def enable_mfa(
    data: MFACodeIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")

    if not user.mfa_secret_encrypted:
        raise HTTPException(409, "Start MFA enrollment first")

    secret = decrypt_mfa_secret(user.mfa_secret_encrypted)

    if not verify_totp_secret(secret, data.code):
        raise HTTPException(400, "Invalid authenticator code")

    recovery_codes, stored_digests = generate_recovery_codes()
    user.mfa_enabled = True
    user.mfa_recovery_codes = stored_digests

    audit(db, user.id, "auth.mfa_enabled", "user", user.id)
    db.commit()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return {
        "enabled": True,
        "recovery_codes": recovery_codes,
        "warning": "Save these recovery codes now. They are shown only once.",
    }


@router.post("/auth/mfa/disable", tags=["auth"])
def disable_mfa(
    data: MFADisableIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.mfa_enabled:
        raise HTTPException(409, "MFA is not enabled")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid password")

    valid, _ = verify_user_mfa_code(user, data.code)

    if not valid:
        raise HTTPException(401, "Invalid authenticator or recovery code")

    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_recovery_codes = None
    user.mfa_last_totp_counter = None

    audit(db, user.id, "auth.mfa_disabled", "user", user.id)
    db.commit()

    return {"enabled": False}

@router.post("/doctors", status_code=201, tags=["doctors"])
def create_doctor(data: DoctorCreate, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    user = db.get(User, data.user_id)
    if not user or user.role != "doctor":
        raise HTTPException(400, "user_id must refer to a provisioned doctor user")
    if db.scalar(select(Doctor).where(Doctor.user_id == data.user_id)):
        raise HTTPException(409, "Doctor profile already exists")
    doctor = Doctor(user_id=data.user_id, specialty=data.specialty, bio=data.bio)
    db.add(doctor); db.flush(); audit(db, admin.id, "doctor.created", "doctor", doctor.id); db.commit(); db.refresh(doctor)
    return {"id": doctor.id, "user_id": doctor.user_id, "specialty": doctor.specialty, "bio": doctor.bio}

@router.get("/doctors", tags=["doctors"])
def search_doctors(specialty: str | None = Query(default=None), q: str | None = Query(default=None), db: Session = Depends(get_db)):
    stmt = select(Doctor).where(Doctor.active.is_(True))
    if specialty:
        stmt = stmt.where(Doctor.specialty.ilike(f"%{specialty}%"))
    doctors = db.scalars(stmt.order_by(Doctor.id)).all()
    output = []
    for d in doctors:
        u = db.get(User, d.user_id)
        if q and q.lower() not in (u.full_name + " " + d.specialty + " " + d.bio).lower():
            continue
        output.append({"id": d.id, "name": u.full_name if u else "Unknown", "specialty": d.specialty, "bio": d.bio})
    return output

@router.post("/doctors/{doctor_id}/slots", response_model=SlotOut, status_code=201, tags=["availability"])
def create_slot(doctor_id: int, data: SlotCreate, db: Session = Depends(get_db), doctor_user: User = Depends(require_roles("doctor", "admin"))):
    doctor = db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.active.is_(True)))
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    if doctor_user.role == "doctor" and doctor.user_id != doctor_user.id:
        raise HTTPException(403, "Doctors can only manage their own availability")
    if data.starts_at.tzinfo is None or data.ends_at.tzinfo is None or data.ends_at <= data.starts_at:
        raise HTTPException(422, "Provide timezone-aware timestamps and an end time after start time")
    slot = AvailabilitySlot(doctor_id=doctor_id, starts_at=data.starts_at.astimezone(timezone.utc).replace(tzinfo=None), ends_at=data.ends_at.astimezone(timezone.utc).replace(tzinfo=None))
    db.add(slot)
    try:
        db.flush(); audit(db, doctor_user.id, "availability.created", "slot", slot.id); db.commit(); db.refresh(slot)
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "A slot already exists at this start time")
    return slot

@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut], tags=["availability"])
def list_slots(doctor_id: int, available_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(AvailabilitySlot).where(AvailabilitySlot.doctor_id == doctor_id)
    if available_only: stmt = stmt.where(AvailabilitySlot.is_booked.is_(False))
    return db.scalars(stmt.order_by(AvailabilitySlot.starts_at)).all()

@router.post("/bookings", response_model=ConsultationOut, status_code=201, tags=["bookings"])
def book(data: BookingIn, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160), db: Session = Depends(get_db), patient: User = Depends(require_roles("patient"))):
    prior = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == idempotency_key))
    if prior:
        if prior.user_id != patient.id:
            raise HTTPException(409, "Idempotency key belongs to another user")
        return json.loads(prior.response_body)
    slot = db.scalar(select(AvailabilitySlot).where(AvailabilitySlot.id == data.slot_id).with_for_update())
    if not slot:
        raise HTTPException(404, "Availability slot not found")
    if slot.is_booked:
        raise HTTPException(409, "Availability slot is already booked")
    if slot.starts_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(409, "Cannot book a slot in the past")
    slot.is_booked = True
    consultation = Consultation(patient_id=patient.id, doctor_id=slot.doctor_id, slot_id=slot.id, reason=data.reason, status="booked")
    db.add(consultation)
    try:
        db.flush()
        response = {"id": consultation.id, "patient_id": consultation.patient_id, "doctor_id": consultation.doctor_id, "slot_id": consultation.slot_id, "status": consultation.status, "reason": consultation.reason, "created_at": consultation.created_at.isoformat()}
        db.add(IdempotencyRecord(key=idempotency_key, user_id=patient.id, response_body=json.dumps(response)))
        audit(db, patient.id, "booking.created", "consultation", consultation.id, f"slot_id={slot.id}")
        db.commit()
        return response
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Slot or idempotency key was concurrently used; retry with a new key after checking booking status")

@router.get("/consultations", response_model=list[ConsultationOut], tags=["consultations"])
def list_consultations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Consultation).order_by(Consultation.created_at.desc())
    if user.role == "patient": stmt = stmt.where(Consultation.patient_id == user.id)
    elif user.role == "doctor":
        doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.id))
        stmt = stmt.where(Consultation.doctor_id == doctor.id) if doctor else stmt.where(Consultation.id == -1)
    return db.scalars(stmt).all()


@router.patch(
    "/consultations/{consultation_id}/status",
    response_model=ConsultationOut,
    tags=["consultations"],
)
def update_status(
    consultation_id: int,
    data: StatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    transitions = {
        "booked": {"confirmed", "cancelled"},
        "confirmed": {"in_progress", "cancelled"},
        "in_progress": {"completed"},
        "completed": set(),
        "cancelled": set(),
    }

    if data.status not in transitions:
        raise HTTPException(422, "Invalid consultation status")

    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        raise HTTPException(404, "Consultation not found")

    doctor = None
    if user.role == "doctor":
        doctor = db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )

    if user.role == "admin":
        permitted = True
    elif user.role == "patient":
        permitted = consultation.patient_id == user.id
    elif user.role == "doctor":
        permitted = (
            doctor is not None
            and consultation.doctor_id == doctor.id
        )
    else:
        permitted = False

    if not permitted:
        raise HTTPException(
            403, "Not allowed to access this consultation"
        )

    if user.role == "patient" and data.status != "cancelled":
        raise HTTPException(
            403, "Patients may only cancel a booking"
        )

    if data.status not in transitions[consultation.status]:
        raise HTTPException(
            409,
            f"Cannot change consultation from "
            f"{consultation.status} to {data.status}",
        )

    old_status = consultation.status
    consultation.status = data.status

    if data.status == "cancelled":
        slot = db.get(AvailabilitySlot, consultation.slot_id)
        if slot:
            slot.is_booked = False

    audit(
        db,
        user.id,
        "consultation.status_changed",
        "consultation",
        consultation.id,
        f"{old_status}->{data.status}",
    )

    db.commit()
    db.refresh(consultation)
    return consultation
@router.post(
    "/consultations/{consultation_id}/prescriptions",
    status_code=201,
    tags=["prescriptions"],
)
def create_prescription(
    consultation_id: int,
    data: PrescriptionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("doctor", "admin")),
):
    consultation = db.get(Consultation, consultation_id)

    if not consultation:
        raise HTTPException(404, "Consultation not found")

    doctor = None
    if user.role == "doctor":
        doctor = db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )

        if not doctor or consultation.doctor_id != doctor.id:
            raise HTTPException(
                403,
                "Doctors can only prescribe for their own consultations",
            )

    if consultation.status not in {"in_progress", "completed"}:
        raise HTTPException(
            409,
            "Consultation must be in progress or completed",
        )

    prescription = Prescription(
        consultation_id=consultation.id,
        doctor_id=consultation.doctor_id,
        notes=data.notes,
    )

    db.add(prescription)
    db.flush()

    audit(
        db,
        user.id,
        "prescription.created",
        "prescription",
        prescription.id,
    )

    db.commit()
    db.refresh(prescription)

    return {
        "id": prescription.id,
        "consultation_id": prescription.consultation_id,
        "doctor_id": prescription.doctor_id,
        "notes": prescription.notes,
        "created_at": prescription.created_at,
    }


@router.get("/admin/analytics", tags=["admin"])
def analytics(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    return {
        "users": db.query(User).count(),
        "doctors": db.query(Doctor).count(),
        "available_slots": db.query(AvailabilitySlot)
        .filter(AvailabilitySlot.is_booked.is_(False))
        .count(),
        "consultations_total": db.query(Consultation).count(),
        "consultations_by_status": {
            status: db.query(Consultation)
            .filter(Consultation.status == status)
            .count()
            for status in [
                "booked",
                "confirmed",
                "in_progress",
                "completed",
                "cancelled",
            ]
        },
    }


@router.get("/admin/audit-logs", tags=["admin"])
def audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    rows = db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]