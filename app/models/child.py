from sqlalchemy import Column, String, Integer, Date, Text, Table, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base



child_category_association = Table(
    'child_category_association',
    Base.metadata,
    Column('child_id', UUID(as_uuid=True), ForeignKey('children.id')),
    Column('category_id', UUID(as_uuid=True), ForeignKey('activity_categories.id'))
)

class Child(Base):
    __tablename__ = "children"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    caregiver_id = Column(UUID, ForeignKey("caregivers.id"))
    name = Column(String(100), nullable=False)
    age = Column(Integer)
    diagnosis_date = Column(Date)
    notes = Column(Text)
    therapy_goals = Column(Text)
    created_at = Column(Date, default=datetime.utcnow)

    # Relationship with ActivityCategory
    areas_of_interest = relationship(
        "ActivityCategory",
        secondary=child_category_association,
        back_populates="children"
    )