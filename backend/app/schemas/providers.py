from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModelId = Literal["gpt-5.1-chat", "gemini-3-flash-preview", "deepseek-v3.2"]
ModelSource = Literal["request", "env", "mock"]


class ModelConfigRequest(BaseModel):
    model_id: ModelId = "gpt-5.1-chat"
    api_key: str | None = None
    base_url: str | None = None


class ResolvedModelConfig(BaseModel):
    model_id: ModelId
    api_key: str | None = None
    base_url: str | None = None
    source: ModelSource
    provider: str


class SupportedModelInfo(BaseModel):
    model_id: ModelId
    label: str
    env_configured: bool
    supports_override: bool = True
    provider: str


class ToolProviderStatus(BaseModel):
    tool_name: str
    env_configured: bool
    fallback_enabled: bool
    mode: Literal["ready", "mock", "warning"]


class ProviderWarning(BaseModel):
    source: str
    message: str
    severity: Literal["low", "medium", "high"] = "low"


class ProviderHealthSummary(BaseModel):
    models: list[SupportedModelInfo]
    tools: list[ToolProviderStatus]
    mock_model_fallback_enabled: bool
    mock_tool_fallback_enabled: bool
    default_model_id: ModelId = Field(default="gemini-3-flash-preview")
