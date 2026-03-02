from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from app.agent.clarification_engine import build_clarification_questions
from app.agent.intent_parser import parse_intent
from app.models.client import ModelApiClient
from app.schemas.domain import BudgetSummary, DayPlan, MapPreview, MemorySummary, PlanSummary, TimelineEvent, TripState, VisualReference
from app.schemas.providers import ProviderWarning, ResolvedModelConfig
from app.tools.image_lookup import ImageLookupService

SAMPLE_IMAGES = [
    "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1526481280695-3c4691f8d1d3?auto=format&fit=crop&w=800&q=80",
    "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=800&q=80",
]
IMAGE_LOOKUP = ImageLookupService()


def _build_day(day_index: int, destination: str, style: str | None, budget: str | None) -> DayPlan:
    title = f"Day {day_index + 1}"
    theme = ["Arrival & Orientation", "Neighborhood Highlights", "Local Culture", "Flexible Favorites"][day_index % 4]
    base_hour = 8
    events: list[TimelineEvent] = []
    labels = [
        ("Hotel Breakfast", "Hotel Lounge", "10 min", "$18", "A slow start to keep the day flexible."),
        (f"Explore {destination} Core", f"{destination} Center", "20 min", "$0", "Anchor the day around a dense walkable zone."),
        ("Local Lunch", "Recommended Bistro", "12 min", "$32", "Midday break matched to your pace and budget."),
        ("Signature Sight", f"{destination} Landmark", "18 min", "$28", "A headline attraction scheduled outside the busiest hours."),
    ]
    for index, (label, location, travel, cost, description) in enumerate(labels):
        start = f"{base_hour + index * 2:02d}:00"
        end = f"{base_hour + index * 2 + 1:02d}:20"
        if budget == "budget" and cost != "$0":
            cost = "$15"
        if budget == "luxury":
            cost = "$45"
        events.append(
            TimelineEvent(
                id=f"d{day_index + 1}-e{index + 1}",
                start_time=start,
                end_time=end,
                title=label,
                location=location,
                travel_time_from_previous=travel,
                cost_estimate=cost,
                description=description if style != "Packed pace" else "A tighter sequence tuned for a higher activity load.",
                image_url=SAMPLE_IMAGES[index % len(SAMPLE_IMAGES)],
                risk_flags=["Tight connection"] if index == 3 and style == "Packed pace" else [],
            )
        )
    return DayPlan(day_index=day_index, title=title, theme=theme, events=events)


def _extract_visual_queries(query: str) -> list[str]:
    candidates: list[str] = []
    lowered = query.lower()
    if "西湖" in query:
        candidates.append("西湖")
    if "west lake" in lowered:
        if "西湖" not in candidates:
            candidates.append("西湖")
        candidates.append("West Lake")
    candidates.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", query))
    return candidates


def _enrich_visuals(query: str, timeline_days: list[DayPlan]) -> list[VisualReference]:
    references: list[VisualReference] = []
    seen_queries: set[str] = set()
    for search_term in _extract_visual_queries(query):
        normalized = search_term.strip().lower()
        if not normalized or normalized in seen_queries:
            continue
        seen_queries.add(normalized)
        reference = IMAGE_LOOKUP.search(search_term)
        if reference and reference.image_url:
            references.append(
                VisualReference(
                    title=reference.title,
                    image_url=reference.image_url,
                    source_url=reference.source_url,
                )
            )
        if len(references) >= 4:
            return references
    for day in timeline_days:
        for event in day.events:
            search_term = event.location or event.title
            normalized = search_term.strip().lower()
            if not normalized or normalized in seen_queries:
                continue
            seen_queries.add(normalized)
            reference = IMAGE_LOOKUP.search(search_term)
            if reference and reference.image_url:
                event.image_url = reference.image_url
                references.append(
                    VisualReference(
                        title=reference.title,
                        image_url=reference.image_url,
                        source_url=reference.source_url,
                    )
                )
            if len(references) >= 4:
                return references
    return references


def _base_trip_fields(
    *,
    trip_id: str,
    now: str,
    query: str,
    resolved_model: ResolvedModelConfig,
) -> dict[str, object]:
    provider_warnings: list[ProviderWarning] = []
    if resolved_model.source == "mock":
        provider_warnings.append(
            ProviderWarning(source="model", message="Using mock model fallback because backend/.env is incomplete.", severity="medium")
        )
    return {
        "trip_id": trip_id,
        "selected_model_id": resolved_model.model_id,
        "model_source": resolved_model.source,
        "query": query,
        "provider_warnings": provider_warnings,
        "created_at": now,
        "updated_at": now,
    }


def _extract_json_object(content: str) -> dict[str, object]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(cleaned[start : end + 1])


