from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib import error, parse, request

from app.core.config import get_settings
from app.tools.request_cache import get_cached_json, set_cached_json

logger = logging.getLogger("travel_agent.tools.amap")

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
    "altay": "阿勒泰",
    "fuyun": "富蕴",
    "burqin": "布尔津",
    "kanas": "喀纳斯",
    "sailimu": "赛里木湖",
    "yining": "伊宁",
    "ili": "伊犁",
}

EN_KEYWORD_ZH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bneighborhood walk\b", "城市漫步"),
    (r"\blocal culture stop\b", "人文街区"),
    (r"\bsignature landmark\b", "地标景点"),
    (r"\boutbound transport\b", "去程交通"),
    (r"\breturn transfer\b", "返程交通"),
    (r"\barrival transfer\b", "抵达交通"),
    (r"\bhotel check[\s-]?in\b", "酒店入住"),
    (r"\bhighlights?\b", "亮点"),
    (r"\bhistoric district\b", "历史街区"),
    (r"\bcustom destination\b", "目的地"),
    (r"\byour city\b", "出发地"),
    (r"\bactivity\s*\d+\b", "景点"),
    (r"\bday\s*\d+\b", ""),
    (r"\bcheck[\s-]?in\b", "入住"),
    (r"\bhotel\b", "酒店"),
    (r"\bhostel\b", "青旅"),
    (r"\bairport\b", "机场"),
    (r"\btrain station\b", "火车站"),
    (r"\brailway station\b", "火车站"),
    (r"\bstation\b", "车站"),
    (r"\bbus station\b", "汽车站"),
    (r"\bbazaar\b", "大巴扎"),
    (r"\bnight market\b", "夜市"),
    (r"\bfood street\b", "美食街"),
    (r"\bmuseum\b", "博物馆"),
    (r"\bpark\b", "公园"),
    (r"\bscenic area\b", "景区"),
    (r"\blake\b", "湖"),
    (r"\bbridge\b", "大桥"),
)

TYPE_HINT_TOKENS: tuple[str, ...] = (
    "机场",
    "车站",
    "酒店",
    "景区",
    "公园",
    "博物馆",
    "夜市",
    "大巴扎",
    "湖",
    "大桥",
)

AMAP_PLACE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
AMAP_GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
AMAP_ROUTE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 3


