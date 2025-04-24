from fastapi import FastAPI
from .api import (
    children,
    auth,
    activities,
    speech_processing,
    analytics,
    feedback
)
from .database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(children.router, prefix="/children", tags=["children"])
app.include_router(activities.router, prefix="/activities", tags=["activities"])
app.include_router(speech_processing.router, prefix="/speech", tags=["speech_processing"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])  # Add this line
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])  # Add this line