def _build_llm_prompt(query: str, parsed: dict[str, str | int | None]) -> str:
    destination = parsed.get("destination") or "the destination"
    duration_days = parsed.get("duration_days") or 3
    budget = parsed.get("budget") or "mid-range"
    style = parsed.get("style") or "balanced"
    return (
        "Create a realistic travel itinerary using only your own knowledge. "
        "Do not mention external tools. Return strict JSON only with this shape: "
        "{\"plan_summary\":{\"headline\":\"\",\"body\":\"\",\"highlights\":[\"\",\"\"]},"
        "\"days\":[{\"theme\":\"\",\"events\":[{\"start_time\":\"08:00\",\"end_time\":\"09:30\","
        "\"title\":\"\",\"location\":\"\",\"travel_time_from_previous\":\"10 min\","
        "\"cost_estimate\":\"$20\",\"description\":\"\",\"risk_flags\":[\"\"]}]}],"
        "\"budget_summary\":{\"trip_total_estimate\":\"$480\",\"current_day_estimate\":\"$120\","
        "\"budget_status\":\"on_track\"},"
        "\"map_preview\":{\"route_label\":\"\",\"stops\":[\"\",\"\"],\"total_transit_time\":\"1h 00m\"}}. "
        f"User request: {query}\n"
        f"Destination: {destination}\n"
        f"Duration days: {duration_days}\n"
        f"Budget: {budget}\n"
        f"Style: {style}\n"
        "Make exactly one day object per travel day. Each day should have 4 events."
    )


