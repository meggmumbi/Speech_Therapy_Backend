from fastapi import FastAPI

from .api import (
    children,
    auth,
    activities,
    speech_processing,
    analytics,
    feedback, ws_routes, genericappendpoints
)
from fastapi.middleware.cors import CORSMiddleware
from .database import Base, engine
from .services import analyze_pronunciation, analyse_pronunciation

Base.metadata.create_all(bind=engine)

app = FastAPI(debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(analyse_pronunciation("Which witch switched the Swiss wristwatches?", "Which witch shwitched the Shwiss wristwatches?"))


app.include_router(ws_routes.router)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(children.router, prefix="/children", tags=["children"])
app.include_router(activities.router, prefix="/activities", tags=["activities"])
app.include_router(genericappendpoints.router, prefix="/generic", tags=["generic"])
app.include_router(speech_processing.router, prefix="/speech", tags=["speech_processing"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])  # Add this line
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])  # Add this line