from __future__ import annotations

import json
import logging
import time
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
    def complete_json(self, *, resolved_model: ResolvedModelConfig, system_prompt: str, user_prompt: str, max_retries: int = 3) -> str:
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
        
        raw = ""
        for attempt in range(max_retries):
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
                break  # Success
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                    sleep_time = 2.0 * (attempt + 1)
                    logger.warning("[model] HTTP %s on attempt %s, retrying in %ss: %s", exc.code, attempt + 1, sleep_time, _clip(detail))
                    time.sleep(sleep_time)
                    continue
                logger.exception("[model] HTTP error status=%s detail=%s", exc.code, _clip(detail))
                raise ModelApiError(f"Model API returned HTTP {exc.code}: {detail}") from exc
            except (error.URLError, TimeoutError) as exc:
                if attempt < max_retries - 1:
                    sleep_time = 2.0 * (attempt + 1)
                    logger.warning("[model] Network error on attempt %s, retrying in %ss: %s", attempt + 1, sleep_time, exc)
                    time.sleep(sleep_time)
                    continue
                logger.exception("[model] URL error: %s", exc)
                raise ModelApiError(f"Unable to reach model API: {exc}") from exc

        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            logger.info("[model] raw_response=%s", _clip(raw))
            logger.info("[model] assistant_content=%s", _clip(content))
            return content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.exception("[model] Unexpected response shape raw=%s", _clip(raw))
            raise ModelApiError("Model API returned an unexpected response shape.") from exc
