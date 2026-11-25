from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_trips import router as trips_router
from app.config import settings

app = FastAPI(
    title="AI Travel Agent API",
    version="0.1.0",
    description="Milestone 1: Structured itinerary generation + deterministic constraint validation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trips_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "model": settings.gemini_model}
