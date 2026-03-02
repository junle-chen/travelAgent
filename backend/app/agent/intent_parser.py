from __future__ import annotations

import re

KNOWN_DESTINATIONS = [
    "hangzhou",
    "tokyo",
    "kyoto",
    "osaka",
    "seoul",
    "paris",
    "london",
    "new york",
    "singapore",
    "bangkok",
]

STYLE_KEYWORDS = {
    "relaxed": "Relaxed pace",
    "packed": "Packed pace",
    "luxury": "Luxury leaning",
    "budget": "Budget conscious",
    "mid-range": "Mid-range",
    "midrange": "Mid-range",
}


def parse_intent(query: str) -> dict[str, str | int | None]:
    lowered = query.lower()
    destination = next((city.title() for city in KNOWN_DESTINATIONS if city in lowered), None)

    duration = None
    match = re.search(r"(\d+)\s*[- ]?day", lowered)
    if match:
        duration = max(1, min(int(match.group(1)), 7))

    budget = None
    if "$" in query:
        amount_match = re.search(r"\$\s*(\d+[\d,]*)", query)
        if amount_match:
            budget = f"${amount_match.group(1)}"
    elif "mid-range" in lowered or "midrange" in lowered:
        budget = "mid-range"
    elif "budget" in lowered:
        budget = "budget"
    elif "luxury" in lowered:
        budget = "luxury"

    style = None
    for keyword, label in STYLE_KEYWORDS.items():
        if keyword in lowered:
            style = label
            break

    return {
        "destination": destination,
        "duration_days": duration,
        "budget": budget,
        "style": style,
    }
