import uuid
from datetime import datetime

from pydantic import BaseModel


class GazeTrackingDataBase(BaseModel):
    session_id: uuid.UUID
    child_id: uuid.UUID
    session_duration_ms: int
    total_attention_time_ms: int
    attention_percentage: float
    time_in_zone1_ms: int
    time_in_zone2_ms: int
    time_in_zone3_ms: int
    zone1_percentage: float
    zone2_percentage: float
    zone3_percentage: float
    average_pleasure: float
    average_excitement: float
    engagement_percentage: float
    smile_percentage: float
    total_gaze_data_points: int
    session_start_time: int
    session_end_time: int

    class Config:
        from_attributes = True

class GazeTrackingDataCreate(GazeTrackingDataBase):
    pass

class GazeTrackingData(GazeTrackingDataBase):
    id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True