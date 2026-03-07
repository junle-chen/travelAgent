from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import error, parse, request

from app.core.config import get_settings

logger = logging.getLogger("travel_agent.tools.amap")


@dataclass(frozen=True)
class AmapPoi:
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None


class AmapTravelService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def available(self) -> bool:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        return bool(config.api_key)

    @lru_cache(maxsize=128)
    def fetch_candidates(self, destination: str) -> dict[str, list[AmapPoi]]:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or not destination.strip():
            return {"hotels": [], "restaurants": [], "attractions": []}
        logger.info("[amap] fetch_candidates destination=%s", destination)

        return {
            "hotels": self._search(destination, f"{destination} 酒店", config.api_key),
            "restaurants": self._search(destination, f"{destination} 餐厅", config.api_key),
            "attractions": self._search(destination, f"{destination} 景点", config.api_key),
        }

    @lru_cache(maxsize=256)
    def lookup_place(self, city: str, keywords: str) -> AmapPoi | None:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or not city.strip() or not keywords.strip():
            return None
        logger.info("[amap] lookup_place city=%s keywords=%s", city, keywords)
        results = self._search(city, keywords, config.api_key, offset=1)
        return results[0] if results else None

    @lru_cache(maxsize=128)
    def geocode_city(self, destination: str) -> tuple[float, float] | None:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or not destination.strip():
            return None
        logger.info("[amap] geocode_city destination=%s", destination)
        url = (
            "https://restapi.amap.com/v3/geocode/geo?"
            + parse.urlencode(
                {
                    "key": config.api_key,
                    "address": destination,
                }
            )
        )
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "travel-agent/0.1"})
        try:
            with request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            logger.warning("[amap] geocode_city failed destination=%s error=%s", destination, exc)
            return None
        geocodes = payload.get("geocodes", [])
        if not isinstance(geocodes, list) or not geocodes:
            return None
        first = geocodes[0]
        if not isinstance(first, dict):
            return None
        location = str(first.get("location") or "").strip()
        if "," not in location:
            return None
        lng_value, lat_value = location.split(",", 1)
        try:
            return (float(lng_value), float(lat_value))
        except ValueError:
            return None

    def build_route_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or len(points) < 2:
            return points
        logger.info("[amap] build_route_points segments=%s", max(len(points) - 1, 0))

        route_points: list[tuple[float, float]] = [points[0]]
        for index in range(len(points) - 1):
            segment = self._walking_route(points[index], points[index + 1], config.api_key)
            if segment:
                route_points.extend(segment[1:])
            else:
                route_points.append(points[index + 1])
        return route_points

    def _search(self, city: str, keywords: str, api_key: str, offset: int = 3) -> list[AmapPoi]:
        url = (
            "https://restapi.amap.com/v3/place/text?"
            + parse.urlencode(
                {
                    "key": api_key,
                    "keywords": keywords,
                    "city": city,
                    "citylimit": "true",
                    "offset": offset,
                    "page": 1,
                    "extensions": "base",
                }
            )
        )
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "travel-agent/0.1"})
        try:
            with request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            logger.warning("[amap] place search failed city=%s keywords=%s error=%s", city, keywords, exc)
            return []

        pois = payload.get("pois", [])
        results: list[AmapPoi] = []
        if not isinstance(pois, list):
            return results
        for item in pois[:3]:
            if not isinstance(item, dict):
                continue
            name = self._clean_name(str(item.get("name") or "").strip())
            if not name:
                continue
            address = str(item.get("address") or item.get("adname") or city).strip()
            if self._is_generic_name(name):
                continue
            latitude = None
            longitude = None
            location = str(item.get("location") or "").strip()
            if "," in location:
                lng_value, lat_value = location.split(",", 1)
                try:
                    longitude = float(lng_value)
                    latitude = float(lat_value)
                except ValueError:
                    longitude = None
                    latitude = None
            results.append(AmapPoi(name=name, address=address or city, latitude=latitude, longitude=longitude))
        return results

    @lru_cache(maxsize=512)
    def _walking_route(self, origin: tuple[float, float], destination: tuple[float, float], api_key: str) -> list[tuple[float, float]]:
        url = (
            "https://restapi.amap.com/v3/direction/walking?"
            + parse.urlencode(
                {
                    "key": api_key,
                    "origin": f"{origin[0]},{origin[1]}",
                    "destination": f"{destination[0]},{destination[1]}",
                }
            )
        )
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "travel-agent/0.1"})
        try:
            with request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            logger.warning("[amap] walking route failed origin=%s destination=%s error=%s", origin, destination, exc)
            return []

        paths = payload.get("route", {}).get("paths", [])
        if not isinstance(paths, list) or not paths:
            return []
        steps = paths[0].get("steps", [])
        if not isinstance(steps, list):
            return []

        points: list[tuple[float, float]] = [origin]
        for step in steps:
            if not isinstance(step, dict):
                continue
            polyline = str(step.get("polyline") or "").strip()
            if not polyline:
                continue
            for pair in polyline.split(";"):
                if "," not in pair:
                    continue
                lng_value, lat_value = pair.split(",", 1)
                try:
                    lng = float(lng_value)
                    lat = float(lat_value)
                except ValueError:
                    continue
                current = (lng, lat)
                if current != points[-1]:
                    points.append(current)
        if points[-1] != destination:
            points.append(destination)
        return points

    @staticmethod
    def _clean_name(name: str) -> str:
        if not name:
            return ""
        chinese_parts = re.findall(r"[\u4e00-\u9fff0-9A-Za-z（）()·\-]+", name)
        if chinese_parts:
            compact = "".join(chinese_parts).strip()
            if any("\u4e00" <= char <= "\u9fff" for char in compact):
                return compact
        return re.sub(r"\s+", " ", name).strip()

    @staticmethod
    def _is_generic_name(name: str) -> bool:
        lowered = name.lower()
        if lowered in {"景点", "观景点", "公园", "restaurant", "hotel"}:
            return True
        if lowered.startswith("a park"):
            return True
        return False
