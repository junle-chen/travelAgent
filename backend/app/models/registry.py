from __future__ import annotations

from app.schemas.providers import ModelId

MODEL_REGISTRY: dict[ModelId, dict[str, str]] = {
    "gpt-5.1-chat": {
        "label": "GPT 5.1 Chat",
        "provider": "openai_compatible",
        "api_key_var": "GPT_5_1_CHAT_API_KEY",
        "base_url_var": "GPT_5_1_CHAT_BASE_URL",
    },
    "gemini-3-flash-preview": {
        "label": "Gemini 3 Flash Preview",
        "provider": "gemini_compatible",
        "api_key_var": "GEMINI_3_FLASH_PREVIEW_API_KEY",
        "base_url_var": "GEMINI_3_FLASH_PREVIEW_BASE_URL",
    },
    "deepseek-v3.2": {
        "label": "DeepSeek V3.2",
        "provider": "deepseek_compatible",
        "api_key_var": "DEEPSEEK_V3_2_API_KEY",
        "base_url_var": "DEEPSEEK_V3_2_BASE_URL",
    },
}
