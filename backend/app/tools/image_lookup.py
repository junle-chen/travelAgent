from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request

USER_AGENT = "travel-agent/0.1 (+https://localhost)"


@dataclass(frozen=True)
class ImageReference:
    title: str
    image_url: str | None
    source_url: str | None


class ImageLookupService:
    def search(self, query: str) -> ImageReference | None:
        cleaned = query.strip()
        if not cleaned:
            return None
        for language in ("zh", "en"):
            result = self._search_wikipedia(cleaned, language)
            if result and result.image_url:
                return result
        return None

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
