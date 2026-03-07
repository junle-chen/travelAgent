from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, request

from app.core.config import get_settings

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
logger = logging.getLogger("travel_agent.tools.tavily")


@dataclass(frozen=True)
class SearchItem:
    title: str
    snippet: str
    link: str


class TavilyTravelService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> bool:
        config = self.settings.get_tool_env_config(["TAVILY_API_KEY"])
        return bool(config.api_key)

    @lru_cache(maxsize=256)
    def search(self, query: str, num: int = 5) -> list[SearchItem]:
        logger.info("[tavily] search q=%s num=%s", query, num)
        payload = self._post(
            {
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(num, 10)),
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False,
            }
        )
        results = payload.get("results", [])
        if not isinstance(results, list):
            return []
        normalized: list[SearchItem] = []
        for item in results[:num]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            link = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or "").strip()
            if title and link:
                normalized.append(SearchItem(title=title, snippet=snippet, link=link))
        logger.info("[tavily] search results=%s", len(normalized))
        return normalized

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
            match = re.search(r"(?:HK\$|US\$|\$|CNY\s?|RMB\s?|¥)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", combined, re.IGNORECASE)
            if match:
                symbol_match = re.search(r"(HK\$|US\$|\$|CNY\s?|RMB\s?|¥)", combined, re.IGNORECASE)
                symbol = symbol_match.group(1).strip() if symbol_match else "$"
                return f"{symbol}{match.group(1)}"
        return None

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        config = self.settings.get_tool_env_config(["TAVILY_API_KEY"])
        if not config.api_key:
            return {}
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            TAVILY_SEARCH_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "travel-agent/0.1",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("[tavily] request failed error=%s", exc)
            return {}
