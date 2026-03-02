from __future__ import annotations

from app.core.config import Settings
from app.schemas.providers import ToolProviderStatus
from app.tools.registry import TOOL_REGISTRY


class ToolCredentialResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def statuses(self) -> list[ToolProviderStatus]:
        statuses: list[ToolProviderStatus] = []
        for tool_name, config in TOOL_REGISTRY.items():
            env_config = self.settings.get_tool_env_config(config.get("api_key_vars"), config.get("base_url_var"))
            api_ready = True if not config.get("requires_api_key", True) else bool(env_config.api_key)
            base_ready = True if not config.get("requires_base_url", False) else bool(env_config.base_url)
            ready = api_ready and base_ready
            mode = "ready" if ready else ("mock" if self.settings.enable_mock_tool_fallback else "warning")
            statuses.append(
                ToolProviderStatus(
                    tool_name=tool_name,
                    env_configured=ready,
                    fallback_enabled=self.settings.enable_mock_tool_fallback,
                    mode=mode,
                )
            )
        return statuses
