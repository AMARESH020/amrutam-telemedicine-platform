from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: str = "patient"

class LoginIn(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = Field(default=None, min_length=6, max_length=64)


class MFASetupIn(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class MFACodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class MFADisableIn(BaseModel):
    password: str = Field(min_length=10, max_length=128)
    code: str = Field(min_length=6, max_length=64)

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class DoctorCreate(BaseModel):
    user_id: int
    specialty: str = Field(min_length=2, max_length=120)
    bio: str = ""

class SlotCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime

class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doctor_id: int
    starts_at: datetime
    ends_at: datetime
    is_booked: bool

class BookingIn(BaseModel):
    slot_id: int
    reason: str = Field(default="", max_length=500)

class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_id: int
    doctor_id: int
    slot_id: int
    status: str
    reason: str
    created_at: datetime

class StatusIn(BaseModel):
    status: str

class PrescriptionIn(BaseModel):
    notes: str = Field(min_length=1, max_length=10000)
