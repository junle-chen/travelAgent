from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
from urllib.parse import quote_plus
from uuid import uuid4

from app.agent.intent_parser import parse_intent
from app.agent.langchain_bridge import render_chat_prompts
from app.models.client import ModelApiClient
from app.schemas.domain import (
    BudgetSummary,
    ClarificationQuestion,
    DayPlan,
    MapPreview,
    MemorySummary,
    PlanSummary,
    ReferenceLink,
    RoutePoint,
    TimelineEvent,
    TravelLogistics,
    TripState,
    VisualReference,
)
from app.schemas.providers import ProviderWarning, ResolvedModelConfig
from app.tools.amap_live import AmapTravelService
from app.tools.concurrent_utils import parallel_call, parallel_map
from app.tools.image_lookup import ImageLookupService
from app.tools.serper_live import SerperTravelService
from app.tools.tavily_live import TavilyTravelService
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger("travel_agent.planner")

PLACEHOLDER_IMAGES = {
    "scenic": None,
    "food": None,
    "hotel": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80",
    "transport": "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?auto=format&fit=crop&w=1200&q=80",
    "default": None,
}
IMAGE_LOOKUP = ImageLookupService()
AMAP_TRAVEL = AmapTravelService()
SERPER_TRAVEL = SerperTravelService()
TAVILY_TRAVEL = TavilyTravelService()
MAINLAND_CITY_HINTS = {
    "beijing",
    "shanghai",
    "shenzhen",
    "guangzhou",
    "hangzhou",
    "xiamen",
    "chengdu",
    "nanjing",
    "suzhou",
    "wuhan",
    "changsha",
}
FALLBACK_ATTRACTIONS = {
    "beijing": [
        ("故宫博物院", "景山前街4号"),
        ("慕田峪长城", "怀柔区渤海镇慕田峪村"),
        ("南锣鼓巷", "东城区南锣鼓巷"),
        ("天坛公园", "东城区天坛东里甲1号"),
        ("颐和园", "海淀区新建宫门路19号"),
    ],
    "shenzhen": [
        ("平安金融中心观光层", "福田区益田路5033号"),
        ("莲花山公园", "福田区红荔路6030号"),
        ("深圳湾公园", "南山区滨海大道"),
        ("世界之窗", "南山区深南大道9037号"),
        ("华侨城创意文化园", "南山区锦绣北街2号"),
    ],
}
GENERIC_SCENIC_TITLES = {
    "neighborhood walk",
    "signature landmark",
    "park walk",
    "observation deck",
    "观景点",
    "a park一个公园",
}
FOOD_IMAGE_POOL = [
    "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1559339352-11d035aa65de?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1515003197210-e0cd71810b5f?auto=format&fit=crop&w=1200&q=80",
]


def _placeholder_image(kind: str) -> str | None:
    return PLACEHOLDER_IMAGES.get(kind, PLACEHOLDER_IMAGES["default"])


def _stable_index(seed: str, size: int) -> int:
    if size <= 0:
        return 0
    return sum(ord(char) for char in seed) % size


def _food_image_for(seed: str) -> str:
    return FOOD_IMAGE_POOL[_stable_index(seed, len(FOOD_IMAGE_POOL))]


def _classify_event(title: str) -> str:
    lowered = title.lower()
    if any(word in lowered for word in ["flight", "train", "transfer", "arrival", "return", "ferry"]):
        return "transport"
    if any(word in lowered for word in ["breakfast", "lunch", "dinner", "restaurant", "cafe", "market"]):
        return "food"
    if "hotel" in lowered or "check-in" in lowered:
        return "hotel"
    return "scenic"


def _sort_key(value: str) -> int:
    try:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return 0


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    # Fast-enough planar approximation for city-bound filtering.
    lon1, lat1 = a
    lon2, lat2 = b
    lat_scale = 111.0
    lon_scale = 111.0 * max(0.2, abs(math.cos(math.radians((lat1 + lat2) / 2.0))))
    return (((lon2 - lon1) * lon_scale) ** 2 + ((lat2 - lat1) * lat_scale) ** 2) ** 0.5


# Regional / multi-city destinations need a wider radius for POI filtering.
_WIDE_REGION_TOKENS = {
    "xinjiang", "新疆", "tibet", "西藏", "inner mongolia", "内蒙古",
    "yunnan", "云南", "sichuan", "四川", "qinghai", "青海",
    "gansu", "甘肃", "heilongjiang", "黑龙江", "guangxi", "广西",
    "north xinjiang", "south xinjiang", "northern xinjiang", "southern xinjiang",
    "北疆", "南疆", "川西", "滇西",
}

_REGION_ANCHORS: dict[str, tuple[float, float]] = {
    "新疆": (87.61, 43.82), # Urumqi
    "北疆": (87.61, 43.82),
    "南疆": (75.99, 39.47), # Kashgar
    "xinjiang": (87.61, 43.82),
    "西藏": (91.14, 29.64), # Lhasa
    "tibet": (91.14, 29.64),
    "内蒙古": (111.76, 40.84), # Hohhot
    "inner mongolia": (111.76, 40.84),
    "云南": (102.71, 25.04), # Kunming
    "yunnan": (102.71, 25.04),
    "四川": (104.06, 30.65), # Chengdu
    "sichuan": (104.06, 30.65),
    "青海": (101.77, 36.62), # Xining
    "qinghai": (101.77, 36.62),
    "甘肃": (103.82, 36.05), # Lanzhou
    "gansu": (103.82, 36.05),
    "黑龙江": (126.64, 45.75), # Harbin
    "heilongjiang": (126.64, 45.75),
    "广西": (108.36, 22.81), # Nanning
    "guangxi": (108.36, 22.81),
    "海南": (110.32, 20.03), # Haikou
    "hainan": (110.32, 20.03),
}

_CITY_ANCHORS: dict[str, tuple[float, float]] = {
    "beijing": (116.4074, 39.9042),
    "shanghai": (121.4737, 31.2304),
    "shenzhen": (114.0579, 22.5431),
    "guangzhou": (113.2644, 23.1291),
    "hangzhou": (120.1551, 30.2741),
    "xiamen": (118.0894, 24.4798),
    "chengdu": (104.0665, 30.5728),
    "nanjing": (118.7969, 32.0603),
    "suzhou": (120.5853, 31.2989),
    "wuhan": (114.3054, 30.5931),
    "changsha": (112.9388, 28.2282),
    "hong kong": (114.1694, 22.3193),
    "香港": (114.1694, 22.3193),
    "北京": (116.4074, 39.9042),
    "上海": (121.4737, 31.2304),
    "深圳": (114.0579, 22.5431),
    "广州": (113.2644, 23.1291),
    "杭州": (120.1551, 30.2741),
    "厦门": (118.0894, 24.4798),
    "成都": (104.0665, 30.5728),
}

def _resolve_destination_anchor(destination: str) -> tuple[float, float] | None:
    lowered = destination.lower().strip()
    compact = lowered.replace(" ", "")
    for key, anchor in _CITY_ANCHORS.items():
        key_lower = key.lower()
        if key_lower in lowered or key_lower.replace(" ", "") in compact:
            return anchor
    for key, anchor in _REGION_ANCHORS.items():
        if key in lowered:
            return anchor
    if not AMAP_TRAVEL.available():
        return None
    geocoded = AMAP_TRAVEL.geocode_city(destination)
    if geocoded:
        return geocoded
    poi = AMAP_TRAVEL.lookup_place(destination, destination)
    if poi and poi.latitude is not None and poi.longitude is not None:
        return (poi.longitude, poi.latitude)
    return None

def _destination_radius_km(destination: str) -> float:
    """Return max allowed distance (km) from destination center for POI validation."""
    lowered = destination.lower().strip()
    if any(token in lowered for token in _WIDE_REGION_TOKENS):
        return 1200.0
    return 80.0


def _validate_amap_poi(
    poi: Any,
    destination_center: tuple[float, float] | None,
    max_radius_km: float,
) -> bool:
    """Return True if the POI's coordinates are within max_radius_km of destination_center."""
    if poi is None:
        return False
    if poi.latitude is None or poi.longitude is None:
        return True  # No coordinates to check, pass through
    if destination_center is None:
        return True  # No anchor to compare, pass through
    dist = _distance_km(destination_center, (poi.longitude, poi.latitude))
    if dist > max_radius_km:
        logger.info(
            "[validate] skip out-of-region POI name=%s dist=%.0fkm max=%skm",
            getattr(poi, 'name', '?'), dist, max_radius_km,
        )
        return False
    return True


def _default_departure_dates(duration_days: int) -> tuple[datetime, datetime]:
    today = datetime.now(timezone.utc)
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    outbound = (today + timedelta(days=days_until_saturday)).replace(hour=8, minute=0, second=0, microsecond=0)
    inbound = outbound + timedelta(days=max(duration_days, 1))
    return outbound, inbound


