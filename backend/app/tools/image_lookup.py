from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, parse, request

from app.tools.serpapi_live import SerpApiTravelService
from app.tools.serper_live import SerperTravelService

USER_AGENT = "travel-agent/0.1 (+https://localhost)"
logger = logging.getLogger("travel_agent.tools.images")


@dataclass(frozen=True)
class ImageReference:
    title: str
    image_url: str | None
    source_url: str | None


class ImageLookupService:
    def __init__(self) -> None:
        self.serpapi = SerpApiTravelService()
        self.serper = SerperTravelService()

    @lru_cache(maxsize=512)
    def search(self, query: str) -> ImageReference | None:
        cleaned = query.strip()
        if not cleaned:
            return None
        logger.info("[images] search query=%s", cleaned)
        if self.serpapi.available():
            for variant in self._query_variants(cleaned):
                items = self.serpapi.search_images(variant, num=6)
                ranked = sorted(items, key=lambda item: self._score_image_item(cleaned, item.title), reverse=True)
                for item in ranked:
                    if self._score_image_item(cleaned, item.title) < 6:
                        continue
                    logger.info("[images] serpapi hit title=%s", item.title)
                    return ImageReference(title=item.title or cleaned, image_url=item.image_url, source_url=item.source_url)
        if self.serper.available():
            for variant in self._query_variants(cleaned):
                items = self.serper.search_images(variant, num=6)
                ranked = sorted(items, key=lambda item: self._score_image_item(cleaned, item.title), reverse=True)
                for item in ranked:
                    if self._score_image_item(cleaned, item.title) < 4:
                        continue
                    logger.info("[images] serper hit title=%s", item.title)
                    return ImageReference(title=item.title or cleaned, image_url=item.image_url, source_url=item.source_url)
        for language in ("zh", "en"):
            result = self._search_wikipedia(cleaned, language)
            if result and result.image_url:
                logger.info("[images] wikipedia hit title=%s", result.title)
                return result
        logger.info("[images] no match query=%s", cleaned)
        return None

    @staticmethod
    def _query_variants(query: str) -> list[str]:
        variants: list[str] = []
        seen: set[str] = set()
        candidates = [
            query,
            re.sub(r"\([^)]*\)", "", query).strip(),
            query.replace("Hotel ", "").strip(),
            query.replace("24h", "").strip(),
        ]
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate).strip(" -")
            if normalized and normalized not in seen:
                seen.add(normalized)
                variants.append(normalized)
        return variants

    @staticmethod
    def _score_image_item(query: str, title: str) -> int:
        query_tokens = [token.lower() for token in re.split(r"[\s,/()-]+", query) if token]
        title_lower = title.lower()
        score = 0
        for token in query_tokens:
            if token in title_lower:
                score += 3
        if query.lower() in title_lower:
            score += 6
        return score

    def _search_wikipedia(self, query: str, language: str) -> ImageReference | None:
        direct_match = self._fetch_summary(query, language)
        if direct_match and direct_match.image_url:
            return direct_match

        api_url = (
            f"https://{language}.wikipedia.org/w/api.php?"
            + parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "utf8": 1,
                    "srlimit": 1,
                }
            )
        )
        try:
            with request.urlopen(self._request(api_url), timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError):
            return None

        search_results = payload.get("query", {}).get("search", [])
        if not search_results:
            return None
        title = search_results[0].get("title")
        if not title:
            return None
        return self._fetch_summary(title, language)

    @staticmethod
    def _request(url: str) -> request.Request:
        return request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    def _fetch_summary(self, title: str, language: str) -> ImageReference | None:
        summary_url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{parse.quote(title)}"
        try:
            with request.urlopen(self._request(summary_url), timeout=8) as response:
                summary = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError):
            return None

        image_url = None
        thumbnail = summary.get("thumbnail")
        if isinstance(thumbnail, dict):
            image_url = thumbnail.get("source")
        if not image_url:
            original = summary.get("originalimage")
            if isinstance(original, dict):
                image_url = original.get("source")

        page_url = None
        content_urls = summary.get("content_urls")
        if isinstance(content_urls, dict):
            desktop = content_urls.get("desktop")
            if isinstance(desktop, dict):
                page_url = desktop.get("page")

        return ImageReference(title=str(summary.get("title", title)), image_url=image_url, source_url=page_url)

    @lru_cache(maxsize=512)
    def verified_image(self, query: str) -> ImageReference | None:
        result = self.search(query)
        if not result or not result.image_url:
            return None
        return result

    def _is_image_url_live(self, url: str) -> bool:
        req = request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        try:
            with request.urlopen(req, timeout=8) as response:
                content_type = response.headers.get("Content-Type", "")
                return response.status < 400 and content_type.startswith("image/")
        except error.HTTPError as exc:
            if exc.code in {405, 403}:
                pass
            else:
                return False
        except error.URLError:
            return False

        fallback_req = request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"})
        try:
            with request.urlopen(fallback_req, timeout=8) as response:
                content_type = response.headers.get("Content-Type", "")
                return response.status < 400 and content_type.startswith("image/")
        except (error.URLError, error.HTTPError):
            return False
