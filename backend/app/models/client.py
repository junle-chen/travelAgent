from __future__ import annotations

import json
from urllib import error, request

from app.schemas.providers import ResolvedModelConfig


class ModelApiError(RuntimeError):
    pass


class ModelApiClient:
    def complete_json(self, *, resolved_model: ResolvedModelConfig, system_prompt: str, user_prompt: str) -> str:
        if not resolved_model.base_url or not resolved_model.api_key:
            raise ModelApiError("Model configuration is incomplete.")

        endpoint = f"{resolved_model.base_url.rstrip('/')}/v1/chat/completions"
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
            with request.urlopen(http_request, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelApiError(f"Model API returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise ModelApiError(f"Unable to reach model API: {exc.reason}") from exc

        try:
            parsed = json.loads(raw)
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelApiError("Model API returned an unexpected response shape.") from exc
