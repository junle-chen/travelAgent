from __future__ import annotations

from app.schemas.domain import ClarificationQuestion


REQUIRED_FIELDS = [
    ("destination", "Where do you want to go?", ["Tokyo", "Kyoto", "Paris"]),
    ("duration_days", "How many days is the trip?", ["3 days", "4 days", "5 days"]),
    ("budget", "What budget range should I optimize for?", ["Budget", "Mid-range", "Luxury"]),
]


def build_clarification_questions(intent: dict[str, object]) -> list[ClarificationQuestion]:
    questions: list[ClarificationQuestion] = []
    for key, question, suggestions in REQUIRED_FIELDS:
        if intent.get(key) in (None, ""):
            questions.append(
                ClarificationQuestion(
                    id=key,
                    label=key.replace("_", " ").title(),
                    question=question,
                    suggestions=suggestions,
                )
            )
    return questions[:3]
