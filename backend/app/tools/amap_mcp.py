from __future__ import annotations

from app.core.config import Settings


def build_amap_mcp_url(settings: Settings) -> str | None:
    config = settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
    if not config.api_key:
        return None
    return f"https://mcp.amap.com/mcp?key={config.api_key}"