def _choose_transport_mode(origin: str, destination: str) -> str:
    origin_lower = origin.lower()
    destination_lower = destination.lower()
    if origin == "Your city" or destination == "Custom Destination":
        return "Best available transfer"
    if any(token in origin_lower for token in ["hong kong", "tokyo", "singapore"]) or any(
        token in destination_lower for token in ["hong kong", "tokyo", "singapore"]
    ):
        return "Flight"
    if any(city in origin_lower for city in MAINLAND_CITY_HINTS) and any(city in destination_lower for city in MAINLAND_CITY_HINTS):
        return "High-speed rail"
    return "Flight"


def _format_schedule_range(date_value: datetime, schedule: str | None, *, approximate: bool) -> str:
    label = date_value.strftime("%a, %b %d")
    if schedule:
        return f"{label} {schedule}"
    if approximate:
        return f"{label} approximate"
    return label


def _normalize_defaults(parsed: dict[str, str | int | None], *, interaction_mode: str) -> dict[str, str | int | None]:
    normalized = dict(parsed)
    if normalized.get("duration_days") is None:
        normalized["duration_days"] = 3
    if normalized.get("budget") is None and interaction_mode == "direct":
        normalized["budget"] = "mid-range"
    if normalized.get("style") is None and interaction_mode == "direct":
        normalized["style"] = "Balanced"
    if normalized.get("travelers") is None:
        normalized["travelers"] = 1 if interaction_mode == "direct" else None
    if normalized.get("origin") is None:
        normalized["origin"] = "Your city" if interaction_mode == "direct" else None
    if normalized.get("destination") is None and interaction_mode == "direct":
        normalized["destination"] = "Custom Destination"
    return normalized


def _planning_questions(parsed: dict[str, str | int | None]) -> list[ClarificationQuestion]:
    questions: list[ClarificationQuestion] = []
    if parsed.get("origin") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="origin",
                label="Start",
                question="Where are you starting from?",
                suggestions=["Shenzhen", "Guangzhou", "Singapore"],
            )
        )
    if parsed.get("destination") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="destination",
                label="Destination",
                question="Where do you want to go?",
                suggestions=["Hong Kong", "Tokyo", "Hangzhou"],
            )
        )
    if parsed.get("travelers") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="travelers",
                label="Travelers",
                question="How many people are traveling?",
                suggestions=["1", "2", "3", "4"],
            )
        )
    if parsed.get("budget") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="budget",
                label="Budget",
                question="What total budget should I aim for?",
                suggestions=["$500", "$1000", "$2000", "$3000"],
            )
        )
    if parsed.get("style") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="style",
                label="Preference",
                question="What travel style do you prefer?",
                suggestions=["Relaxed", "Food focused", "Family friendly", "Packed"],
            )
        )
    return questions[:5]


def _build_day(day_index: int, destination: str, style: str | None, budget: str | None) -> DayPlan:
    theme = ["Arrival & Orientation", "Neighborhood Highlights", "Local Culture", "Flexible Favorites"][day_index % 4]
    base_hour = 9
    events: list[TimelineEvent] = []
    labels = [
        ("Neighborhood Walk", f"{destination} center", "15 min", "$0", "Start with a walkable anchor zone to reduce transit overhead."),
        ("Signature Landmark", f"{destination} landmark", "18 min", "$25", "Prioritize one headline attraction at a comfortable pace."),
        ("Local Culture Stop", f"{destination} historic district", "15 min", "$15", "Layer in a second meaningful stop instead of routine meal filler."),
    ]
    if style and "food" in style.lower():
        labels.append(
            ("Standout Food Pick", f"{destination} dining district", "12 min", "$30", "Include one worthwhile food stop because the trip is food-led.")
        )
    for index, (label, location, travel, cost, description) in enumerate(labels):
        if budget == "budget" and cost != "$0":
            cost = "$15"
        elif budget == "luxury":
            cost = "$60"
        start_hour = base_hour + index * 3
        events.append(
            TimelineEvent(
                id=f"d{day_index + 1}-e{index + 1}",
                start_time=f"{start_hour:02d}:00",
                end_time=f"{start_hour + 2:02d}:00",
                title=label,
                location=location,
                travel_time_from_previous=travel,
                cost_estimate=cost,
                description=description if style != "Packed pace" else "A denser cadence tuned for a high-energy day.",
                image_url=_placeholder_image(_classify_event(label)) if _classify_event(label) in {"scenic", "food"} else None,
                risk_flags=[],
            )
        )
    return DayPlan(day_index=day_index, title=f"Day {day_index + 1}", theme=theme, events=events)


def _default_logistics(parsed: dict[str, str | int | None]) -> TravelLogistics:
    destination = str(parsed.get("destination") or "Custom Destination")
    travelers = int(parsed.get("travelers") or 1)
    origin = str(parsed.get("origin") or "Your city")
    transport_mode = _choose_transport_mode(origin, destination)
    outbound_date, return_date = _default_departure_dates(int(parsed.get("duration_days") or 3))
    if transport_mode == "High-speed rail":
        outbound = f"High-speed rail to {destination}"
        inbound = f"High-speed rail back to {origin}"
    elif transport_mode == "Best available transfer":
        outbound = f"Best available transfer to {destination}"
        inbound = f"Return transfer from {destination}"
    else:
        outbound = f"Flight to {destination}"
        inbound = f"Flight back to {origin}"
    hotel_name = f"{destination} Central Hotel"
    return TravelLogistics(
        origin=origin,
        destination=destination,
        travelers=travelers,
        outbound_transport=outbound,
        return_transport=inbound,
        outbound_schedule=_format_schedule_range(outbound_date, None, approximate=True),
        return_schedule=_format_schedule_range(return_date, None, approximate=True),
        hotel_name=hotel_name,
    )


def _search_attraction_candidates(destination: str) -> list[tuple[str, str]]:
    service = _active_search_service()
    if not service:
        return []
    results = service.search(f"{destination} famous attractions landmarks travel guide", num=5)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in results:
        if not _result_mentions_destination(destination, _search_item_text(item)):
            continue
        headline = item.title.split(" - ")[0].split(" | ")[0].strip()
        headline = headline.replace(f"{destination} ", "").strip()
        if not headline or len(headline) < 2:
            continue
        lowered = headline.lower()
        if lowered in seen:
            continue
        if any(token in lowered for token in ["travel guide", "itinerary", "tripadvisor", "best things"]):
            continue
        seen.add(lowered)
        candidates.append((headline, destination))
    return candidates[:3]


def _search_food_candidates(destination: str) -> list[tuple[str, str]]:
    service = _active_search_service()
    if not service:
        return []
    results = service.search(f"{destination} best local restaurants famous food", num=4)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in results:
        if not _result_mentions_destination(destination, _search_item_text(item)):
            continue
        headline = item.title.split(" - ")[0].split(" | ")[0].strip()
        if not headline or len(headline) < 2:
            continue
        lowered = headline.lower()
        if lowered in seen:
            continue
        if any(token in lowered for token in ["tripadvisor", "best", "guide", "restaurants in"]):
            continue
        seen.add(lowered)
        candidates.append((headline, destination))
    return candidates[:2]


def _active_search_service() -> Any | None:
    if SERPER_TRAVEL.available():
        return SERPER_TRAVEL
    if TAVILY_TRAVEL.available():
        return TAVILY_TRAVEL
    return None


def _search_item_text(item: Any) -> str:
    title = str(getattr(item, "title", "") or "")
    snippet = str(getattr(item, "snippet", "") or "")
    return f"{title} {snippet}".strip()


def _result_mentions_destination(destination: str, text: str) -> bool:
    destination_lower = destination.lower().strip()
    normalized_text = text.lower().strip()
    if not destination_lower:
        return True
    compact_destination = destination_lower.replace(" ", "")
    compact_text = normalized_text.replace(" ", "")
    if destination_lower in normalized_text or compact_destination in compact_text:
        return True
    return False


def _extract_schedule_from_results(results: list[Any]) -> str | None:
    for item in results:
        combined = _search_item_text(item)
        times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", combined)
        if len(times) >= 2:
            return f"{times[0]} - {times[1]}"
        if len(times) == 1:
            return times[0]
    return None


def _extract_price_from_results(results: list[Any]) -> str | None:
    for item in results:
        combined = _search_item_text(item)
        match = re.search(r"(?:HK\$|US\$|\$|CNY\s?|RMB\s?|¥)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", combined, re.IGNORECASE)
        if match:
            symbol_match = re.search(r"(HK\$|US\$|\$|CNY\s?|RMB\s?|¥)", combined, re.IGNORECASE)
            symbol = symbol_match.group(1).strip() if symbol_match else "$"
            return f"{symbol}{match.group(1)}"
    return None


def _is_valid_reference_url(url: str) -> bool:
    lowered = url.strip().lower()
    if not lowered.startswith("http"):
        return False
    if "example.com" in lowered:
        return False
    if "xiaohongshu.com/search_result" in lowered:
        return False
    return True


