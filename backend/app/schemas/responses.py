from __future__ import annotations

from pydantic import BaseModel

from app.schemas.domain import TripState
from app.schemas.providers import ProviderHealthSummary, ProviderWarning, SupportedModelInfo


class ModelsResponse(BaseModel):
    models: list[SupportedModelInfo]
    default_model_id: str
    mock_model_fallback_enabled: bool


class HealthResponse(BaseModel):
    status: str
    providers: ProviderHealthSummary
    warnings: list[ProviderWarning]


class TripResponse(BaseModel):
    trip: TripState


class TripSummaryResponse(BaseModel):
    trip_id: str
    query: str
    headline: str
    destination: str
    view_state: str
    updated_at: str
    created_at: str


class TripListResponse(BaseModel):
    trips: list[TripSummaryResponse]
