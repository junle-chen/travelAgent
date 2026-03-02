from __future__ import annotations

from app.core.config import Settings
from app.models.registry import MODEL_REGISTRY
from app.schemas.providers import ModelConfigRequest, ResolvedModelConfig, SupportedModelInfo


class ModelResolutionError(ValueError):
    pass


class ModelCredentialResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve(self, request: ModelConfigRequest) -> ResolvedModelConfig:
        config = MODEL_REGISTRY.get(request.model_id)
        if config is None:
            raise ModelResolutionError(f"Unsupported model: {request.model_id}")

        if request.api_key and request.base_url:
            return ResolvedModelConfig(
                model_id=request.model_id,
                api_key=request.api_key,
                base_url=request.base_url,
                source="request",
                provider=config["provider"],
            )

        env_config = self.settings.get_model_env_config(config["api_key_var"], config["base_url_var"])
        if env_config.api_key and env_config.base_url:
            return ResolvedModelConfig(
                model_id=request.model_id,
                api_key=env_config.api_key,
                base_url=env_config.base_url,
                source="env",
                provider=config["provider"],
            )

        if self.settings.enable_mock_model_fallback:
            return ResolvedModelConfig(
                model_id=request.model_id,
                api_key=None,
                base_url=None,
                source="mock",
                provider="mock_provider",
            )

        raise ModelResolutionError(
            f"Missing configuration for {request.model_id}. Add API_KEY and BASE_URL to backend/.env."
        )

    def supported_models(self) -> list[SupportedModelInfo]:
        models: list[SupportedModelInfo] = []
        for model_id, config in MODEL_REGISTRY.items():
            env_config = self.settings.get_model_env_config(config["api_key_var"], config["base_url_var"])
            models.append(
                SupportedModelInfo(
                    model_id=model_id,
                    label=config["label"],
                    env_configured=bool(env_config.api_key and env_config.base_url),
                    provider=config["provider"],
                )
            )
        return models
