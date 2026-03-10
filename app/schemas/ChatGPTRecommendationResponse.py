from pydantic import BaseModel
from datetime import datetime

class ChatGPTRecommendationResponse(BaseModel):
    child_id: str
    child_name: str
    recommendations: str
    prompt_used: str
    timestamp: datetime