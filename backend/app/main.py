from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.models import router as models_router
from app.api.routes.trips import router as trips_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Travel Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(trips_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Travel Agent API is running."}
