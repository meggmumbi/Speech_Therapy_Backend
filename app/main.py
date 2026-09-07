from fastapi import FastAPI

from .api import (
    children,
    auth,
    activities,
    speech_processing,
    analytics,
    feedback, ws_routes, genericappendpoints, pronunciation, study
)
from fastapi.middleware.cors import CORSMiddleware
from .database import Base, engine
from .services import analyze_pronunciation, analyse_pronunciation
from .services.pronunciation.runtime import warmup as warmup_pronunciation

Base.metadata.create_all(bind=engine)

app = FastAPI(debug=True)


@app.on_event("startup")
def _load_acoustic_model() -> None:
    # Loading the model costs seconds and ~1.2 GB. Doing it here means the
    # first participant of a session does not pay for it. Failures are logged
    # inside warmup(), not raised: the rest of the API must still serve.
    warmup_pronunciation()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_routes.router)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(children.router, prefix="/children", tags=["children"])
app.include_router(activities.router, prefix="/activities", tags=["activities"])
app.include_router(genericappendpoints.router, prefix="/generic", tags=["generic"])
app.include_router(speech_processing.router, prefix="/speech", tags=["speech_processing"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])  # Add this line
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])  # Add this line
app.include_router(pronunciation.router, prefix="/pronunciation", tags=["pronunciation"])
app.include_router(study.router, prefix="/study", tags=["study"])