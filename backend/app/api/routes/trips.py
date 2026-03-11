from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.agent.orchestrator import build_trip_state
from app.core.config import get_settings
from app.db.sqlite import Database
from app.models.client import ModelApiClient, ModelApiError
from app.models.credential_resolver import ModelCredentialResolver, ModelResolutionError
from app.schemas.requests import CreateTripRequest, RegenerateRequest, ReorderRequest, TripMessageRequest
from app.schemas.responses import TripListResponse, TripResponse, TripSummaryResponse

router = APIRouter(prefix="/api/trips", tags=["trips"])
settings = get_settings()
database = Database(settings)
model_resolver = ModelCredentialResolver(settings)
model_client = ModelApiClient()
logger = logging.getLogger("travel_agent.routes.trips")


def _normalize_user_query(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text.strip()
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return "\n".join(deduped)


@router.post("", response_model=TripResponse)
def create_trip(payload: CreateTripRequest) -> TripResponse:
    normalized_query = _normalize_user_query(payload.query)
    try:
        resolved = model_resolver.resolve(payload.model_request)
    except ModelResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        trip = build_trip_state(normalized_query, resolved, interaction_mode=payload.interaction_mode, model_client=model_client)
    except ModelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled create_trip failure")
        raise HTTPException(status_code=500, detail=f"Trip generation failed: {exc}") from exc
    database.save_trip(trip, normalized_query)
    return TripResponse(trip=trip)


@router.get("", response_model=TripListResponse)
def list_trips(limit: int = 50) -> TripListResponse:
    trips = database.list_trips(limit=limit)
    return TripListResponse(
        trips=[
            TripSummaryResponse(
                trip_id=trip.trip_id,
                query=trip.query,
                headline=trip.plan_summary.headline,
                destination=trip.travel_logistics.destination,
                view_state=trip.view_state,
                updated_at=trip.updated_at,
                created_at=trip.created_at,
            )
            for trip in trips
        ]
    )


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
    incoming = _normalize_user_query(payload.message)
    if payload.interaction_mode == "direct":
        combined_query = incoming
    else:
        combined_query = _normalize_user_query(f"{existing.query}\n{incoming}")
    try:
        trip = build_trip_state(combined_query, resolved, interaction_mode=payload.interaction_mode, existing_trip_id=trip_id, model_client=model_client)
    except ModelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled post_message failure")
        raise HTTPException(status_code=500, detail=f"Trip update failed: {exc}") from exc
    database.save_trip(trip, incoming)
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled regenerate_trip failure")
        raise HTTPException(status_code=500, detail=f"Trip regeneration failed: {exc}") from exc
    database.save_trip(trip, f"regenerate:{payload.scope}")
    return TripResponse(trip=trip)
