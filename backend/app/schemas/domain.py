from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.providers import ModelId, ModelSource, ProviderWarning

ViewState = Literal[
    "idle",
    "submitting",
    "needs_clarification",
    "itinerary_ready",
    "partial_itinerary_with_warnings",
    "error_recoverable",
]
InteractionMode = Literal["direct", "planning"]


class ClarificationQuestion(BaseModel):
    id: str
    label: str
    question: str
    suggestions: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    id: str
    start_time: str
    end_time: str
    title: str
    location: str
    travel_time_from_previous: str
    cost_estimate: str | None = None
    description: str
    image_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    risk_flags: list[str] = Field(default_factory=list)


class RoutePoint(BaseModel):
    label: str
    latitude: float
    longitude: float


class DayPlan(BaseModel):
    day_index: int
    title: str
    theme: str
    events: list[TimelineEvent]
    route_points: list[RoutePoint] = Field(default_factory=list)


class PlanSummary(BaseModel):
    headline: str
    body: str
    highlights: list[str] = Field(default_factory=list)


class BudgetSummary(BaseModel):
    trip_total_estimate: str
    current_day_estimate: str
    budget_status: Literal["on_track", "watch", "over"]
    transport_total_estimate: str | None = None
    flight_total_estimate: str | None = None
    rail_total_estimate: str | None = None
    city_transport_total_estimate: str | None = None
    car_rental_total_estimate: str | None = None
    hotel_total_estimate: str | None = None
    notes: list[str] = Field(default_factory=list)


class MemorySummary(BaseModel):
    fixed_anchors: list[str] = Field(default_factory=list)
    open_constraints: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    last_selected_model: ModelId
    route_mode: str


class VisualReference(BaseModel):
    title: str
    image_url: str | None = None
    source_url: str | None = None


class MapPreview(BaseModel):
    route_label: str
    stops: list[str] = Field(default_factory=list)
    total_transit_time: str
    image_references: list[VisualReference] = Field(default_factory=list)


class TravelLogistics(BaseModel):
    origin: str = "Your city"
    destination: str = "Custom Destination"
    travelers: int = 1
    outbound_transport: str = "Flight to the destination"
    return_transport: str = "Flight back home"
    outbound_schedule: str = "Schedule pending"
    return_schedule: str = "Schedule pending"
    hotel_name: str = "Central Hotel"


class ReferenceLink(BaseModel):
    title: str
    url: str
    label: str


class TripState(BaseModel):
    trip_id: str
    view_state: ViewState
    interaction_mode: InteractionMode = "direct"
    selected_model_id: ModelId
    model_source: ModelSource
    query: str
    plan_summary: PlanSummary
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    timeline_days: list[DayPlan] = Field(default_factory=list)
    budget_summary: BudgetSummary
    memory_summary: MemorySummary
    provider_warnings: list[ProviderWarning] = Field(default_factory=list)
    conflict_warnings: list[ProviderWarning] = Field(default_factory=list)
    map_preview: MapPreview
    travel_logistics: TravelLogistics = Field(default_factory=TravelLogistics)
    reference_links: list[ReferenceLink] = Field(default_factory=list)
    planning_trace: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