def _sanitize_reference_links(links: list[ReferenceLink]) -> list[ReferenceLink]:
    sanitized: list[ReferenceLink] = []
    seen_urls: set[str] = set()
    for link in links:
        if not _is_valid_reference_url(link.url):
            continue
        if link.url in seen_urls:
            continue
        seen_urls.add(link.url)
        sanitized.append(link)
    return sanitized


def _merge_reference_links(*groups: list[ReferenceLink]) -> list[ReferenceLink]:
    merged: list[ReferenceLink] = []
    for group in groups:
        merged.extend(group)
    return _sanitize_reference_links(merged)


def _build_search_context(
    destination: str, origin: str, style: str | None
) -> tuple[str, dict[str, list], list[tuple[str, str]]]:
    """Return (context_string, amap_candidates, attraction_candidates).

    Runs Amap, Serper searches **in parallel** to cut wall-clock time.
    """
    # ---- kick off parallel tasks ------------------------------------------------
    tasks: list[tuple] = []
    task_keys: list[str] = []
    search_service = _active_search_service()

    # 0: amap candidates
    if AMAP_TRAVEL.available():
        tasks.append((AMAP_TRAVEL.fetch_candidates, (destination,)))
        task_keys.append("amap")
    # 1: search attractions
    tasks.append((_search_attraction_candidates, (destination,)))
    task_keys.append("search_attractions")
    # 2: search food (conditionally)
    want_food = bool(style and "food" in style.lower())
    if want_food:
        tasks.append((_search_food_candidates, (destination,)))
        task_keys.append("search_food")
    # 3: transport search
    want_transport = bool(origin and destination and origin != "Your city")
    if want_transport and search_service:
        outbound_date, _ = _default_departure_dates(3)
        transport_keyword = "flight" if _choose_transport_mode(origin, destination) == "Flight" else "train"
        transport_query = f"{origin} to {destination} {outbound_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
        tasks.append((search_service.search, (transport_query, 2)))
        task_keys.append("transport")

    results = parallel_call(tasks) if tasks else []
    result_map = dict(zip(task_keys, results))

    # ---- assemble context string -----------------------------------------------
    amap_candidates: dict[str, list] = result_map.get("amap", {"hotels": [], "restaurants": [], "attractions": []})
    search_attraction_results: list[tuple[str, str]] = result_map.get("search_attractions", [])

    attraction_lines: list[str] = []
    food_lines: list[str] = []

    attraction_lines.extend([f"- {poi.name} ({poi.address})" for poi in amap_candidates.get("attractions", [])[:5]])
    if want_food:
        food_lines.extend([f"- {poi.name} ({poi.address})" for poi in amap_candidates.get("restaurants", [])[:3]])

    attraction_lines.extend([f"- {name} ({address})" for name, address in search_attraction_results])
    if want_food:
        food_lines.extend([f"- {name} ({address})" for name, address in result_map.get("search_food", [])])

    if not attraction_lines:
        fallback = FALLBACK_ATTRACTIONS.get(destination.lower(), [])
        attraction_lines.extend([f"- {name} ({address})" for name, address in fallback[:4]])

    transport_lines: list[str] = []
    if want_transport:
        for item in result_map.get("transport", []):
            transport_lines.append(f"- {item.title}: {item.snippet}")

    sections = [
        "Grounding context from search results and map providers:",
        "Attractions:",
        *(attraction_lines or ["- None found"]),
    ]
    if food_lines:
        sections.extend(["Food:", *food_lines])
    if transport_lines:
        sections.extend(["Transport:", *transport_lines])
    return "\n".join(sections), amap_candidates, search_attraction_results


def _is_generic_scenic_event(event: TimelineEvent) -> bool:
    lowered = event.title.lower()
    return lowered in GENERIC_SCENIC_TITLES or any(token in lowered for token in ["park walk", "observation deck", "scenic stop"])


def _apply_amap_candidates(
    destination: str,
    timeline_days: list[DayPlan],
    logistics: TravelLogistics,
    *,
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
) -> list[ProviderWarning]:
    warnings: list[ProviderWarning] = []
    if not AMAP_TRAVEL.available() and prefetched_amap is None:
        return warnings

    candidates = prefetched_amap if prefetched_amap is not None else AMAP_TRAVEL.fetch_candidates(destination)

    # --- Resolve a destination anchor for POI validation ---
    destination_center = _resolve_destination_anchor(destination)
    max_radius = _destination_radius_km(destination)

    # --- Filter Amap POIs to only those near the destination ---
    hotels = [poi for poi in candidates.get("hotels", []) if _validate_amap_poi(poi, destination_center, max_radius)]
    restaurants = [poi for poi in candidates.get("restaurants", []) if _validate_amap_poi(poi, destination_center, max_radius)]
    attractions = [poi for poi in candidates.get("attractions", []) if _validate_amap_poi(poi, destination_center, max_radius)]

    destination_key = destination.lower()
    fallback = FALLBACK_ATTRACTIONS.get(destination_key, [])
    search_candidates = prefetched_attractions if prefetched_attractions is not None else _search_attraction_candidates(destination)
    attraction_pool: list[tuple[str, str]] = []
    for poi in attractions:
        attraction_pool.append((poi.name, poi.address))
    for name, address in search_candidates:
        attraction_pool.append((name, address))
    if not attraction_pool:
        for name, address in fallback:
            attraction_pool.append((name, address))

    deduped_attractions: list[tuple[str, str]] = []
    seen_attractions: set[str] = set()
    for name, address in attraction_pool:
        key = name.strip().lower()
        if not key or key in seen_attractions:
            continue
        seen_attractions.add(key)
        deduped_attractions.append((name, address))

    if hotels:
        logistics.hotel_name = hotels[0].name
        hotel_point = hotels[0]
    else:
        hotel_point = None

    restaurant_index = 0
    attraction_index = 0
    for day in timeline_days:
        for event in day.events:
            kind = _classify_event(event.title)
            if kind == "food" and restaurant_index < len(restaurants):
                event.title = restaurants[restaurant_index].name
                event.location = restaurants[restaurant_index].address
                event.description = f"A worthwhile local food stop at {restaurants[restaurant_index].name}."
                event.latitude = restaurants[restaurant_index].latitude
                event.longitude = restaurants[restaurant_index].longitude
                restaurant_index += 1
            elif kind == "scenic":
                if _is_generic_scenic_event(event) and attraction_index < len(deduped_attractions):
                    event.title = deduped_attractions[attraction_index][0]
                    event.location = deduped_attractions[attraction_index][1]
                    if attraction_index < len(attractions):
                        event.latitude = attractions[attraction_index].latitude
                        event.longitude = attractions[attraction_index].longitude
                    attraction_index += 1
                elif attraction_index < len(deduped_attractions) and event.location.lower().endswith("landmark"):
                    event.title = deduped_attractions[attraction_index][0]
                    event.location = deduped_attractions[attraction_index][1]
                    if attraction_index < len(attractions):
                        event.latitude = attractions[attraction_index].latitude
                        event.longitude = attractions[attraction_index].longitude
                    attraction_index += 1
            elif kind == "hotel":
                event.location = logistics.hotel_name
                if hotel_point:
                    event.latitude = hotel_point.latitude
                    event.longitude = hotel_point.longitude

    if not hotels and not restaurants and not deduped_attractions:
        warnings.append(
            ProviderWarning(
                source="amap",
                message="Amap did not return candidate POIs for this destination, so the planner used model-only suggestions.",
                severity="low",
            )
        )
    return warnings


def _hydrate_event_geocodes(destination: str, timeline_days: list[DayPlan], logistics: TravelLogistics) -> None:
    if not AMAP_TRAVEL.available():
        return
    destination_center = _resolve_destination_anchor(destination)
    max_radius = _destination_radius_km(destination)
    events_to_geocode: list[tuple[TimelineEvent, list[str]]] = []
    for day in timeline_days:
        for event in day.events:
            if (
                destination_center is not None
                and event.latitude is not None
                and event.longitude is not None
                and _distance_km(destination_center, (event.longitude, event.latitude)) > max_radius
            ):
                logger.info(
                    "[geocode] reset out-of-region existing point destination=%s event=%s location=%s",
                    destination,
                    event.title,
                    event.location,
                )
                event.latitude = None
                event.longitude = None
            if event.latitude is not None and event.longitude is not None:
                continue
            variants: list[str] = []
            if event.location and event.location != logistics.hotel_name:
                variants.append(event.location)
                variants.append(f"{destination} {event.location}")
            variants.append(event.title)
            variants.append(f"{destination} {event.title}")
            deduped_variants = [value for value in dict.fromkeys(item.strip() for item in variants if item and item.strip())]
            events_to_geocode.append((event, deduped_variants))
    if not events_to_geocode:
        return
    unique_keywords = list(dict.fromkeys(keyword for _, keywords in events_to_geocode for keyword in keywords))
    lookup_map: dict[str, Any] = {}
    if unique_keywords:
        pois = parallel_map(lambda keyword: AMAP_TRAVEL.lookup_place(destination, keyword), unique_keywords)
        lookup_map = {keyword: poi for keyword, poi in zip(unique_keywords, pois)}
    resolved_count = 0
    unresolved: list[str] = []
    for event, keywords in events_to_geocode:
        matched = False
        for keyword in keywords:
            poi = lookup_map.get(keyword)
            if poi and poi.latitude is not None and poi.longitude is not None:
                if destination_center is not None:
                    point = (poi.longitude, poi.latitude)
                    if _distance_km(destination_center, point) > max_radius:
                        logger.info(
                            "[geocode] skip out-of-region point destination=%s keyword=%s dist=%.0fkm max=%skm",
                            destination,
                            keyword,
                            _distance_km(destination_center, point),
                            max_radius,
                        )
                        continue
                event.latitude = poi.latitude
                event.longitude = poi.longitude
                resolved_count += 1
                matched = True
                break
        if not matched and keywords:
            unresolved.append(keywords[0])
    logger.info(
        "[geocode] destination=%s resolved=%s/%s unresolved=%s",
        destination,
        resolved_count,
        len(events_to_geocode),
        unresolved[:5],
    )


