from uuid import UUID

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class LearningPathItemSchema(BaseModel):
    category_id: UUID
    category_name: str
    target_score: float
    current_score: Optional[float]
    status: str
    priority: int
    reason: str

class LearningPathSchema(BaseModel):
    child_id: UUID
    paths: List[LearningPathItemSchema]
    created_at: datetime
    updated_at: datetime

class AdaptationRecommendation(BaseModel):
    action: str
    difficulty_adjustment: Optional[int]
    modality_suggestion: Optional[str]
    feedback: str
    error_patterns: Optional[dict]

class AdaptationSchema(BaseModel):
    recommendations: List[AdaptationRecommendation]
    session_id: UUID
    generated_at: datetime