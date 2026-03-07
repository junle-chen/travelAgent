from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.credential_resolver import ModelCredentialResolver
from app.schemas.responses import ModelsResponse

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelsResponse)
def get_models() -> ModelsResponse:
    settings = get_settings()
    resolver = ModelCredentialResolver(settings)
    return ModelsResponse(
        models=resolver.supported_models(),
        default_model_id="gemini-3-flash-preview",
        mock_model_fallback_enabled=settings.enable_mock_model_fallback,
    )