def _build_day_routes(destination: str, timeline_days: list[DayPlan]) -> None:
    destination_center = _resolve_destination_anchor(destination)
    max_radius = _destination_radius_km(destination)
    day_data: list[tuple[DayPlan, list[tuple[float, float]], list[str]]] = []
    for day in timeline_days:
        ordered_points: list[tuple[float, float]] = []
        labels: list[str] = []
        for event in day.events:
            if _classify_event(event.title) == "transport":
                continue
            if event.latitude is None or event.longitude is None:
                continue
            point = (event.longitude, event.latitude)
            if destination_center is not None and _distance_km(destination_center, point) > max_radius:
                logger.info(
                    "[route] skip out-of-region route point destination=%s event=%s location=%s",
                    destination,
                    event.title,
                    event.location,
                )
                continue
            if ordered_points and ordered_points[-1] == point:
                continue
            ordered_points.append(point)
            labels.append(event.title)
        day_data.append((day, ordered_points, labels))

    def _build_route(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return AMAP_TRAVEL.build_route_points(pts) if pts else []

    route_results = parallel_call([(_build_route, (pts,)) for _, pts, _ in day_data])

    for (day, ordered_points, labels), route_points in zip(day_data, route_results):
        if route_points:
            day.route_points = [
                RoutePoint(
                    label=labels[min(index, len(labels) - 1)],
                    latitude=point[1],
                    longitude=point[0],
                )
                for index, point in enumerate(route_points)
            ]
        else:
            day.route_points = [
                RoutePoint(label=labels[index], latitude=point[1], longitude=point[0])
                for index, point in enumerate(ordered_points)
            ]


def _reference_links(destination: str) -> list[ReferenceLink]:
    service = _active_search_service()
    safe = quote_plus(destination)
    query_plan = [
        (f"{destination} travel blog itinerary", "Travel blog"),
        (f"{destination} trip report 3 day itinerary", "Trip report"),
        (f"site:reddit.com/r/travel {destination} itinerary", "Traveler forum"),
    ]
    links: list[ReferenceLink] = []
    if service:
        search_results = parallel_call([(service.search, (query, 2)) for query, _ in query_plan])
        for (_, label), results in zip(query_plan, search_results):
            for item in results:
                links.append(ReferenceLink(title=item.title, url=item.link, label=label))
        links = _sanitize_reference_links(links)
        if links:
            return links[:6]
    return [
        ReferenceLink(
            title=f"{destination} travel blog search",
            url=f"https://www.google.com/search?q={safe}+travel+blog+itinerary",
            label="Travel blog",
        ),
        ReferenceLink(
            title=f"{destination} trip report search",
            url=f"https://www.google.com/search?q={safe}+trip+report+itinerary",
            label="Trip report",
        ),
        ReferenceLink(
            title=f"{destination} traveler forum search",
            url=f"https://www.google.com/search?q={safe}+reddit+travel+itinerary",
            label="Traveler forum",
        ),
    ]


def _apply_live_search(
    logistics: TravelLogistics,
    timeline_days: list[DayPlan],
) -> tuple[list[ReferenceLink], list[ProviderWarning]]:
    warnings: list[ProviderWarning] = []
    references: list[ReferenceLink] = []
    schedule_service = _active_search_service()
    if not schedule_service:
        return references, warnings

    duration_days = max(len(timeline_days), 1)
    outbound_date, return_date = _default_departure_dates(duration_days)
    transport_keyword = "flight" if "flight" in logistics.outbound_transport.lower() else "train"
    transport_site = "google.com/travel/flights" if transport_keyword == "flight" else "12306"
    outbound_query = (
        f"site:{transport_site} {logistics.origin} to {logistics.destination} "
        f"{outbound_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
    )
    return_query = (
        f"site:{transport_site} {logistics.destination} to {logistics.origin} "
        f"{return_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
    )
    scenic_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "scenic"]
    food_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "food"]

    tasks: list[tuple[Any, tuple[Any, ...]]] = [
        (schedule_service.search, (outbound_query, 2)),
        (schedule_service.search, (return_query, 2)),
        (schedule_service.search, (f"{logistics.hotel_name} hotel nightly price booking reviews", 2)),
    ]

    if transport_keyword != "flight":
        alternate_flight_outbound = (
            f"site:google.com/travel/flights {logistics.origin} to {logistics.destination} "
            f"{outbound_date.strftime('%Y-%m-%d')} flight departure arrival time"
        )
        alternate_flight_return = (
            f"site:google.com/travel/flights {logistics.destination} to {logistics.origin} "
            f"{return_date.strftime('%Y-%m-%d')} flight departure arrival time"
        )
        tasks.extend(
            [
                (schedule_service.search, (alternate_flight_outbound, 1)),
                (schedule_service.search, (alternate_flight_return, 1)),
            ]
        )

    for event in scenic_events[:2]:
        tasks.append((schedule_service.search, (f"{event.title} {logistics.destination} tickets opening hours", 1)))
    for event in food_events:
        tasks.append((schedule_service.search, (f"{event.title} {event.location} menu reviews", 2)))

    task_results = parallel_call(tasks)
    result_index = 0
    outbound_results = task_results[result_index]
    result_index += 1
    return_results = task_results[result_index]
    result_index += 1
    hotel_results = task_results[result_index]
    result_index += 1
    outbound_schedule = _extract_schedule_from_results(outbound_results)
    return_schedule = _extract_schedule_from_results(return_results)
    if outbound_schedule:
        logistics.outbound_schedule = _format_schedule_range(outbound_date, outbound_schedule, approximate=False)
    if return_schedule:
        logistics.return_schedule = _format_schedule_range(return_date, return_schedule, approximate=False)

    outbound_label = "Flight search" if transport_keyword == "flight" else "Rail search"
    return_label = "Return flight" if transport_keyword == "flight" else "Return rail"
    for item in outbound_results[:1]:
        references.append(ReferenceLink(title=item.title, url=item.link, label=outbound_label))
    for item in return_results[:1]:
        references.append(ReferenceLink(title=item.title, url=item.link, label=return_label))

    if transport_keyword != "flight":
        flight_results = task_results[result_index]
        result_index += 1
        flight_return_results = task_results[result_index]
        result_index += 1
        for item in flight_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="Alternate flights"))
        for item in flight_return_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="Return flights"))

    hotel_price = _extract_price_from_results(hotel_results)
    if hotel_price:
        for day in timeline_days:
            for event in day.events:
                if "hotel" in event.title.lower():
                    event.cost_estimate = hotel_price
                    break
    else:
        for day in timeline_days:
            for event in day.events:
                if "hotel" in event.title.lower() and not event.cost_estimate:
                    event.cost_estimate = "approximate"
                    break
    for item in hotel_results[:1]:
        references.append(ReferenceLink(title=item.title, url=item.link, label="Hotel search"))

    for event in scenic_events[:2]:
        poi_results = task_results[result_index]
        result_index += 1
        for item in poi_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="POI details"))

    for event in food_events:
        food_results = task_results[result_index]
        result_index += 1
        price = _extract_price_from_results(food_results)
        if price:
            event.cost_estimate = price
        elif not event.cost_estimate:
            event.cost_estimate = "approximate"
        for item in food_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="Food reviews"))

    return _sanitize_reference_links(references), warnings


def _ensure_cost_estimates(timeline_days: list[DayPlan]) -> None:
    for day in timeline_days:
        for event in day.events:
            if not event.cost_estimate:
                event.cost_estimate = "approximate"


def _assign_food_images(timeline_days: list[DayPlan]) -> None:
    food_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "food"]
    for index, event in enumerate(food_events):
        if not event.image_url:
            event.image_url = FOOD_IMAGE_POOL[index % len(FOOD_IMAGE_POOL)]


