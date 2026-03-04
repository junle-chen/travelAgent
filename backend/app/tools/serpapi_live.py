from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, parse, request

from app.core.config import get_settings

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
logger = logging.getLogger("travel_agent.tools.serpapi")


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


class SerpApiTravelService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> bool:
        config = self.settings.get_tool_env_config(["SERPAPI_API_KEY"])
        return bool(config.api_key)

    @lru_cache(maxsize=256)
    def search(self, query: str, num: int = 5) -> list[SearchItem]:
        logger.info("[serpapi] search q=%s num=%s", query, num)
        payload = self._get(
            {
                "engine": "google",
                "q": query,
                "num": max(1, min(num, 10)),
                "google_domain": "google.com",
                "hl": "en",
                "gl": "hk",
            }
        )
        organic = payload.get("organic_results", [])
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
        logger.info("[serpapi] search results=%s", len(results))
        return results

    @lru_cache(maxsize=256)
    def search_images(self, query: str, num: int = 5) -> list[ImageItem]:
        logger.info("[serpapi] image_search q=%s num=%s", query, num)
        payload = self._get(
            {
                "engine": "google_images",
                "q": query,
                "ijn": "0",
                "hl": "en",
                "gl": "hk",
            }
        )
        images = payload.get("images_results", [])
        if not isinstance(images, list):
            return []
        results: list[ImageItem] = []
        for item in images[:num]:
            if not isinstance(item, dict):
                continue
            image_url = str(item.get("original") or item.get("thumbnail") or "").strip()
            source_url = str(item.get("link") or item.get("source") or "").strip() or None
            title = str(item.get("title") or query).strip()
            if image_url:
                results.append(ImageItem(title=title, image_url=image_url, source_url=source_url))
        logger.info("[serpapi] image_search results=%s", len(results))
        return results

    @lru_cache(maxsize=256)
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

    @lru_cache(maxsize=256)
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

    def _get(self, params: dict[str, object]) -> dict[str, object]:
        config = self.settings.get_tool_env_config(["SERPAPI_API_KEY"])
        if not config.api_key:
            return {}
        query = dict(params)
        query["api_key"] = config.api_key
        url = f"{SERPAPI_SEARCH_URL}?{parse.urlencode(query)}"
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "travel-agent/0.1"})
        try:
            with request.urlopen(req, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, json.JSONDecodeError):
            logger.exception("[serpapi] request failed")
            return {}
