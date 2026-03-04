from __future__ import annotations

import re

KNOWN_DESTINATIONS = {
    "beijing": "Beijing",
    "shanghai": "Shanghai",
    "shenzhen": "Shenzhen",
    "hong kong": "Hong Kong",
    "hongkong": "Hong Kong",
    "hangzhou": "Hangzhou",
    "xiamen": "Xiamen",
    "chengdu": "Chengdu",
    "tokyo": "Tokyo",
    "kyoto": "Kyoto",
    "osaka": "Osaka",
    "seoul": "Seoul",
    "paris": "Paris",
    "london": "London",
    "new york": "New York",
    "singapore": "Singapore",
    "bangkok": "Bangkok",
}

STYLE_KEYWORDS = {
    "relaxed": "Relaxed pace",
    "packed": "Packed pace",
    "luxury": "Luxury leaning",
    "budget": "Budget conscious",
    "mid-range": "Mid-range",
    "midrange": "Mid-range",
    "family": "Family friendly",
    "food": "Food focused",
}


def parse_intent(query: str) -> dict[str, str | int | None]:
    lowered = query.lower()

    destination = None
    destination_label_match = re.search(r"(?:destination|end)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if destination_label_match:
        destination = destination_label_match.group(1).strip().title()
    for city in sorted(KNOWN_DESTINATIONS, key=len, reverse=True):
        if city in lowered:
            destination = KNOWN_DESTINATIONS[city]
            break

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
    elif "mid-range" in lowered or "midrange" in lowered:
        budget = "mid-range"
    elif "budget" in lowered:
        budget = "budget"
    elif "luxury" in lowered:
        budget = "luxury"

    style = None
    style_label_match = re.search(r"(?:preference|style)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if style_label_match:
        style = style_label_match.group(1).strip().title()
    for keyword, label in STYLE_KEYWORDS.items():
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
    elif re.search(r"\bsolo\b", lowered):
        travelers = 1
    elif re.search(r"\bcouple\b", lowered):
        travelers = 2
    elif re.search(r"\bfamily\b", lowered):
        travelers = 4

    origin = None
    origin_label_match = re.search(r"(?:start|origin|from)\s*:\s*([^\n]+)", query, re.IGNORECASE)
    if origin_label_match:
        origin = origin_label_match.group(1).strip().title()
    origin_match = re.search(r"from\s+([a-z][a-z\s]{1,30}?)\s+(?:to|for)\b", lowered)
    if origin_match:
        origin = origin_match.group(1).strip().title()

    return {
        "destination": destination,
        "duration_days": duration,
        "budget": budget,
        "style": style,
        "travelers": travelers,
        "origin": origin,
    }
