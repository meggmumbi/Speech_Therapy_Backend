from pydantic import BaseModel, EmailStr


class CaregiverBase(BaseModel):
    username: str
    email: EmailStr


class CaregiverCreate(CaregiverBase):
    password: str


class Caregiver(CaregiverBase):
    id: str
    is_active: bool

    class Config:
        from_attributes = True