from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agent.orchestrator import build_trip_state
from app.core.config import get_settings
from app.db.sqlite import Database
from app.models.client import ModelApiClient, ModelApiError
from app.models.credential_resolver import ModelCredentialResolver, ModelResolutionError
from app.schemas.requests import CreateTripRequest, RegenerateRequest, ReorderRequest, TripMessageRequest
from app.schemas.responses import TripResponse

router = APIRouter(prefix="/api/trips", tags=["trips"])
settings = get_settings()
database = Database(settings)
model_resolver = ModelCredentialResolver(settings)
model_client = ModelApiClient()


@router.post("", response_model=TripResponse)
def create_trip(payload: CreateTripRequest) -> TripResponse:
    try:
        resolved = model_resolver.resolve(payload.model_request)
    except ModelResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        trip = build_trip_state(payload.query, resolved, interaction_mode=payload.interaction_mode, model_client=model_client)
    except ModelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    database.save_trip(trip, payload.query)
    return TripResponse(trip=trip)


@router.get("/{trip_id}", response_model=TripResponse)
def get_trip(trip_id: str) -> TripResponse:
    trip = database.get_trip(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return TripResponse(trip=trip)


@router.post("/{trip_id}/messages", response_model=TripResponse)
def post_message(trip_id: str, payload: TripMessageRequest) -> TripResponse:
    existing = database.get_trip(trip_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        resolved = model_resolver.resolve(payload.model_request)
    except ModelResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    combined_query = f"{existing.query}\n{payload.message}"
    try:
        trip = build_trip_state(combined_query, resolved, interaction_mode=payload.interaction_mode, existing_trip_id=trip_id, model_client=model_client)
    except ModelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    database.save_trip(trip, payload.message)
    return TripResponse(trip=trip)


@router.post("/{trip_id}/reorder", response_model=TripResponse)
def reorder_trip(trip_id: str, payload: ReorderRequest) -> TripResponse:
    trip = database.get_trip(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    if payload.day_index < 0 or payload.day_index >= len(trip.timeline_days):
        raise HTTPException(status_code=400, detail="Invalid day index")
    day = trip.timeline_days[payload.day_index]
    event_map = {event.id: event for event in day.events}
    reordered = [event_map[event_id] for event_id in payload.event_ids if event_id in event_map]
    if len(reordered) == len(day.events):
        day.events = reordered
    trip.conflict_warnings = []
    database.save_trip(trip, f"reorder day {payload.day_index}")
    return TripResponse(trip=trip)


@router.post("/{trip_id}/regenerate", response_model=TripResponse)
def regenerate_trip(trip_id: str, payload: RegenerateRequest) -> TripResponse:
    existing = database.get_trip(trip_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        resolved = model_resolver.resolve(payload.model_request)
    except ModelResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        trip = build_trip_state(existing.query, resolved, existing_trip_id=trip_id, model_client=model_client)
    except ModelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    database.save_trip(trip, f"regenerate:{payload.scope}")
    return TripResponse(trip=trip)
