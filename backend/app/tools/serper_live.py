from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, request

from app.core.config import get_settings
from app.tools.request_cache import get_cached_json, set_cached_json

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_IMAGES_URL = "https://google.serper.dev/images"
logger = logging.getLogger("travel_agent.tools.serper")
SERPER_CACHE_TTL_SECONDS = 60 * 60 * 6
CITY_ZH_ALIASES: dict[str, str] = {
    "beijing": "北京",
    "shanghai": "上海",
    "shenzhen": "深圳",
    "guangzhou": "广州",
    "hangzhou": "杭州",
    "xiamen": "厦门",
    "chengdu": "成都",
    "nanjing": "南京",
    "suzhou": "苏州",
    "wuhan": "武汉",
    "changsha": "长沙",
    "hong kong": "香港",
    "hongkong": "香港",
    "xinjiang": "新疆",
    "north xinjiang": "北疆",
    "northern xinjiang": "北疆",
    "south xinjiang": "南疆",
    "southern xinjiang": "南疆",
    "urumqi": "乌鲁木齐",
    "yining": "伊宁",
    "ili": "伊犁",
}


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


@dataclass(frozen=True)
class FlightOption:
    title: str
    link: str
    schedule: str | None
    price: str | None


@dataclass(frozen=True)
class HotelRate:
    title: str
    link: str
    nightly_price: str | None


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

    def _parse_image_results(self, payload: dict[str, object], query: str, num: int) -> list[ImageItem]:
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
        return results

    @lru_cache(maxsize=256)
    def search_images(self, query: str, num: int = 3) -> list[ImageItem]:
        logger.info("[serper] image_search q=%s num=%s", query, num)
        payload = self._post(SERPER_IMAGES_URL, {"q": query, "num": num})
        results = self._parse_image_results(payload, query, num)
        logger.info("[serper] image_search results=%s", len(results))
        return results

    def search_images_live(self, query: str, num: int = 3) -> list[ImageItem]:
        logger.info("[serper] image_search_live q=%s num=%s", query, num)
        payload = self._post(SERPER_IMAGES_URL, {"q": query, "num": num}, use_cache=False)
        results = self._parse_image_results(payload, query, num)
        logger.info("[serper] image_search_live results=%s", len(results))
        return results

    def search_images_cached_only(self, query: str, num: int = 3) -> list[ImageItem]:
        config = self.settings.get_tool_env_config(["SERPER_API_KEY"])
        if not config.api_key:
            return []
        cache_key = json.dumps({"url": SERPER_IMAGES_URL, "payload": {"q": query, "num": num}}, ensure_ascii=False, sort_keys=True)
        cached = get_cached_json("serper.post", cache_key, max_age_seconds=SERPER_CACHE_TTL_SECONDS)
        if not isinstance(cached, dict):
            return []
        return self._parse_image_results(cached, query, num)

    def extract_schedule(self, query: str) -> str | None:
        results = self.search(query, num=3)
        for item in results:
            schedule = self._extract_schedule_text(f"{item.title} {item.snippet}")
            if schedule:
                return schedule
        return None

    def extract_price(self, query: str) -> str | None:
        results = self.search(query, num=3)
        for item in results:
            price = self._extract_price_text(f"{item.title} {item.snippet}")
            if price:
                return price
        return None

    @lru_cache(maxsize=256)
    def search_flights(self, origin: str, destination: str, date: str, num: int = 3) -> list[FlightOption]:
        normalized_origin = self._normalize_city_name(origin)
        normalized_destination = self._normalize_city_name(destination)
        if self._should_use_chinese(normalized_origin, normalized_destination):
            query = (
                f"site:google.com/travel/flights {normalized_origin} 到 {normalized_destination} {date} "
                "机票 航班 价格 起飞 到达"
            )
        else:
            query = (
                f"site:google.com/travel/flights {normalized_origin} to {normalized_destination} {date} "
                "flight price departure arrival"
            )
        items = self.search(query, num=max(1, min(num, 6)))
        options: list[FlightOption] = []
        for item in items:
            combined = f"{item.title} {item.snippet}"
            options.append(
                FlightOption(
                    title=item.title,
                    link=item.link,
                    schedule=self._extract_schedule_text(combined),
                    price=self._extract_price_text(combined),
                )
            )
        return options

    @lru_cache(maxsize=256)
    def search_hotel_rates(
        self,
        hotel_name: str,
        destination: str,
        check_in_date: str,
        num: int = 3,
    ) -> list[HotelRate]:
        normalized_destination = self._normalize_city_name(destination)
        if self._should_use_chinese(hotel_name, normalized_destination):
            query = f"{hotel_name} {normalized_destination} 酒店 每晚 价格 {check_in_date} 预订"
        else:
            query = f"{hotel_name} {normalized_destination} hotel nightly price {check_in_date} booking"
        items = self.search(query, num=max(1, min(num, 6)))
        rates: list[HotelRate] = []
        for item in items:
            combined = f"{item.title} {item.snippet}"
            rates.append(
                HotelRate(
                    title=item.title,
                    link=item.link,
                    nightly_price=self._extract_price_text(combined),
                )
            )
        return rates

    @staticmethod
    def _extract_schedule_text(text: str) -> str | None:
        times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
        if len(times) >= 2:
            return f"{times[0]} - {times[1]}"
        if len(times) == 1:
            return times[0]
        return None

    @staticmethod
    def _extract_price_text(text: str) -> str | None:
        match = re.search(r"(?:HK\\$|US\\$|\\$|CNY\\s?|RMB\\s?|¥)\\s?([0-9][0-9,]*(?:\\.[0-9]{1,2})?)", text, re.IGNORECASE)
        if not match:
            return None
        symbol_match = re.search(r"(HK\\$|US\\$|\\$|CNY\\s?|RMB\\s?|¥)", text, re.IGNORECASE)
        symbol = symbol_match.group(1).strip() if symbol_match else "$"
        return f"{symbol}{match.group(1)}"

    def _post(self, url: str, payload: dict[str, object], *, use_cache: bool = True) -> dict[str, object]:
        config = self.settings.get_tool_env_config(["SERPER_API_KEY"])
        if not config.api_key:
            return {}
        cache_key = json.dumps({"url": url, "payload": payload}, ensure_ascii=False, sort_keys=True)
        if use_cache:
            cached = get_cached_json("serper.post", cache_key, max_age_seconds=SERPER_CACHE_TTL_SECONDS)
            if isinstance(cached, dict):
                return cached
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
            with request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
                if use_cache:
                    set_cached_json("serper.post", cache_key, data)
                return data
        except (error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("[serper] request failed url=%s error=%s", url, exc)
            return {}

    @staticmethod
    def _contains_chinese(text: str | None) -> bool:
        if not text:
            return False
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    @staticmethod
    def _normalize_city_name(city: str) -> str:
        cleaned = city.strip()
        lowered = cleaned.lower()
        return CITY_ZH_ALIASES.get(lowered, cleaned)

    def _should_use_chinese(self, *values: str) -> bool:
        merged = " ".join(value for value in values if value).strip()
        if not merged:
            return False
        if self._contains_chinese(merged):
            return True
        lowered = merged.lower()
        compact = lowered.replace(" ", "")
        return any(
            token in lowered or token.replace(" ", "") in compact
            for token in ["china", "beijing", "shanghai", "shenzhen", "xinjiang", "hong kong", "taiwan", "macau"]
        )