@dataclass(frozen=True)
class AmapPoi:
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    province: str = ""
    city: str = ""
    district: str = ""
    poi_type: str = ""


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
        city = self._normalize_city(destination)
        logger.info("[amap] fetch_candidates destination=%s city=%s", destination, city)

        return {
            "hotels": self._search(city, f"{city} 酒店", config.api_key),
            "restaurants": self._search(city, f"{city} 餐厅", config.api_key),
            "attractions": self._search(city, f"{city} 景点", config.api_key),
        }

    @lru_cache(maxsize=256)
    def lookup_place(self, city: str, keywords: str) -> AmapPoi | None:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or not city.strip() or not keywords.strip():
            return None
        normalized_city = self._normalize_city(city)
        normalized_keywords = self._normalize_keywords(keywords)
        if not normalized_keywords:
            return None
        query_variants = [normalized_keywords]
        if normalized_city and normalized_city not in normalized_keywords:
            query_variants.append(f"{normalized_city} {normalized_keywords}")
        query_variants = list(dict.fromkeys(query for query in query_variants if query.strip()))
        logger.info(
            "[amap] lookup_place city=%s normalized_city=%s keywords=%s variants=%s",
            city,
            normalized_city,
            normalized_keywords,
            query_variants,
        )

        scored_candidates: list[tuple[float, AmapPoi, str, bool]] = []
        for query in query_variants:
            used_city_limit = bool(normalized_city)
            city_limited = self._search(normalized_city or city, query, config.api_key, offset=8, city_limit=used_city_limit)
            city_best = self._pick_best_poi(city_limited, query, normalized_city)
            if city_best:
                score, poi = city_best
                scored_candidates.append((score, poi, query, used_city_limit))
                # Exact or near-exact local hit can return immediately.
                if score >= 9.0:
                    return poi

        if not scored_candidates:
            return None
        best_score, best_poi, used_query, from_city_limit = max(scored_candidates, key=lambda item: item[0])
        if best_score < 4.5:
            logger.info(
                "[amap] reject low-confidence match city=%s keywords=%s score=%.2f",
                normalized_city,
                normalized_keywords,
                best_score,
            )
            return None
        logger.info(
            "[amap] lookup_place matched city=%s keywords=%s score=%.2f citylimit=%s query=%s poi=%s",
            normalized_city,
            normalized_keywords,
            best_score,
            from_city_limit,
            used_query,
            best_poi.name,
        )
        return best_poi

    @lru_cache(maxsize=128)
    def geocode_city(self, destination: str) -> tuple[float, float] | None:
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        if not config.api_key or not destination.strip():
            return None
        normalized_destination = self._normalize_city(destination)
        logger.info("[amap] geocode_city destination=%s normalized_destination=%s", destination, normalized_destination)
        url = (
            "https://restapi.amap.com/v3/geocode/geo?"
            + parse.urlencode(
                {
                    "key": config.api_key,
                    "address": normalized_destination,
                }
            )
        )
        payload = self._request_json_cached(
            namespace="amap.geocode",
            cache_key=normalized_destination,
            url=url,
            ttl_seconds=AMAP_GEOCODE_CACHE_TTL_SECONDS,
        )
        if payload is None:
            logger.warning("[amap] geocode_city failed destination=%s", destination)
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

    def estimate_travel_time(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        *,
        preferred_mode: str = "drive",
        city: str | None = None,
    ) -> tuple[str, int]:
        """Return (mode_label, duration_minutes) with API-first and heuristic fallback."""
        config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
        distance_km = self._distance_km(origin, destination)
        api_key = str(config.api_key or "").strip()
        mode = preferred_mode.lower().strip()
        if mode not in {"walk", "drive", "transit", "rail", "flight"}:
            mode = "drive"
        if mode == "walk" and distance_km > 4:
            mode = "drive"
        if mode == "rail":
            mode = "transit" if distance_km <= 35 else "drive"
        if mode == "flight" and distance_km <= 220:
            mode = "drive"

        duration_minutes: int | None = None
        if api_key:
            if mode == "walk":
                duration_minutes = self._walking_duration_minutes(origin, destination, api_key)
            elif mode == "drive":
                duration_minutes = self._driving_duration_minutes(origin, destination, api_key)
            elif mode == "transit":
                city_name = self._normalize_city(city or "")
                duration_minutes = self._transit_duration_minutes(origin, destination, city_name, api_key)

        if duration_minutes is None:
            if preferred_mode == "flight" or distance_km > 900:
                mode_label = "航班"
                duration_minutes = max(90, int(distance_km / 700 * 60) + 110)
            elif preferred_mode == "rail" or distance_km > 180:
                mode_label = "高铁"
                duration_minutes = max(60, int(distance_km / 220 * 60) + 35)
            elif mode == "walk":
                mode_label = "步行"
                duration_minutes = max(8, int(distance_km / 4.5 * 60))
            elif mode == "transit":
                mode_label = "公共交通"
                duration_minutes = max(20, int(distance_km / 28 * 60))
            else:
                mode_label = "驾车"
                duration_minutes = max(15, int(distance_km / 45 * 60))
            return mode_label, duration_minutes

        mode_label = {
            "walk": "步行",
            "drive": "驾车",
            "transit": "公共交通",
        }.get(mode, "驾车")
        return mode_label, max(1, duration_minutes)

    def estimate_travel_leg(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        *,
        preferred_mode: str = "drive",
        city: str | None = None,
    ) -> tuple[str, int, str | None]:
        distance_km = self._distance_km(origin, destination)
        mode_label, minutes = self.estimate_travel_time(
            origin,
            destination,
            preferred_mode=preferred_mode,
            city=city,
        )
        detail: str | None = None
        if mode_label == "公共交通":
            config = self.settings.get_tool_env_config(["AMAP_API_KEY", "AMAP_MAPS_API_KEY"])
            api_key = str(config.api_key or "").strip()
            city_name = self._normalize_city(city or "")
            payload = self._transit_payload(origin, destination, city_name, api_key) if api_key and city_name else None
            detail = self._transit_line_summary(payload)
        elif mode_label == "驾车":
            detail = f"约{distance_km:.1f}公里"
        elif mode_label == "步行":
            detail = f"步行约{distance_km:.1f}公里"
        elif mode_label in {"高铁", "航班"}:
            detail = f"约{distance_km:.0f}公里"
        return mode_label, minutes, detail

    def _request_json_cached(
        self,
        *,
        namespace: str,
        cache_key: str,
        url: str,
        ttl_seconds: int,
    ) -> dict[str, Any] | None:
        cached = get_cached_json(namespace, cache_key, max_age_seconds=ttl_seconds)
        if isinstance(cached, dict):
            return cached
        req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "travel-agent/0.1"})
        try:
            with request.urlopen(req, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
            return None
        set_cached_json(namespace, cache_key, payload)
        return payload

    @staticmethod
    def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
        lon1, lat1 = a
        lon2, lat2 = b
        lat_scale = 111.0
        lon_scale = 111.0 * max(0.2, abs(math.cos(math.radians((lat1 + lat2) / 2.0))))
        return (((lon2 - lon1) * lon_scale) ** 2 + ((lat2 - lat1) * lat_scale) ** 2) ** 0.5

    def _search(
        self,
        city: str,
        keywords: str,
        api_key: str,
        offset: int = 3,
        *,
        city_limit: bool = True,
    ) -> list[AmapPoi]:
        url = (
            "https://restapi.amap.com/v3/place/text?"
            + parse.urlencode(
                {
                    "key": api_key,
                    "keywords": keywords,
                    "city": city,
                    "citylimit": "true" if city_limit and city else "false",
                    "offset": offset,
                    "page": 1,
                    "extensions": "base",
                }
            )
        )
        cache_key = f"{city}|{keywords}|{offset}|{city_limit}"
        payload = self._request_json_cached(
            namespace="amap.place_text",
            cache_key=cache_key,
            url=url,
            ttl_seconds=AMAP_PLACE_CACHE_TTL_SECONDS,
        )
        if payload is None:
            logger.warning("[amap] place search failed city=%s keywords=%s", city, keywords)
            return []

        pois = payload.get("pois", [])
        results: list[AmapPoi] = []
        if not isinstance(pois, list):
            return results
        limit = max(1, min(offset, 20))
        for item in pois[:limit]:
            if not isinstance(item, dict):
                continue
            name = self._clean_name(str(item.get("name") or "").strip())
            if not name:
                continue
            province = str(item.get("pname") or "").strip()
            city_name = str(item.get("cityname") or "").strip()
            district = str(item.get("adname") or "").strip()
            poi_type = str(item.get("type") or "").strip()
            address = str(item.get("address") or district or city).strip()
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
            results.append(
                AmapPoi(
                    name=name,
                    address=address or city,
                    latitude=latitude,
                    longitude=longitude,
                    province=province,
                    city=city_name,
                    district=district,
                    poi_type=poi_type,
                )
            )
        return results

    def _pick_best_poi(self, pois: list[AmapPoi], keyword: str, city: str) -> tuple[float, AmapPoi] | None:
        best_score = float("-inf")
        best_poi: AmapPoi | None = None
        for poi in pois:
            score = self._score_poi(poi, keyword, city)
            if score > best_score:
                best_score = score
                best_poi = poi
        if best_poi is None:
            return None
        return (best_score, best_poi)

    def _score_poi(self, poi: AmapPoi, keyword: str, city: str) -> float:
        keyword_norm = self._normalize_match_text(keyword)
        name_norm = self._normalize_match_text(poi.name)
        city_norm = self._normalize_match_text(city)
        full_address_norm = self._normalize_match_text(
            f"{poi.province} {poi.city} {poi.district} {poi.address} {poi.poi_type}"
        )
        if not keyword_norm or not name_norm:
            return float("-inf")

        score = 0.0
        if keyword_norm == name_norm:
            score += 10.0
        if keyword_norm in name_norm or name_norm in keyword_norm:
            score += 6.0

        score += self._overlap_ratio(keyword_norm, name_norm) * 5.0
        score += self._overlap_ratio(keyword_norm, full_address_norm) * 2.0

        if city_norm and (city_norm in full_address_norm or city_norm in name_norm):
            score += 1.5
        if self._is_generic_name(name_norm):
            score -= 3.0
        if poi.latitude is None or poi.longitude is None:
            score -= 1.0

        combined_norm = f"{name_norm} {full_address_norm}"
        for hint in TYPE_HINT_TOKENS:
            if hint in keyword_norm and hint not in combined_norm:
                score -= 1.2
        return score

    @staticmethod
    def _overlap_ratio(source: str, target: str) -> float:
        if not source or not target:
            return 0.0
        overlap = sum(1 for char in source if char in target)
        return overlap / max(len(source), 1)

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        lowered = value.lower().strip()
        lowered = re.sub(r"^d\d+[-.、]?\d*[-.、\s]*", "", lowered)
        lowered = re.sub(r"\s+", "", lowered)
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", lowered)

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
        cache_key = f"{origin[0]},{origin[1]}->{destination[0]},{destination[1]}"
        payload = self._request_json_cached(
            namespace="amap.walking_route",
            cache_key=cache_key,
            url=url,
            ttl_seconds=AMAP_ROUTE_CACHE_TTL_SECONDS,
        )
        if payload is None:
            logger.warning("[amap] walking route failed origin=%s destination=%s", origin, destination)
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

    @lru_cache(maxsize=2048)
    def _walking_duration_minutes(self, origin: tuple[float, float], destination: tuple[float, float], api_key: str) -> int | None:
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
        cache_key = f"{origin[0]},{origin[1]}->{destination[0]},{destination[1]}"
        payload = self._request_json_cached(
            namespace="amap.walking_duration",
            cache_key=cache_key,
            url=url,
            ttl_seconds=AMAP_ROUTE_CACHE_TTL_SECONDS,
        )
        return self._extract_route_duration_minutes(payload, route_key="paths")

    @lru_cache(maxsize=2048)
    def _driving_duration_minutes(self, origin: tuple[float, float], destination: tuple[float, float], api_key: str) -> int | None:
        url = (
            "https://restapi.amap.com/v3/direction/driving?"
            + parse.urlencode(
                {
                    "key": api_key,
                    "origin": f"{origin[0]},{origin[1]}",
                    "destination": f"{destination[0]},{destination[1]}",
                    "strategy": 0,
                    "extensions": "base",
                }
            )
        )
        cache_key = f"{origin[0]},{origin[1]}->{destination[0]},{destination[1]}"
        payload = self._request_json_cached(
            namespace="amap.driving_duration",
            cache_key=cache_key,
            url=url,
            ttl_seconds=AMAP_ROUTE_CACHE_TTL_SECONDS,
        )
        return self._extract_route_duration_minutes(payload, route_key="paths")

    @lru_cache(maxsize=2048)
    def _transit_duration_minutes(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        city: str,
        api_key: str,
    ) -> int | None:
        payload = self._transit_payload(origin, destination, city, api_key)
        if not isinstance(payload, dict):
            return None
        route = payload.get("route")
        if not isinstance(route, dict):
            return None
        transits = route.get("transits")
        if not isinstance(transits, list) or not transits:
            return None
        first = transits[0]
        if not isinstance(first, dict):
            return None
        duration_raw = first.get("duration")
        return self._duration_to_minutes(duration_raw)

    @lru_cache(maxsize=2048)
    def _transit_payload(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        city: str,
        api_key: str,
    ) -> dict[str, Any] | None:
        if not city or not api_key:
            return None
        url = (
            "https://restapi.amap.com/v3/direction/transit/integrated?"
            + parse.urlencode(
                {
                    "key": api_key,
                    "origin": f"{origin[0]},{origin[1]}",
                    "destination": f"{destination[0]},{destination[1]}",
                    "city": city,
                    "cityd": city,
                    "strategy": 0,
                    "nightflag": 0,
                }
            )
        )
        cache_key = f"{city}|{origin[0]},{origin[1]}->{destination[0]},{destination[1]}"
        return self._request_json_cached(
            namespace="amap.transit_duration",
            cache_key=cache_key,
            url=url,
            ttl_seconds=AMAP_ROUTE_CACHE_TTL_SECONDS,
        )

    @staticmethod
    def _transit_line_summary(payload: dict[str, Any] | None) -> str | None:
        if not isinstance(payload, dict):
            return None
        route = payload.get("route")
        if not isinstance(route, dict):
            return None
        transits = route.get("transits")
        if not isinstance(transits, list) or not transits:
            return None
        first = transits[0]
        if not isinstance(first, dict):
            return None
        segments = first.get("segments")
        if not isinstance(segments, list):
            return None
        lines: list[str] = []
        walking_minutes = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            walking = segment.get("walking")
            if isinstance(walking, dict):
                walk_duration = AmapTravelService._duration_to_minutes(walking.get("duration"))
                if walk_duration:
                    walking_minutes += walk_duration
            bus = segment.get("bus")
            if isinstance(bus, dict):
                buslines = bus.get("buslines")
                if isinstance(buslines, list):
                    for line in buslines[:2]:
                        if not isinstance(line, dict):
                            continue
                        name = str(line.get("name") or "").strip()
                        if name:
                            lines.append(name.split("(")[0].strip())
            railway = segment.get("railway")
            if isinstance(railway, dict):
                name = str(railway.get("name") or "").strip()
                if name:
                    lines.append(name)
        uniq_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq_lines.append(line)
        parts: list[str] = []
        if uniq_lines:
            parts.append(" → ".join(uniq_lines[:3]))
        if walking_minutes > 0:
            parts.append(f"步行约{walking_minutes}分钟")
        return "，".join(parts) if parts else None

    @staticmethod
    def _extract_route_duration_minutes(payload: dict[str, Any] | None, *, route_key: str) -> int | None:
        if not isinstance(payload, dict):
            return None
        route = payload.get("route")
        if not isinstance(route, dict):
            return None
        paths = route.get(route_key)
        if not isinstance(paths, list) or not paths:
            return None
        first = paths[0]
        if not isinstance(first, dict):
            return None
        return AmapTravelService._duration_to_minutes(first.get("duration"))

    @staticmethod
    def _duration_to_minutes(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            seconds = int(float(str(value)))
        except ValueError:
            return None
        return max(1, int(round(seconds / 60)))

    @staticmethod
    def _normalize_city(city: str) -> str:
        cleaned = city.strip()
        lowered = cleaned.lower()
        if lowered in CITY_ZH_ALIASES:
            return CITY_ZH_ALIASES[lowered]
        return cleaned

    @staticmethod
    def _normalize_keywords(keywords: str) -> str:
        cleaned = keywords.strip()
        if not cleaned:
            return cleaned
        raw_lowered = cleaned.lower()
        cleaned = re.sub(r"^d\d+[-.、]?\d*[-.、\s]*", "", cleaned, flags=re.IGNORECASE)
        lowered = cleaned.lower()
        for english, chinese in CITY_ZH_ALIASES.items():
            if english in lowered:
                cleaned = re.sub(re.escape(english), chinese, cleaned, flags=re.IGNORECASE)
                lowered = cleaned.lower()
        for pattern, replacement in EN_KEYWORD_ZH_REPLACEMENTS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("/", " ").replace("_", " ")
        cleaned = re.sub(r"[()（）\[\],;:]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if re.search(r"[A-Za-z]", cleaned):
            # AMap queries should be Chinese to reduce cross-language mismatch.
            cleaned = re.sub(r"\b[A-Za-z]+\b", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            cleaned = AmapTravelService._fallback_keyword_type(raw_lowered)
        return cleaned or "景点"

    @staticmethod
    def _fallback_keyword_type(lowered: str) -> str:
        if any(token in lowered for token in ("hotel", "check-in", "checkin", "hostel", "stay")):
            return "酒店"
        if any(token in lowered for token in ("restaurant", "food", "cafe", "dinner", "lunch", "breakfast", "night market")):
            return "餐厅"
        if any(token in lowered for token in ("airport", "station", "rail", "train", "bus", "transfer")):
            return "交通枢纽"
        if any(token in lowered for token in ("museum",)):
            return "博物馆"
        if any(token in lowered for token in ("park",)):
            return "公园"
        if any(token in lowered for token in ("bridge",)):
            return "大桥"
        if any(token in lowered for token in ("lake",)):
            return "湖"
        return "景点"

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