def _trip_from_fallback(
    *,
    query: str,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
) -> TripState:
    destination = str(parsed["destination"])
    duration_days = int(parsed["duration_days"])
    budget = parsed.get("budget")
    style = parsed.get("style")
    timeline_days = [
        _build_day(index, destination, style if isinstance(style, str) else None, budget if isinstance(budget, str) else None)
        for index in range(duration_days)
    ]
    trip_total = f"${duration_days * 120}"
    day_total = "$120"
    provider_warnings = list(base_fields["provider_warnings"])
    if base_fields["model_source"] != "mock":
        provider_warnings.append(
            ProviderWarning(
                source="model",
                message="The model response could not be parsed, so a local fallback itinerary was used.",
                severity="medium",
            )
        )
    image_references = _enrich_visuals(query, timeline_days)
    if not image_references:
        provider_warnings.append(
            ProviderWarning(
                source="visual_search",
                message="No image matches were found for the current itinerary, so local fallback images are shown.",
                severity="low",
            )
        )
    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    view_state = "partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready"
    return TripState(
        **trip_fields,
        view_state=view_state,
        plan_summary=PlanSummary(
            headline=f"{duration_days}-day {destination} plan ready",
            body="The itinerary is grouped by area, keeps transit bounded, and leaves clear decision points for revisions.",
            highlights=["Low Transit", "Structured Timeline", "Budget Aware"],
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=BudgetSummary(
            trip_total_estimate=trip_total,
            current_day_estimate=day_total,
            budget_status="on_track" if budget != "luxury" else "watch",
        ),
        memory_summary=MemorySummary(
            fixed_anchors=["Hotel check-in"],
            open_constraints=["Add transport bookings"] if base_fields["model_source"] == "mock" else [],
            user_preferences=[value for value in [style, budget] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="itinerary_generation",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=f"{destination} central loop",
            stops=[event.location for event in timeline_days[0].events[:3]],
            total_transit_time="1h 05m",
            image_references=image_references,
        ),
    )


def _trip_from_model(
    *,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
    model_payload: dict[str, object],
) -> TripState:
    duration_days = int(parsed["duration_days"])
    days_payload = model_payload.get("days")
    if not isinstance(days_payload, list) or len(days_payload) < duration_days:
        raise ValueError("Model did not return enough day plans.")

    timeline_days: list[DayPlan] = []
    for day_index in range(duration_days):
        raw_day = days_payload[day_index] if day_index < len(days_payload) else {}
        raw_events = raw_day.get("events") if isinstance(raw_day, dict) else []
        events: list[TimelineEvent] = []
        if isinstance(raw_events, list):
            for event_index, raw_event in enumerate(raw_events[:4]):
                if not isinstance(raw_event, dict):
                    continue
                events.append(
                    TimelineEvent(
                        id=f"d{day_index + 1}-e{event_index + 1}",
                        start_time=str(raw_event.get("start_time", f"{8 + event_index * 2:02d}:00")),
                        end_time=str(raw_event.get("end_time", f"{9 + event_index * 2:02d}:00")),
                        title=str(raw_event.get("title", f"Activity {event_index + 1}")),
                        location=str(raw_event.get("location", "Recommended area")),
                        travel_time_from_previous=str(raw_event.get("travel_time_from_previous", "15 min")),
                        cost_estimate=str(raw_event.get("cost_estimate")) if raw_event.get("cost_estimate") is not None else None,
                        description=str(raw_event.get("description", "A suggested stop based on your selected constraints.")),
                        image_url=SAMPLE_IMAGES[(day_index + event_index) % len(SAMPLE_IMAGES)],
                        risk_flags=[str(flag) for flag in raw_event.get("risk_flags", []) if isinstance(flag, (str, int, float))],
                    )
                )
        if not events:
            raise ValueError("Model returned an empty day.")
        theme = "Highlights"
        if isinstance(raw_day, dict) and raw_day.get("theme") is not None:
            theme = str(raw_day["theme"])
        timeline_days.append(
            DayPlan(day_index=day_index, title=f"Day {day_index + 1}", theme=theme, events=events)
        )

    summary_payload = model_payload.get("plan_summary", {})
    if not isinstance(summary_payload, dict):
        summary_payload = {}
    budget_payload = model_payload.get("budget_summary", {})
    if not isinstance(budget_payload, dict):
        budget_payload = {}
    map_payload = model_payload.get("map_preview", {})
    if not isinstance(map_payload, dict):
        map_payload = {}
    budget_status = str(budget_payload.get("budget_status", "on_track"))
    if budget_status not in {"on_track", "watch", "over"}:
        budget_status = "watch"
    image_references = _enrich_visuals(base_fields["query"], timeline_days)
    provider_warnings = list(base_fields["provider_warnings"])
    if not image_references:
        provider_warnings.append(
            ProviderWarning(
                source="visual_search",
                message="No image matches were found for the current itinerary, so local fallback images are shown.",
                severity="low",
            )
        )
    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    return TripState(
        **trip_fields,
        view_state="partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready",
        plan_summary=PlanSummary(
            headline=str(summary_payload.get("headline", f"{duration_days}-day trip plan ready")),
            body=str(summary_payload.get("body", "A structured itinerary generated by the selected model.")),
            highlights=[str(item) for item in summary_payload.get("highlights", []) if isinstance(item, (str, int, float))][:4],
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=BudgetSummary(
            trip_total_estimate=str(budget_payload.get("trip_total_estimate", f"${duration_days * 120}")),
            current_day_estimate=str(budget_payload.get("current_day_estimate", "$120")),
            budget_status=budget_status,
        ),
        memory_summary=MemorySummary(
            fixed_anchors=["Hotel check-in"],
            open_constraints=[],
            user_preferences=[value for value in [parsed.get("style"), parsed.get("budget")] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="model_generated",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=str(map_payload.get("route_label", "Suggested route")),
            stops=[str(item) for item in map_payload.get("stops", []) if isinstance(item, (str, int, float))][:6],
            total_transit_time=str(map_payload.get("total_transit_time", "1h 00m")),
            image_references=image_references,
        ),
    )


def build_trip_state(
    query: str,
    resolved_model: ResolvedModelConfig,
    existing_trip_id: str | None = None,
    model_client: ModelApiClient | None = None,
) -> TripState:
    parsed = parse_intent(query)
    questions = build_clarification_questions(parsed)
    now = datetime.now(timezone.utc).isoformat()
    trip_id = existing_trip_id or uuid4().hex
    base_fields = _base_trip_fields(trip_id=trip_id, now=now, query=query, resolved_model=resolved_model)

    if questions:
        return TripState(
            **base_fields,
            view_state="needs_clarification",
            plan_summary=PlanSummary(
                headline="Need a few details before building the trip",
                body="I can avoid unnecessary tool calls once destination, duration, and budget are confirmed.",
                highlights=["Clarification First", "Lower Latency"],
            ),
            clarification_questions=questions,
            timeline_days=[],
            budget_summary=BudgetSummary(
                trip_total_estimate="Pending details",
                current_day_estimate="Pending details",
                budget_status="watch",
            ),
            memory_summary=MemorySummary(
                fixed_anchors=[],
                open_constraints=[question.label for question in questions],
                user_preferences=[parsed["style"]] if parsed.get("style") else [],
                last_selected_model=resolved_model.model_id,
                route_mode="clarification_gate",
            ),
            conflict_warnings=[],
            map_preview=MapPreview(route_label="Route preview unlocks after clarification", stops=[], total_transit_time="Pending"),
        )

    if resolved_model.source == "mock" or model_client is None:
        return _trip_from_fallback(query=query, parsed=parsed, base_fields=base_fields)

    content = model_client.complete_json(
        resolved_model=resolved_model,
        system_prompt="You are a meticulous travel planner. Output valid JSON only, with no markdown fences.",
        user_prompt=_build_llm_prompt(query, parsed),
    )
    try:
        model_payload = _extract_json_object(content)
        return _trip_from_model(parsed=parsed, base_fields=base_fields, model_payload=model_payload)
    except (ValueError, TypeError, json.JSONDecodeError):
        return _trip_from_fallback(query=query, parsed=parsed, base_fields=base_fields)
