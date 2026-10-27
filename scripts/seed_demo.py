"""Create local demo accounts. Set DEMO_ADMIN_PASSWORD and DEMO_DOCTOR_PASSWORD first."""
import os
from sqlalchemy import select
from app.db import Base, engine, SessionLocal
from app.models import User, Doctor
from app.security import hash_password

Base.metadata.create_all(bind=engine)
admin_password = os.getenv("DEMO_ADMIN_PASSWORD")
doctor_password = os.getenv("DEMO_DOCTOR_PASSWORD")
if not admin_password or not doctor_password:
    raise SystemExit("Set DEMO_ADMIN_PASSWORD and DEMO_DOCTOR_PASSWORD environment variables first.")

with SessionLocal() as db:
    admin = db.scalar(select(User).where(User.email == "admin.demo@example.com"))
    if not admin:
        admin = User(email="admin.demo@example.com", full_name="Demo Admin", password_hash=hash_password(admin_password), role="admin")
        db.add(admin)
    doctor_user = db.scalar(select(User).where(User.email == "doctor.demo@example.com"))
    if not doctor_user:
        doctor_user = User(email="doctor.demo@example.com", full_name="Demo Doctor", password_hash=hash_password(doctor_password), role="doctor")
        db.add(doctor_user)
    db.flush()
    profile = db.scalar(select(Doctor).where(Doctor.user_id == doctor_user.id))
    if not profile:
        db.add(Doctor(user_id=doctor_user.id, specialty="General Medicine", bio="Demo profile for assignment walkthrough"))
    db.commit()
print("Seeded admin.demo@example.com and doctor.demo@example.com. Use the passwords supplied through environment variables.")
