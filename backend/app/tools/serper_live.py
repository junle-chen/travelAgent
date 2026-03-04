from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, request

from app.core.config import get_settings

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_IMAGES_URL = "https://google.serper.dev/images"
logger = logging.getLogger("travel_agent.tools.serper")


@dataclass(frozen=True)
class SearchItem:
    title: str
    snippet: str
    link: str


@dataclass(frozen=True)
class ImageItem:
    title: str
    image_url: str
    source_url: str | None


class SerperTravelService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> bool:
        config = self.settings.get_tool_env_config(["SERPER_API_KEY"])
        return bool(config.api_key)

    @lru_cache(maxsize=256)
    def search(self, query: str, num: int = 5) -> list[SearchItem]:
        logger.info("[serper] search q=%s num=%s", query, num)
        payload = self._post(SERPER_SEARCH_URL, {"q": query, "num": num})
        organic = payload.get("organic", [])
        if not isinstance(organic, list):
            return []
        results: list[SearchItem] = []
        for item in organic[:num]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if title and link:
                results.append(SearchItem(title=title, snippet=snippet, link=link))
        logger.info("[serper] search results=%s", len(results))
        return results

    @lru_cache(maxsize=256)
    def search_images(self, query: str, num: int = 3) -> list[ImageItem]:
        logger.info("[serper] image_search q=%s num=%s", query, num)
        payload = self._post(SERPER_IMAGES_URL, {"q": query, "num": num})
        images = payload.get("images", [])
        if not isinstance(images, list):
            return []
        results: list[ImageItem] = []
        for item in images[:num]:
            if not isinstance(item, dict):
                continue
            image_url = str(item.get("imageUrl") or item.get("image_url") or "").strip()
            source_url = str(item.get("sourceUrl") or item.get("link") or "").strip() or None
            title = str(item.get("title") or item.get("source") or query).strip()
            if image_url:
                results.append(ImageItem(title=title, image_url=image_url, source_url=source_url))
        logger.info("[serper] image_search results=%s", len(results))
        return results

    def extract_schedule(self, query: str) -> str | None:
        results = self.search(query, num=3)
        for item in results:
            combined = f"{item.title} {item.snippet}"
            times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", combined)
            if len(times) >= 2:
                return f"{times[0]} - {times[1]}"
            if len(times) == 1:
                return times[0]
        return None

    def extract_price(self, query: str) -> str | None:
        results = self.search(query, num=3)
        for item in results:
            combined = f"{item.title} {item.snippet}"
            match = re.search(r"(?:HK\\$|US\\$|\\$|CNY\\s?|RMB\\s?|¥)\\s?([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", combined, re.IGNORECASE)
            if match:
                symbol_match = re.search(r"(HK\\$|US\\$|\\$|CNY\\s?|RMB\\s?|¥)", combined, re.IGNORECASE)
                symbol = symbol_match.group(1).strip() if symbol_match else "$"
                return f"{symbol}{match.group(1)}"
        return None

    def _post(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        config = self.settings.get_tool_env_config(["SERPER_API_KEY"])
        if not config.api_key:
            return {}
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "X-API-KEY": config.api_key,
                "Content-Type": "application/json",
                "User-Agent": "travel-agent/0.1",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, json.JSONDecodeError):
            logger.exception("[serper] request failed url=%s", url)
            return {}
