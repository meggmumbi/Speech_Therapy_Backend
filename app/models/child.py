from sqlalchemy import Column, String, Integer, Date, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.database import Base


class Child(Base):
    __tablename__ = "children"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    age = Column(Integer)
    diagnosis_date = Column(Date)
    notes = Column(Text)
    created_at = Column(Date, default=datetime.utcnow)