def _inject_logistics_events(timeline_days: list[DayPlan], logistics: TravelLogistics) -> None:
    if not timeline_days:
        return
    first_day = timeline_days[0]
    last_day = timeline_days[-1]

    if not any("arrival" in event.title.lower() or "flight" in event.title.lower() for event in first_day.events):
        first_day.events.append(
            TimelineEvent(
                id=f"d{first_day.day_index + 1}-arrival",
                start_time="07:00",
                end_time="08:30",
                title="Arrival Transfer",
                location=f"{logistics.origin} to {logistics.destination}",
                travel_time_from_previous="-",
                cost_estimate=None,
                description=f"Take the main inbound leg via {logistics.outbound_transport}.",
                image_url=None,
                risk_flags=[],
            )
        )
    if not any("hotel" in event.title.lower() or "check-in" in event.title.lower() for event in first_day.events):
        first_day.events.append(
            TimelineEvent(
                id=f"d{first_day.day_index + 1}-hotel",
                start_time="15:00",
                end_time="15:45",
                title="Hotel Check-in",
                location=logistics.hotel_name,
                travel_time_from_previous="15 min",
                cost_estimate=None,
                description=f"Check in at {logistics.hotel_name} and reset before the next stop.",
                image_url=None,
                risk_flags=[],
            )
        )
    if not any("return" in event.title.lower() or "departure" in event.title.lower() for event in last_day.events):
        last_day.events.append(
            TimelineEvent(
                id=f"d{last_day.day_index + 1}-return",
                start_time="19:00",
                end_time="21:00",
                title="Return Transfer",
                location=f"{logistics.destination} to {logistics.origin}",
                travel_time_from_previous="25 min",
                cost_estimate=None,
                description=f"Wrap the trip with the outbound leg home via {logistics.return_transport}.",
                image_url=None,
                risk_flags=[],
            )
        )

    for day in timeline_days:
        day.events.sort(key=lambda event: _sort_key(event.start_time))


def _search_event_visual(destination: str, event: TimelineEvent) -> VisualReference | None:
    kind = _classify_event(event.title)
    if kind not in {"scenic", "food"}:
        event.image_url = None
        return None
    if kind == "food":
        if not event.image_url:
            event.image_url = _food_image_for(f"{destination}-{event.title}-{event.location}")
        return None

    candidates = [
        f"\"{event.title}\" {destination} landmark",
        event.title,
        f"{destination} {event.title}",
    ]

    for candidate in candidates:
        reference = IMAGE_LOOKUP.verified_image(candidate)
        if reference and reference.image_url:
            event.image_url = reference.image_url
            return VisualReference(title=event.title, image_url=reference.image_url, source_url=reference.source_url)

    event.image_url = None
    return None


def _enrich_visuals(destination: str, timeline_days: list[DayPlan]) -> list[VisualReference]:
    references: list[VisualReference] = []
    seen_urls: set[str] = set()
    pending_events: list[TimelineEvent] = []
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "scenic":
                continue
            pending_events.append(event)
            if len(pending_events) >= 20:
                break
        if len(pending_events) >= 20:
            break
    if not pending_events:
        return references

    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    futures = {}
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="img-enrich") as pool:
        for event in pending_events:
            futures[pool.submit(_search_event_visual, destination, event)] = event
            
        for future in as_completed(futures):
            event = futures[future]
            try:
                # 15s timeout per image search chain (which tries up to 3 queries)
                res = future.result(timeout=15)
                if res and res.image_url:
                    if res.image_url not in seen_urls:
                        seen_urls.add(res.image_url)
                        references.append(res)
                        if len(references) >= 4:
                            return references
            except Exception as exc:
                # Assuming 'logger' is defined elsewhere in the module
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("[enrich] image search failed for event '%s': %s", event.title, exc)

    return references


def _base_trip_fields(
    *,
    trip_id: str,
    now: str,
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str,
) -> dict[str, object]:
    provider_warnings: list[ProviderWarning] = []
    if resolved_model.source == "mock":
        provider_warnings.append(
            ProviderWarning(source="model", message="Using mock model fallback because backend/.env is incomplete.", severity="medium")
        )
    return {
        "trip_id": trip_id,
        "interaction_mode": interaction_mode,
        "selected_model_id": resolved_model.model_id,
        "model_source": resolved_model.source,
        "query": query,
        "provider_warnings": provider_warnings,
        "created_at": now,
        "updated_at": now,
    }


def _parse_cost_amount(cost: str | None) -> float | None:
    if not cost:
        return None
    lowered = cost.strip().lower()
    if lowered in {"free", "$0", "0"}:
        return 0.0
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", cost)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _estimate_transport_one_way(logistics: TravelLogistics) -> float:
    lowered = logistics.outbound_transport.lower()
    if "flight" in lowered:
        return 220.0
    if "rail" in lowered or "train" in lowered:
        return 70.0
    if "ferry" in lowered:
        return 55.0
    return 90.0


def _estimate_budget_summary(
    parsed: dict[str, str | int | None],
    logistics: TravelLogistics,
    timeline_days: list[DayPlan],
) -> BudgetSummary:
    travelers = max(int(logistics.travelers or 1), 1)
    room_count = max((travelers + 1) // 2, 1)
    duration_days = max(len(timeline_days), 1)

    hotel_amount = None
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) == "hotel":
                hotel_amount = _parse_cost_amount(event.cost_estimate)
                if hotel_amount is not None:
                    break
        if hotel_amount is not None:
            break
    if hotel_amount is None:
        hotel_amount = 120.0

    event_totals_by_day: list[float] = []
    for day in timeline_days:
        day_total = 0.0
        for event in day.events:
            kind = _classify_event(event.title)
            amount = _parse_cost_amount(event.cost_estimate)
            if amount is None:
                if kind == "food":
                    amount = 18.0
                elif kind == "scenic":
                    amount = 25.0
                else:
                    amount = 0.0
            if kind in {"food", "scenic"}:
                day_total += amount * travelers
            elif kind == "hotel":
                day_total += amount * room_count
            else:
                day_total += amount
        event_totals_by_day.append(day_total)

    transport_total = _estimate_transport_one_way(logistics) * 2 * travelers
    hotel_total = hotel_amount * room_count * max(duration_days - 1, 1)
    event_total = sum(event_totals_by_day)
    trip_total_value = round(transport_total + hotel_total + event_total)
    current_day_value = round((event_totals_by_day[0] if event_totals_by_day else 0.0) + (hotel_amount * room_count))

    raw_budget = str(parsed.get("budget") or "").strip().lower()
    numeric_budget = _parse_cost_amount(raw_budget) if raw_budget else None
    if numeric_budget is not None:
        target = numeric_budget
    elif "budget" in raw_budget:
        target = 180.0 * travelers * duration_days + transport_total
    elif "luxury" in raw_budget:
        target = 420.0 * travelers * duration_days + transport_total
    else:
        target = 300.0 * travelers * duration_days + transport_total

    ratio = trip_total_value / max(target, 1.0)
    if ratio <= 1.0:
        status = "on_track"
    elif ratio <= 1.2:
        status = "watch"
    else:
        status = "over"

    return BudgetSummary(
        trip_total_estimate=f"${trip_total_value}",
        current_day_estimate=f"${current_day_value}",
        budget_status=status,
    )


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


def _merge_parsed(
    heuristic: dict[str, str | int | None],
    extracted: dict[str, str | int | None],
) -> dict[str, str | int | None]:
    merged = dict(heuristic)
    for key, value in extracted.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _extract_constraints_with_model(
    query: str,
    resolved_model: ResolvedModelConfig,
    model_client: ModelApiClient | None,
) -> dict[str, str | int | None]:
    if model_client is None or resolved_model.source == "mock":
        return {}

    prompt = (
        "Extract structured travel constraints from the user request. "
        "Return strict JSON only with this shape: "
        "{\"origin\":null,\"destination\":null,\"travelers\":null,\"budget\":null,"
        "\"style\":null,\"duration_days\":null}. "
        "Use null for unknown values. "
        "Budget should be a short string like \"$1200\", \"mid-range\", \"budget\", or \"luxury\". "
        "Style should be a short label like \"Relaxed\", \"Food focused\", \"Family friendly\", or \"Packed\". "
        "Destination and origin can be any city or place name."
    )
    try:
        raw = model_client.complete_json(
            resolved_model=resolved_model,
            system_prompt="You extract travel constraints. Output valid JSON only.",
            user_prompt=f"{prompt}\nUser request: {query}",
        )
        parsed = _extract_json_object(raw)
    except Exception:
        return {}
    result: dict[str, str | int | None] = {}

    origin = parsed.get("origin")
    destination = parsed.get("destination")
    travelers = parsed.get("travelers")
    budget = parsed.get("budget")
    style = parsed.get("style")
    duration_days = parsed.get("duration_days")

    if isinstance(origin, str):
        result["origin"] = origin.strip().title()
    if isinstance(destination, str):
        result["destination"] = destination.strip().title()
    if isinstance(travelers, int):
        result["travelers"] = max(1, min(travelers, 12))
    elif isinstance(travelers, str) and travelers.strip().isdigit():
        result["travelers"] = max(1, min(int(travelers.strip()), 12))
    if isinstance(budget, str):
        result["budget"] = budget.strip()
    if isinstance(style, str):
        result["style"] = style.strip().title()
    if isinstance(duration_days, int):
        result["duration_days"] = max(1, min(duration_days, 10))
    elif isinstance(duration_days, str) and duration_days.strip().isdigit():
        result["duration_days"] = max(1, min(int(duration_days.strip()), 10))
    return result


