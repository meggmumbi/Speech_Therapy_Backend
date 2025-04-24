from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.orm import Session
from starlette import status

from ..schemas.caregiver import CaregiverCreate
from ..models.caregiver import Caregiver
from ..database import get_db
from ..utils.auth import get_password_hash, create_access_token, verify_password

router = APIRouter()


@router.post("/register")
def register(caregiver: CaregiverCreate, db: Session = Depends(get_db)):
    db_caregiver = db.query(Caregiver).filter(Caregiver.email == caregiver.email).first()
    if db_caregiver:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = get_password_hash(caregiver.password)
    new_caregiver = Caregiver(
        username=caregiver.username,
        email=caregiver.email,
        hashed_password=hashed_password
    )
    db.add(new_caregiver)
    db.commit()
    db.refresh(new_caregiver)
    return {"message": "Caregiver created successfully"}


@router.post("/login")
def login(
    username: str,
    password: str,
    db: Session = Depends(get_db)
):
    caregiver = db.query(Caregiver).filter(Caregiver.username == username).first()
    if not caregiver or not verify_password(password, caregiver.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": caregiver.username})
    return {"access_token": access_token, "token_type": "bearer"}