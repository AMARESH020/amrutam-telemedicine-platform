
from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, Doctor
from app.security import hash_password


EMAIL = "doctor@example.com"
PASSWORD = "DoctorPass123!"


def seed_doctor():
    db = SessionLocal()

    try:
        # Find the demo doctor account or create it.
        user = db.scalar(
            select(User).where(User.email == EMAIL)
        )

        if user is None:
            user = User(
                email=EMAIL,
                full_name="Demo Doctor",
                password_hash=hash_password(PASSWORD),
                role="doctor",
            )
            db.add(user)
            db.flush()
        elif user.role != "doctor":
            raise ValueError(
                f"{EMAIL} already exists with role '{user.role}'. "
                "Choose a different demo email."
            )

        # Create the doctor profile if it does not exist.
        doctor = db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )

        if doctor is None:
            doctor = Doctor(
                user_id=user.id,
                specialty="General Medicine",
                bio="Demo doctor profile for API testing.",
            )
            db.add(doctor)
            db.flush()

        db.commit()

        print("Demo doctor seeded successfully.")
        print("Email:", user.email)
        print("Role:", user.role)
        print("Doctor profile ID:", doctor.id)

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_doctor()
