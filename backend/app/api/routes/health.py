from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.credential_resolver import ModelCredentialResolver
from app.schemas.providers import ProviderHealthSummary, ProviderWarning
from app.schemas.responses import HealthResponse
from app.tools.credential_resolver import ToolCredentialResolver

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def get_health() -> HealthResponse:
    settings = get_settings()
    model_resolver = ModelCredentialResolver(settings)
    tool_resolver = ToolCredentialResolver(settings)
    warnings: list[ProviderWarning] = []
    if not any(model.env_configured for model in model_resolver.supported_models()):
        warnings.append(
            ProviderWarning(source="models", message="No model env configuration found. Mock fallback will be used.", severity="medium")
        )
    return HealthResponse(
        status="ok",
        providers=ProviderHealthSummary(
            models=model_resolver.supported_models(),
            tools=tool_resolver.statuses(),
            mock_model_fallback_enabled=settings.enable_mock_model_fallback,
            mock_tool_fallback_enabled=settings.enable_mock_tool_fallback,
        ),
        warnings=warnings,
    )
