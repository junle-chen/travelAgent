from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)


@dataclass(frozen=True)
class ModelEnvConfig:
    api_key: str | None
    base_url: str | None


@dataclass(frozen=True)
class ToolEnvConfig:
    api_key: str | None
    base_url: str | None


class Settings:
    def __init__(self) -> None:
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_host = os.getenv("APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("APP_PORT", "8000"))
        self.enable_mock_model_fallback = self._bool("ENABLE_MOCK_MODEL_FALLBACK", True)
        self.enable_mock_tool_fallback = self._bool("ENABLE_MOCK_TOOL_FALLBACK", True)
        self.database_path = str(ROOT_DIR / "travel_agent.db")

    @staticmethod
    def _bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def get_model_env_config(self, api_key_var: str, base_url_var: str) -> ModelEnvConfig:
        api_key = os.getenv(api_key_var) or None
        base_url = os.getenv(base_url_var) or None
        return ModelEnvConfig(api_key=api_key, base_url=base_url)

    def get_tool_env_config(
        self,
        api_key_vars: str | list[str] | tuple[str, ...] | None = None,
        base_url_var: str | None = None,
    ) -> ToolEnvConfig:
        api_key = None
        if isinstance(api_key_vars, str):
            api_key = os.getenv(api_key_vars) or None
        elif api_key_vars:
            for name in api_key_vars:
                api_key = os.getenv(name) or None
                if api_key:
                    break
        base_url = os.getenv(base_url_var) or None if base_url_var else None
        return ToolEnvConfig(api_key=api_key, base_url=base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
