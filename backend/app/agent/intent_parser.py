from __future__ import annotations

import re

KNOWN_DESTINATIONS = [
    ("hong kong", "Hong Kong"),
    ("hongkong", "Hong Kong"),
    ("new york", "New York"),
    ("singapore", "Singapore"),
    ("shanghai", "Shanghai"),
    ("shenzhen", "Shenzhen"),
    ("hangzhou", "Hangzhou"),
    ("chengdu", "Chengdu"),
    ("beijing", "Beijing"),
    ("xiamen", "Xiamen"),
    ("bangkok", "Bangkok"),
    ("tokyo", "Tokyo"),
    ("kyoto", "Kyoto"),
    ("osaka", "Osaka"),
    ("seoul", "Seoul"),
    ("paris", "Paris"),
    ("london", "London"),
]

STYLE_KEYWORDS = [
    ("food-focused", "Food focused"),
    ("food focused", "Food focused"),
    ("relaxed", "Relaxed pace"),
    ("packed", "Packed pace"),
    ("luxury", "Luxury leaning"),
    ("mid-range", "Mid-range"),
    ("midrange", "Mid-range"),
    ("family", "Family friendly"),
    ("budget", "Budget conscious"),
    ("food", "Food focused"),
]


def parse_intent(query: str) -> dict[str, str | int | None]:
    lowered = query.lower()

    def normalize_place(raw: str) -> str | None:
        cleaned = raw.strip(" .,:;-").strip()
        if not cleaned:
            return None
        for needle, label in KNOWN_DESTINATIONS:
            if needle == cleaned.lower():
                return label
        return cleaned.title()

    destination = None
    destination_label_match = re.search(r"(?:destination|end)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if destination_label_match:
        destination = normalize_place(destination_label_match.group(1))

    duration = None
    match = re.search(r"(\d+)\s*(?:[- ]?day|days|d)\b", lowered)
    if match:
        duration = max(1, min(int(match.group(1)), 10))

    budget = None
    budget_label_match = re.search(r"budget\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if budget_label_match:
        budget = budget_label_match.group(1).strip()
    amount_match = re.search(r"(?:budget\s*(?:is|around|of)?\s*|\$)\s*(\d+[\d,]*)", lowered)
    if amount_match:
        budget = f"${amount_match.group(1).replace(',', '')}"
    elif "balanced" in lowered or "balance" in lowered or "mid-range" in lowered or "midrange" in lowered:
        budget = "balanced"
    elif "low" in lowered or "budget" in lowered:
        budget = "low"
    elif "high" in lowered or "luxury" in lowered:
        budget = "high"

    style = None
    style_label_match = re.search(r"(?:preference|style)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if style_label_match:
        style = style_label_match.group(1).strip().title()
    for keyword, label in STYLE_KEYWORDS:
        if keyword in lowered:
            style = label
            break

    travelers = None
    travelers_label_match = re.search(r"(?:travelers|travellers|people|人数)\s*:\s*(\d+)", query, re.IGNORECASE)
    if travelers_label_match:
        travelers = max(1, min(int(travelers_label_match.group(1)), 12))
    people_match = re.search(r"(\d+)\s*(?:people|person|traveler|travellers|travelers|pax)\b", lowered)
    if people_match:
        travelers = max(1, min(int(people_match.group(1)), 12))
    elif companion_match := re.search(r"\b(\d+)\s*(?:friends|adults|guests|visitors)\b", lowered):
        travelers = max(1, min(int(companion_match.group(1)), 12))
    elif re.search(r"\bsolo\b", lowered):
        travelers = 1
    elif re.search(r"\bcouple\b", lowered):
        travelers = 2
    elif re.search(r"\bfamily\b", lowered):
        travelers = 4

    origin = None
    origin_label_match = re.search(r"(?:start|origin|from)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if origin_label_match:
        origin = normalize_place(origin_label_match.group(1)) or None
    origin_match = re.search(r"from\s+([a-z][a-z\s]{1,30}?)(?:\s+(?:to|for|want|planning)\b|,|$)", lowered)
    if origin_match:
        origin = normalize_place(origin_match.group(1)) or origin

    city_hits: list[tuple[int, str, str]] = []
    for needle, label in KNOWN_DESTINATIONS:
        for match in re.finditer(re.escape(needle), lowered):
            city_hits.append((match.start(), needle, label))
    city_hits.sort(key=lambda item: item[0])

    if destination is None:
        explicit_destination_patterns = [
            r"\bto\s+([a-z][a-z\s]{1,30}?)\b",
            r"\btrip\s+(?:to|in)\s+([a-z][a-z\s]{1,30}?)\b",
            r"\b(?:weekend|holiday|vacation)\s+in\s+([a-z][a-z\s]{1,30}?)\b",
        ]
        for pattern in explicit_destination_patterns:
            match = re.search(pattern, lowered)
            if match:
                candidate = normalize_place(match.group(1))
                if candidate:
                    destination = candidate
                    break

    if destination is None:
        for _, needle, label in city_hits:
            if re.search(rf"\b{re.escape(needle)}\s+(?:trip|weekend|holiday|vacation)\b", lowered):
                destination = label
                break

    if destination is None:
        for _, _, label in city_hits:
            if label != origin:
                destination = label
                break

    return {
        "destination": destination,
        "duration_days": duration,
        "budget": budget,
        "style": style,
        "travelers": travelers,
        "origin": origin,
    }