def _planning_system_prompt() -> str:
    return (
        "You are a travel planning assistant.\n"
        "The user will provide free-form travel requirements.\n"
        "You must use the provided grounding context from search and map results to build a realistic trip.\n"
        "Choose practical transport, select well-known POIs, avoid filler meals, and only include standout food recommendations.\n"
        "CRITICAL ROUTING RULES:\n"
        "- Group attractions that are geographically close together on the same day.\n"
        "- Within each day, order events so the route flows in one direction without backtracking.\n"
        "- Minimize total transit time by visiting nearby POIs consecutively.\n"
        "- Each day must have 4-6 meaningful events spanning from ~08:00 to ~21:00.\n"
        "- Spread activities evenly across the day with reasonable gaps (1-2 hours per event).\n"
        "- Do NOT leave large empty blocks; cover morning, afternoon, and evening.\n"
        "Output valid JSON only with no markdown fences."
    )


def _planning_draft_system_prompt() -> str:
    return (
        "You are a travel planning assistant.\n"
        "The user's requirements will follow.\n"
        "Generate an initial structured itinerary draft in JSON.\n"
        "Do not use markdown fences.\n"
        "Do not add routine lunch or dinner filler unless the trip is explicitly food-focused.\n"
        "Group attractions by geographic area or district for each day.\n"
        "Order events within each day to flow geographically without backtracking across the city.\n"
        "Each day must have 4-6 events covering morning (~08:00) through evening (~21:00)."
    )


def _prune_routine_food_events(timeline_days: list[DayPlan], style: str | None) -> None:
    keep_food = bool(style and "food" in style.lower())
    generic_food_tokens = {"local lunch", "light lunch before departure", "hotel breakfast", "breakfast"}
    for day in timeline_days:
        filtered: list[TimelineEvent] = []
        food_kept = False
        for event in day.events:
            kind = _classify_event(event.title)
            lowered = event.title.lower()
            if kind == "food":
                standout = not any(token == lowered for token in generic_food_tokens) and any(
                    token in lowered for token in ["馆", "restaurant", "cafe", "bistro", "food", "market", "roast", "hotpot", "sushi"]
                )
                if keep_food and not food_kept:
                    filtered.append(event)
                    food_kept = True
                elif standout and not food_kept:
                    filtered.append(event)
                    food_kept = True
                continue
            filtered.append(event)
        day.events = filtered


class PlannerGraphState(TypedDict, total=False):
    query: str
    resolved_model: ResolvedModelConfig
    interaction_mode: str
    existing_trip_id: str | None
    model_client: ModelApiClient | None
    now: str
    trip_id: str
    base_fields: dict[str, object]
    heuristic: dict[str, str | int | None]
    extracted: dict[str, str | int | None]
    parsed: dict[str, str | int | None]
    clarification_questions: list[ClarificationQuestion]
    search_context: str
    prefetched_amap: dict[str, list]
    prefetched_attractions: list[tuple[str, str]]
    draft_content: str
    refined_content: str
    model_payload: dict[str, object] | None
    trip: TripState


def _build_draft_llm_prompt(query: str, parsed: dict[str, str | int | None], interaction_mode: str) -> str:
    destination = parsed.get("destination") or "the destination"
    duration_days = parsed.get("duration_days") or 3
    budget = parsed.get("budget") or "mid-range"
    style = parsed.get("style") or "Balanced"
    travelers = parsed.get("travelers") or 1
    origin = parsed.get("origin") or "the departure city"
    transport_mode = _choose_transport_mode(str(origin), str(destination))
    outbound_date, return_date = _default_departure_dates(int(duration_days))
    return (
        "Create a realistic travel itinerary draft from the user requirements. "
        "Return strict JSON only with this shape: "
        "{\"plan_summary\":{\"headline\":\"\",\"body\":\"\",\"highlights\":[\"\",\"\"]},"
        "\"travel_logistics\":{\"origin\":\"\",\"destination\":\"\",\"travelers\":1,"
        "\"outbound_transport\":\"\",\"return_transport\":\"\",\"outbound_schedule\":\"\","
        "\"return_schedule\":\"\",\"hotel_name\":\"\"},"
        "\"days\":[{\"theme\":\"\",\"events\":[{\"start_time\":\"08:00\",\"end_time\":\"09:30\","
        "\"title\":\"\",\"location\":\"\",\"travel_time_from_previous\":\"10 min\","
        "\"cost_estimate\":\"$20\",\"description\":\"\",\"risk_flags\":[\"\"]}]}],"
        "\"budget_summary\":{\"trip_total_estimate\":\"$480\",\"current_day_estimate\":\"$120\",\"budget_status\":\"on_track\"},"
        "\"map_preview\":{\"route_label\":\"\",\"stops\":[\"\",\"\"],\"total_transit_time\":\"1h 00m\"},"
        "\"reference_links\":[{\"title\":\"\",\"url\":\"https://example.com\",\"label\":\"\"}]}. "
        f"Mode: {interaction_mode}.\n"
        f"User request: {query}\n"
        f"Origin: {origin}\n"
        f"Destination: {destination}\n"
        f"Travelers: {travelers}\n"
        f"Duration days: {duration_days}\n"
        f"Budget: {budget}\n"
        f"Style: {style}\n"
        f"Recommended transport mode: {transport_mode}\n"
        f"If no user date is present, use outbound date {outbound_date.strftime('%Y-%m-%d')} and return date {return_date.strftime('%Y-%m-%d')}.\n"
        "Make exactly one day object per travel day. Prioritize well-known attractions and landmark areas. "
        "Do not insert routine lunch or dinner fillers. Only add a food stop if it is a notable local recommendation or the user is food-focused. "
        "Each day MUST have 4-6 meaningful events spanning from ~08:00 to ~21:00. "
        "IMPORTANT: Group geographically close attractions on the same day. "
        "Order each day's events STRICTLY by physical proximity to form a logical route without backtracking (e.g., A -> B -> C, where A is near B, and B is near C). "
        "Visit nearby POIs consecutively to minimize transit time between stops. "
        "Spread activities evenly across morning, afternoon, and evening — no large empty gaps. "
        "Travel logistics should be practical. You MUST select a centrally located hotel near the destination's primary attractions to minimize daily commuting. "
        "Pick a transport mode first, then provide realistic departure and arrival time windows. "
        "If an exact price is unknown, write approximate. "
        "CRITICAL: If the destination is within Greater China (Mainland, Hong Kong, Macau, Taiwan), you MUST output the `destination`, `title`, and `location` fields in Simplified Chinese (e.g., '北京' instead of 'Beijing', '故宫' instead of 'Forbidden City'), even if the user query is in English. This is strictly required for the map API to geocode correctly."
    )


def _build_refinement_prompt(
    query: str,
    parsed: dict[str, str | int | None],
    interaction_mode: str,
    draft_json: str,
    search_context: str,
) -> str:
    destination = parsed.get("destination") or "the destination"
    return (
        f"You are a travel planning assistant.\n"
        f"The user's requirements are: {query}.\n"
        "Now let's plan the journey from the start city to the target city.\n"
        "You are given:\n"
        "1. An initial itinerary draft from a large model.\n"
        "2. Search and map grounding context with REAL POIs and their addresses.\n"
        "Use both to produce a better final itinerary.\n"
        "REFINEMENT RULES:\n"
        "- Replace any generic or hallucinated POIs with real ones from the grounding context.\n"
        "- STRICTLY reorder events within each day based on actual geographic proximity to create a logical, linear route without any backtracking.\n"
        "- Ensure each day has 4-6 events from ~08:00 to ~21:00, spread evenly.\n"
        "- Group geographically close POIs on the same day.\n"
        "- Choose a centrally located hotel from the grounding context if applicable, near the main attractions.\n"
        "- Keep only meaningful food stops (famous local specialties, not routine meals).\n"
        "- CRITICAL: If the destination is within Greater China (Mainland, Hong Kong, Macau, Taiwan), you MUST output the `destination`, `title`, and `location` fields in Simplified Chinese (e.g., '北京' instead of 'Beijing', '故宫' instead of 'Forbidden City'). This is strictly required for the map API to geocode correctly.\n"
        "Return strict JSON only in the same schema as the draft.\n\n"
        f"Mode: {interaction_mode}\n"
        f"Initial draft JSON:\n{draft_json}\n\n"
        f"{search_context}\n"
    )


