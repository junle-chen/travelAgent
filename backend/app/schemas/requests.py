from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.providers import ModelConfigRequest

InteractionMode = Literal["direct", "planning"]


class CreateTripRequest(BaseModel):
    query: str = Field(min_length=1)
    interaction_mode: InteractionMode = "direct"
    model_request: ModelConfigRequest = Field(
        default_factory=ModelConfigRequest,
        validation_alias="model_config",
        serialization_alias="model_config",
    )


class TripMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    interaction_mode: InteractionMode = "direct"
    model_request: ModelConfigRequest = Field(
        default_factory=ModelConfigRequest,
        validation_alias="model_config",
        serialization_alias="model_config",
    )


class ReorderRequest(BaseModel):
    day_index: int
    event_ids: list[str]
    model_request: ModelConfigRequest = Field(
        default_factory=ModelConfigRequest,
        validation_alias="model_config",
        serialization_alias="model_config",
    )


class RegenerateRequest(BaseModel):
    scope: str = "full"
    day_index: int | None = None
    model_request: ModelConfigRequest = Field(
        default_factory=ModelConfigRequest,
        validation_alias="model_config",
        serialization_alias="model_config",
    )
