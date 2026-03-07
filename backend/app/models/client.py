from __future__ import annotations

import json
import logging
from urllib import error, request

from app.schemas.providers import ResolvedModelConfig

logger = logging.getLogger("travel_agent.model")


class ModelApiError(RuntimeError):
    pass


def _clip(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


class ModelApiClient:
    def complete_json(self, *, resolved_model: ResolvedModelConfig, system_prompt: str, user_prompt: str) -> str:
        if not resolved_model.base_url or not resolved_model.api_key:
            raise ModelApiError("Model configuration is incomplete.")

        endpoint = f"{resolved_model.base_url.rstrip('/')}/v1/chat/completions"
        logger.info("[model] request model=%s endpoint=%s", resolved_model.model_id, endpoint)
        logger.info("[model] system_prompt=%s", _clip(system_prompt))
        logger.info("[model] user_prompt=%s", _clip(user_prompt))
        payload = {
            "model": resolved_model.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.5,
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {resolved_model.api_key}",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.exception("[model] HTTP error status=%s detail=%s", exc.code, _clip(detail))
            raise ModelApiError(f"Model API returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            logger.exception("[model] URL error: %s", exc.reason)
            raise ModelApiError(f"Unable to reach model API: {exc.reason}") from exc

        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            logger.info("[model] raw_response=%s", _clip(raw))
            logger.info("[model] assistant_content=%s", _clip(content))
            return content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("[model] Unexpected response shape raw=%s", _clip(raw))
            raise ModelApiError("Model API returned an unexpected response shape.") from exc
