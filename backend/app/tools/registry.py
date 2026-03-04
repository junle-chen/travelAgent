from __future__ import annotations

TOOL_REGISTRY: dict[str, dict[str, object]] = {
    "amap_mcp": {
        "api_key_vars": ["AMAP_API_KEY", "AMAP_MAPS_API_KEY"],
        "base_url_var": None,
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "tavily_search": {
        "api_key_vars": ["TAVILY_API_KEY"],
        "base_url_var": None,
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "serper_search": {
        "api_key_vars": ["SERPER_API_KEY"],
        "base_url_var": None,
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "serpapi_search": {
        "api_key_vars": ["SERPAPI_API_KEY"],
        "base_url_var": None,
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "visual_search": {
        "api_key_vars": None,
        "base_url_var": None,
        "requires_api_key": False,
        "requires_base_url": False,
    },
}