def _trip_from_fallback(
    *,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
) -> TripState:
    destination = str(parsed["destination"])
    duration_days = int(parsed["duration_days"])
    budget = parsed.get("budget")
    style = parsed.get("style")
    logistics = _default_logistics(parsed)
    timeline_days = [
        _build_day(index, destination, style if isinstance(style, str) else None, budget if isinstance(budget, str) else None)
        for index in range(duration_days)
    ]
    provider_warnings = list(base_fields["provider_warnings"])
    provider_warnings.extend(
        _apply_amap_candidates(
            destination,
            timeline_days,
            logistics,
            prefetched_amap=prefetched_amap,
            prefetched_attractions=prefetched_attractions,
        )
    )
    _inject_logistics_events(timeline_days, logistics)
    _prune_routine_food_events(timeline_days, style if isinstance(style, str) else None)
    _hydrate_event_geocodes(destination, timeline_days, logistics)
    _build_day_routes(destination, timeline_days)
    _ensure_cost_estimates(timeline_days)
    _assign_food_images(timeline_days)
    computed_budget = _estimate_budget_summary(parsed, logistics, timeline_days)
    if base_fields["model_source"] != "mock":
        provider_warnings.append(
            ProviderWarning(
                source="model",
                message="The model response could not be parsed, so a local fallback itinerary was used.",
                severity="medium",
            )
        )
    image_references = _enrich_visuals(destination, timeline_days)
    live_references, live_warnings = _apply_live_search(logistics, timeline_days)
    provider_warnings.extend(live_warnings)
    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    return TripState(
        **trip_fields,
        view_state="partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready",
        plan_summary=PlanSummary(
            headline=f"{duration_days}-day {destination} plan ready",
            body="The itinerary includes arrival, hotel, daily pacing, and the return leg so the full trip is executable.",
            highlights=["Logistics Included", "Structured Timeline", "Budget Aware"],
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=computed_budget,
        memory_summary=MemorySummary(
            fixed_anchors=["Hotel check-in", logistics.hotel_name],
            open_constraints=[],
            user_preferences=[value for value in [style, budget] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="itinerary_generation",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=f"{destination} full-trip route",
            stops=[event.location for event in timeline_days[0].events[:4]],
            total_transit_time="2h 10m",
            image_references=image_references,
        ),
        travel_logistics=logistics,
        reference_links=_merge_reference_links(live_references, _reference_links(destination)),
        planning_trace=[],
    )


def _trip_from_model(
    *,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
    model_payload: dict[str, object],
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
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
            for event_index, raw_event in enumerate(raw_events[:8]):
                if not isinstance(raw_event, dict):
                    continue
                title = str(raw_event.get("title", f"Activity {event_index + 1}"))
                kind = _classify_event(title)
                events.append(
                    TimelineEvent(
                        id=f"d{day_index + 1}-e{event_index + 1}",
                        start_time=str(raw_event.get("start_time", f"{9 + event_index * 3:02d}:00")),
                        end_time=str(raw_event.get("end_time", f"{11 + event_index * 3:02d}:00")),
                        title=title,
                        location=str(raw_event.get("location", "Recommended area")),
                        travel_time_from_previous=str(raw_event.get("travel_time_from_previous", "15 min")),
                        cost_estimate=str(raw_event.get("cost_estimate")) if raw_event.get("cost_estimate") is not None else None,
                        description=str(raw_event.get("description", "A suggested stop based on your selected constraints.")),
                        image_url=_placeholder_image(kind) if kind in {"scenic", "food"} else None,
                        risk_flags=[str(flag) for flag in raw_event.get("risk_flags", []) if isinstance(flag, (str, int, float))],
                    )
                )
        if not events:
            raise ValueError("Model returned an empty day.")
        theme = "Highlights"
        if isinstance(raw_day, dict) and raw_day.get("theme") is not None:
            theme = str(raw_day["theme"])
        timeline_days.append(DayPlan(day_index=day_index, title=f"Day {day_index + 1}", theme=theme, events=events))

    summary_payload = model_payload.get("plan_summary") if isinstance(model_payload.get("plan_summary"), dict) else {}
    budget_payload = model_payload.get("budget_summary") if isinstance(model_payload.get("budget_summary"), dict) else {}
    map_payload = model_payload.get("map_preview") if isinstance(model_payload.get("map_preview"), dict) else {}
    logistics_payload = model_payload.get("travel_logistics") if isinstance(model_payload.get("travel_logistics"), dict) else {}
    links_payload = model_payload.get("reference_links") if isinstance(model_payload.get("reference_links"), list) else []

    default_logistics = _default_logistics(parsed)
    logistics = TravelLogistics(
        origin=str(logistics_payload.get("origin", default_logistics.origin)),
        destination=str(logistics_payload.get("destination", default_logistics.destination)),
        travelers=int(logistics_payload.get("travelers", default_logistics.travelers)),
        outbound_transport=str(logistics_payload.get("outbound_transport", default_logistics.outbound_transport)),
        return_transport=str(logistics_payload.get("return_transport", default_logistics.return_transport)),
        outbound_schedule=str(logistics_payload.get("outbound_schedule", default_logistics.outbound_schedule)),
        return_schedule=str(logistics_payload.get("return_schedule", default_logistics.return_schedule)),
        hotel_name=str(logistics_payload.get("hotel_name", f"{parsed.get('destination') or 'Central'} Grand Hotel")),
    )
    provider_warnings = list(base_fields["provider_warnings"])
    provider_warnings.extend(
        _apply_amap_candidates(
            logistics.destination,
            timeline_days,
            logistics,
            prefetched_amap=prefetched_amap,
            prefetched_attractions=prefetched_attractions,
        )
    )
    _inject_logistics_events(timeline_days, logistics)
    _prune_routine_food_events(timeline_days, parsed.get("style") if isinstance(parsed.get("style"), str) else None)
    _hydrate_event_geocodes(logistics.destination, timeline_days, logistics)
    _build_day_routes(logistics.destination, timeline_days)
    _ensure_cost_estimates(timeline_days)
    _assign_food_images(timeline_days)
    image_references = _enrich_visuals(logistics.destination, timeline_days)
    computed_budget = _estimate_budget_summary(parsed, logistics, timeline_days)

    reference_links = _sanitize_reference_links([
        ReferenceLink(
            title=str(item.get("title", "External reference")),
            url=str(item.get("url", "https://www.google.com")),
            label=str(item.get("label", "Open")),
        )
        for item in links_payload[:3]
        if isinstance(item, dict)
    ])
    if not reference_links:
        reference_links = _reference_links(logistics.destination)
    live_references, live_warnings = _apply_live_search(logistics, timeline_days)
    provider_warnings.extend(live_warnings)
    reference_links = _merge_reference_links(live_references, reference_links, _reference_links(logistics.destination))

    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    return TripState(
        **trip_fields,
        view_state="partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready",
        plan_summary=PlanSummary(
            headline=str(summary_payload.get("headline", f"{duration_days}-day {logistics.destination} plan ready")),
            body=str(summary_payload.get("body", "A structured itinerary generated by the selected model.")),
            highlights=[str(item) for item in summary_payload.get("highlights", []) if isinstance(item, (str, int, float))][:4],
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=BudgetSummary(
            trip_total_estimate=str(budget_payload.get("trip_total_estimate", computed_budget.trip_total_estimate)),
            current_day_estimate=str(budget_payload.get("current_day_estimate", computed_budget.current_day_estimate)),
            budget_status=str(budget_payload.get("budget_status", computed_budget.budget_status))
            if str(budget_payload.get("budget_status", computed_budget.budget_status)) in {"on_track", "watch", "over"}
            else computed_budget.budget_status,
        ),
        memory_summary=MemorySummary(
            fixed_anchors=["Hotel check-in", logistics.hotel_name],
            open_constraints=[],
            user_preferences=[value for value in [parsed.get("style"), parsed.get("budget")] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="model_generated",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=str(map_payload.get("route_label", f"{logistics.destination} complete route")),
            stops=[str(item) for item in map_payload.get("stops", []) if isinstance(item, (str, int, float))][:6],
            total_transit_time=str(map_payload.get("total_transit_time", "2h 00m")),
            image_references=image_references,
        ),
        travel_logistics=logistics,
        reference_links=reference_links,
        planning_trace=[],
    )


def _run_langgraph_planner(
    *,
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str,
    existing_trip_id: str | None,
    model_client: ModelApiClient | None,
) -> TripState:
    def extract_node(state: PlannerGraphState) -> PlannerGraphState:
        logger.info("[trip:%s] request received mode=%s model=%s query=%s", state["trip_id"], state["interaction_mode"], state["resolved_model"].model_id, state["query"][:160])
        heuristic = parse_intent(state["query"])
        extracted = _extract_constraints_with_model(state["query"], state["resolved_model"], state.get("model_client"))
        parsed = _normalize_defaults(_merge_parsed(heuristic, extracted), interaction_mode=state["interaction_mode"])
        clarification_questions = _planning_questions(parsed) if state["interaction_mode"] == "planning" else []
        logger.info(
            "[trip:%s] extract complete origin=%s destination=%s travelers=%s budget=%s style=%s duration=%s clarifications=%s",
            state["trip_id"],
            parsed.get("origin"),
            parsed.get("destination"),
            parsed.get("travelers"),
            parsed.get("budget"),
            parsed.get("style"),
            parsed.get("duration_days"),
            len(clarification_questions),
        )
        return {
            "heuristic": heuristic,
            "extracted": extracted,
            "parsed": parsed,
            "clarification_questions": clarification_questions,
        }

    def route_after_extract(state: PlannerGraphState) -> str:
        if state["interaction_mode"] == "planning" and state.get("clarification_questions"):
            return "end_clarification"
        return "search"

    def end_clarification_node(state: PlannerGraphState) -> PlannerGraphState:
        logger.info("[trip:%s] returning clarification brief", state["trip_id"])
        parsed = state["parsed"]
        base_fields = state["base_fields"]
        destination = str(parsed.get("destination") or "destination")
        trip = TripState(
            **base_fields,
            view_state="needs_clarification",
            plan_summary=PlanSummary(
                headline="Fill the planning brief first",
                body="Planning mode collects the trip brief up front, then generates the itinerary in one pass.",
                highlights=["Structured Brief", "Less Rework"],
            ),
            clarification_questions=state.get("clarification_questions", []),
            timeline_days=[],
            budget_summary=BudgetSummary(
                trip_total_estimate="Pending brief",
                current_day_estimate="Pending brief",
                budget_status="watch",
            ),
            memory_summary=MemorySummary(
                fixed_anchors=[],
                open_constraints=[question.label for question in state.get("clarification_questions", [])],
                user_preferences=[str(parsed.get("style"))] if parsed.get("style") else [],
                last_selected_model=resolved_model.model_id,
                route_mode="planning_brief",
            ),
            conflict_warnings=[],
            map_preview=MapPreview(route_label="Visual route unlocks after the brief is complete", stops=[], total_transit_time="Pending"),
            travel_logistics=_default_logistics({**parsed, "destination": destination if destination != "destination" else None}),
            reference_links=[],
            planning_trace=[],
        )
        return {"trip": trip}

    def search_and_draft_node(state: PlannerGraphState) -> PlannerGraphState:
        """Run search and draft LLM call in parallel to save wall-clock time.

        Each leg is independently error-tolerant: if either times out,
        we continue with whatever succeeded.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        parsed = state["parsed"]
        destination = str(parsed.get("destination") or "Custom Destination")
        origin = str(parsed.get("origin") or "Your city")
        style = parsed.get("style") if isinstance(parsed.get("style"), str) else None

        def _do_search() -> tuple[str, dict[str, list], list[tuple[str, str]]]:
            return _build_search_context(destination, origin, style)

        def _do_draft() -> str:
            if state["resolved_model"].source == "mock" or state.get("model_client") is None:
                return ""
            draft_system, draft_user = render_chat_prompts(
                _planning_draft_system_prompt(),
                _build_draft_llm_prompt(state["query"], state["parsed"], state["interaction_mode"]),
            )
            return state["model_client"].complete_json(
                resolved_model=state["resolved_model"],
                system_prompt=draft_system,
                user_prompt=draft_user,
            )

        logger.info("[trip:%s] search+draft parallel start", state["trip_id"])

        # Run both in parallel with individual error handling
        search_context = "Grounding context from search results and map providers:\nAttractions:\n- None found"
        prefetched_amap: dict[str, list] = {}
        prefetched_attractions: list[tuple[str, str]] = []
        draft_content = ""

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="plan-io") as pool:
            search_future = pool.submit(_do_search)
            draft_future = pool.submit(_do_draft)

            try:
                search_result = search_future.result(timeout=30)
                search_context, prefetched_amap, prefetched_attractions = search_result
            except Exception as exc:
                logger.warning("[trip:%s] search leg failed, continuing with empty context: %s", state["trip_id"], exc)

            try:
                draft_content = draft_future.result(timeout=90)
            except Exception as exc:
                logger.warning("[trip:%s] draft leg failed, continuing with empty draft: %s", state["trip_id"], exc)

        logger.info(
            "[trip:%s] search+draft parallel complete amap_attractions=%s amap_hotels=%s search_attractions=%s draft_len=%s",
            state["trip_id"],
            len(prefetched_amap.get("attractions", [])),
            len(prefetched_amap.get("hotels", [])),
            len(prefetched_attractions),
            len(draft_content),
        )
        return {
            "search_context": search_context,
            "prefetched_amap": prefetched_amap,
            "prefetched_attractions": prefetched_attractions,
            "draft_content": draft_content,
        }

    def refine_node(state: PlannerGraphState) -> PlannerGraphState:
        if state["resolved_model"].source == "mock" or state.get("model_client") is None:
            logger.info("[trip:%s] refine skipped (mock/no model client)", state["trip_id"])
            return {"refined_content": "", "model_payload": None}
        logger.info("[trip:%s] refine LLM call start", state["trip_id"])
        refine_system, refine_user = render_chat_prompts(
            _planning_system_prompt(),
            _build_refinement_prompt(
                state["query"],
                state["parsed"],
                state["interaction_mode"],
                state.get("draft_content") or "{}",
                state.get("search_context") or "Grounding context from search results and map providers:\nAttractions:\n- None found",
            ),
        )
        refined_content = state["model_client"].complete_json(
            resolved_model=state["resolved_model"],
            system_prompt=refine_system,
            user_prompt=refine_user,
        )
        model_payload: dict[str, object] | None = None
        try:
            model_payload = _extract_json_object(refined_content)
            logger.info("[trip:%s] refine parse succeeded", state["trip_id"])
        except (ValueError, TypeError, json.JSONDecodeError):
            try:
                model_payload = _extract_json_object(state.get("draft_content") or "")
                logger.info("[trip:%s] refine parse failed, using draft payload", state["trip_id"])
            except (ValueError, TypeError, json.JSONDecodeError):
                model_payload = None
                logger.info("[trip:%s] refine parse failed, falling back to local itinerary", state["trip_id"])
        return {"refined_content": refined_content, "model_payload": model_payload}

    def enrich_node(state: PlannerGraphState) -> PlannerGraphState:
        if state.get("model_payload"):
            logger.info("[trip:%s] enrich using model payload", state["trip_id"])
            trip = _trip_from_model(
                parsed=state["parsed"],
                base_fields=state["base_fields"],
                model_payload=state["model_payload"],
                prefetched_amap=state.get("prefetched_amap"),
                prefetched_attractions=state.get("prefetched_attractions"),
            )
        else:
            logger.info("[trip:%s] enrich using fallback builder", state["trip_id"])
            trip = _trip_from_fallback(
                parsed=state["parsed"],
                base_fields=state["base_fields"],
                prefetched_amap=state.get("prefetched_amap"),
                prefetched_attractions=state.get("prefetched_attractions"),
            )
        logger.info("[trip:%s] trip ready view_state=%s days=%s warnings=%s", state["trip_id"], trip.view_state, len(trip.timeline_days), len(trip.provider_warnings))
        return {"trip": trip}

    graph = StateGraph(PlannerGraphState)
    graph.add_node("extract", extract_node)
    graph.add_node("end_clarification", end_clarification_node)
    graph.add_node("search_and_draft", search_and_draft_node)
    graph.add_node("refine", refine_node)
    graph.add_node("enrich", enrich_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract",
        route_after_extract,
        {
            "end_clarification": "end_clarification",
            "search": "search_and_draft",
        },
    )
    graph.add_edge("end_clarification", END)
    graph.add_edge("search_and_draft", "refine")
    graph.add_edge("refine", "enrich")
    graph.add_edge("enrich", END)

    compiled = graph.compile()
    now = datetime.now(timezone.utc).isoformat()
    trip_id = existing_trip_id or uuid4().hex
    base_fields = _base_trip_fields(
        trip_id=trip_id,
        now=now,
        query=query,
        resolved_model=resolved_model,
        interaction_mode=interaction_mode,
    )
    final_state = compiled.invoke(
        PlannerGraphState(
            query=query,
            resolved_model=resolved_model,
            interaction_mode=interaction_mode,
            existing_trip_id=existing_trip_id,
            model_client=model_client,
            now=now,
            trip_id=trip_id,
            base_fields=base_fields,
        )
    )
    return final_state["trip"]


def build_trip_state(
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str = "direct",
    existing_trip_id: str | None = None,
    model_client: ModelApiClient | None = None,
) -> TripState:
    return _run_langgraph_planner(
        query=query,
        resolved_model=resolved_model,
        interaction_mode=interaction_mode,
        existing_trip_id=existing_trip_id,
        model_client=model_client,
    )
