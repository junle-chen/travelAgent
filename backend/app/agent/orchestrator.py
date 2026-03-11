from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
from urllib.parse import quote_plus
from uuid import uuid4

from app.agent.intent_parser import parse_intent
from app.agent.langchain_bridge import render_chat_prompts
from app.models.client import ModelApiClient
from app.schemas.domain import (
    BudgetSummary,
    ClarificationQuestion,
    DayPlan,
    MapPreview,
    MemorySummary,
    PlanSummary,
    ReferenceLink,
    RoutePoint,
    TimelineEvent,
    TravelLogistics,
    TripState,
    VisualReference,
)
from app.schemas.providers import ProviderWarning, ResolvedModelConfig
from app.tools.amap_live import AmapTravelService
from app.tools.concurrent_utils import parallel_call, parallel_map
from app.tools.image_lookup import ImageLookupService
from app.tools.request_cache import get_cached_json, set_cached_json
from app.tools.serper_live import FlightOption, HotelRate, SerperTravelService
from app.tools.tavily_live import TavilyTravelService
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger("travel_agent.planner")

PLACEHOLDER_IMAGES = {
    "scenic": None,
    "food": None,
    "hotel": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80",
    "transport": "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?auto=format&fit=crop&w=1200&q=80",
    "default": None,
}
IMAGE_LOOKUP = ImageLookupService()
AMAP_TRAVEL = AmapTravelService()
SERPER_TRAVEL = SerperTravelService()
TAVILY_TRAVEL = TavilyTravelService()
SCENIC_IMAGE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
MAINLAND_CITY_HINTS = {
    "beijing",
    "shanghai",
    "shenzhen",
    "guangzhou",
    "hangzhou",
    "xiamen",
    "chengdu",
    "nanjing",
    "suzhou",
    "wuhan",
    "changsha",
}
MAINLAND_CITY_HINTS_ZH = {
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "厦门",
    "成都",
    "南京",
    "苏州",
    "武汉",
    "长沙",
    "乌鲁木齐",
    "伊宁",
    "伊犁",
}
GREATER_CHINA_HINTS = {
    "china",
    "mainland",
    "beijing",
    "shanghai",
    "shenzhen",
    "guangzhou",
    "hangzhou",
    "xiamen",
    "chengdu",
    "nanjing",
    "suzhou",
    "wuhan",
    "changsha",
    "urumqi",
    "xinjiang",
    "north xinjiang",
    "south xinjiang",
    "hong kong",
    "hongkong",
    "macau",
    "taiwan",
    "中国",
    "大陆",
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "厦门",
    "成都",
    "南京",
    "苏州",
    "武汉",
    "长沙",
    "乌鲁木齐",
    "新疆",
    "北疆",
    "南疆",
    "香港",
    "澳门",
    "台湾",
}
FALLBACK_ATTRACTIONS = {
    "beijing": [
        ("故宫博物院", "景山前街4号"),
        ("慕田峪长城", "怀柔区渤海镇慕田峪村"),
        ("南锣鼓巷", "东城区南锣鼓巷"),
        ("天坛公园", "东城区天坛东里甲1号"),
        ("颐和园", "海淀区新建宫门路19号"),
    ],
    "shenzhen": [
        ("平安金融中心观光层", "福田区益田路5033号"),
        ("莲花山公园", "福田区红荔路6030号"),
        ("深圳湾公园", "南山区滨海大道"),
        ("世界之窗", "南山区深南大道9037号"),
        ("华侨城创意文化园", "南山区锦绣北街2号"),
    ],
    "xinjiang": [
        ("新疆国际大巴扎", "乌鲁木齐市天山区解放南路8号"),
        ("天山天池风景区", "昌吉回族自治州阜康市"),
        ("新疆维吾尔自治区博物馆", "乌鲁木齐市沙依巴克区西北路132号"),
        ("红山公园", "乌鲁木齐市水磨沟区红山路"),
        ("可可托海国家地质公园", "阿勒泰地区富蕴县可可托海镇"),
        ("可可托海三号矿坑", "阿勒泰地区富蕴县可可托海镇"),
        ("五彩滩风景区", "阿勒泰地区布尔津县五彩滩景区"),
        ("布尔津河堤夜市", "阿勒泰地区布尔津县"),
        ("喀纳斯湖景区", "阿勒泰地区布尔津县喀纳斯景区"),
        ("观鱼台", "阿勒泰地区喀纳斯景区内"),
        ("喀纳斯村", "阿勒泰地区布尔津县喀纳斯村"),
        ("月亮湾", "阿勒泰地区喀纳斯景区内"),
        ("神仙湾", "阿勒泰地区喀纳斯景区内"),
        ("卧龙湾", "阿勒泰地区喀纳斯景区内"),
        ("禾木村", "阿勒泰地区布尔津县禾木哈纳斯蒙古族乡"),
        ("禾木观景台", "阿勒泰地区禾木景区"),
        ("世界魔鬼城", "克拉玛依市乌尔禾区"),
        ("赛里木湖风景名胜区", "博尔塔拉蒙古自治州博乐市"),
        ("果子沟大桥", "伊犁哈萨克自治州霍城县连霍高速"),
        ("喀赞其民俗旅游区", "伊犁哈萨克自治州伊宁市"),
        ("六星街", "伊犁哈萨克自治州伊宁市"),
        ("那拉提草原", "伊犁哈萨克自治州新源县那拉提镇"),
    ],
    "north xinjiang": [
        ("可可托海国家地质公园", "阿勒泰地区富蕴县可可托海镇"),
        ("五彩滩风景区", "阿勒泰地区布尔津县五彩滩景区"),
        ("喀纳斯湖景区", "阿勒泰地区布尔津县喀纳斯景区"),
        ("禾木村", "阿勒泰地区布尔津县禾木哈纳斯蒙古族乡"),
        ("世界魔鬼城", "克拉玛依市乌尔禾区"),
        ("赛里木湖风景名胜区", "博尔塔拉蒙古自治州博乐市"),
        ("果子沟大桥", "伊犁哈萨克自治州霍城县连霍高速"),
        ("喀赞其民俗旅游区", "伊犁哈萨克自治州伊宁市"),
        ("六星街", "伊犁哈萨克自治州伊宁市"),
        ("那拉提草原", "伊犁哈萨克自治州新源县那拉提镇"),
    ],
    "新疆": [
        ("新疆国际大巴扎", "乌鲁木齐市天山区解放南路8号"),
        ("天山天池风景区", "昌吉回族自治州阜康市"),
        ("可可托海国家地质公园", "阿勒泰地区富蕴县可可托海镇"),
        ("五彩滩风景区", "阿勒泰地区布尔津县五彩滩景区"),
        ("喀纳斯湖景区", "阿勒泰地区布尔津县喀纳斯景区"),
        ("禾木村", "阿勒泰地区布尔津县禾木哈纳斯蒙古族乡"),
        ("世界魔鬼城", "克拉玛依市乌尔禾区"),
        ("赛里木湖风景名胜区", "博尔塔拉蒙古自治州博乐市"),
        ("果子沟大桥", "伊犁哈萨克自治州霍城县连霍高速"),
        ("六星街", "伊犁哈萨克自治州伊宁市"),
    ],
    "北疆": [
        ("可可托海国家地质公园", "阿勒泰地区富蕴县可可托海镇"),
        ("可可托海三号矿坑", "阿勒泰地区富蕴县可可托海镇"),
        ("五彩滩风景区", "阿勒泰地区布尔津县五彩滩景区"),
        ("喀纳斯湖景区", "阿勒泰地区布尔津县喀纳斯景区"),
        ("禾木村", "阿勒泰地区布尔津县禾木哈纳斯蒙古族乡"),
        ("世界魔鬼城", "克拉玛依市乌尔禾区"),
        ("赛里木湖风景名胜区", "博尔塔拉蒙古自治州博乐市"),
        ("果子沟大桥", "伊犁哈萨克自治州霍城县连霍高速"),
        ("喀赞其民俗旅游区", "伊犁哈萨克自治州伊宁市"),
        ("六星街", "伊犁哈萨克自治州伊宁市"),
    ],
}
GENERIC_SCENIC_TITLES = {
    "neighborhood walk",
    "signature landmark",
    "park walk",
    "observation deck",
    "观景点",
    "a park一个公园",
}
BEIJING_TICKET_RULES: list[tuple[tuple[str, ...], str]] = [
    (("故宫", "紫禁城"), "¥60（旺季，淡季¥40，需预约，周一闭馆）"),
    (("八达岭长城",), "¥40（缆车往返约¥140）"),
    (("慕田峪长城",), "¥40（缆车约¥100-140）"),
    (("颐和园",), "¥30（旺季，淡季¥20，联票约¥60）"),
    (("天坛", "天坛公园"), "¥15（旺季，淡季¥10，联票约¥34）"),
    (("圆明园",), "¥10（遗址区约¥25）"),
    (("北海公园",), "¥10（旺季，淡季¥5）"),
    (("景山公园",), "¥2"),
    (("北京动物园",), "¥15（熊猫馆另收费）"),
    (("香山公园",), "¥10（旺季，淡季¥5）"),
    (("天安门广场",), "¥0（免费，需安检）"),
    (("中国国家博物馆", "国家博物馆"), "¥0（免费，需预约）"),
    (("什刹海", "后海"), "¥0（免费）"),
    (("南锣鼓巷",), "¥0（免费）"),
    (("奥林匹克公园",), "¥0（免费）"),
]
FOOD_IMAGE_POOL = [
    "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1559339352-11d035aa65de?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1515003197210-e0cd71810b5f?auto=format&fit=crop&w=1200&q=80",
]
SCENIC_IMAGE_POOL = [
    "https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1469474968028-56623f02e42e?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1473447198193-3d6f62c5f1f1?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1454496522488-7a8e488e8606?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=1200&q=80",
]
DEFAULT_DAY_THEMES_EN = [
    "Arrival & Orientation",
    "Neighborhood Highlights",
    "Local Culture",
    "Flexible Favorites",
    "Natural Landscapes",
    "Food & Leisure",
    "Historic Core",
    "Scenic Loop",
    "Slow Travel",
    "Departure Day",
]
DEFAULT_DAY_THEMES_ZH = [
    "抵达适应",
    "城市亮点",
    "在地人文",
    "弹性机动",
    "自然风景",
    "美食休闲",
    "历史街区",
    "环线打卡",
    "慢节奏体验",
    "返程收尾",
]
GENERIC_DAY_THEMES = {"highlight", "highlights", "亮点", "精选", "day highlights", "day highlight", "行程亮点"}


def _placeholder_image(kind: str) -> str | None:
    return PLACEHOLDER_IMAGES.get(kind, PLACEHOLDER_IMAGES["default"])


def _stable_index(seed: str, size: int) -> int:
    if size <= 0:
        return 0
    return sum(ord(char) for char in seed) % size


def _food_image_for(seed: str) -> str:
    return FOOD_IMAGE_POOL[_stable_index(seed, len(FOOD_IMAGE_POOL))]


def _scenic_image_for(seed: str) -> str:
    return SCENIC_IMAGE_POOL[_stable_index(seed, len(SCENIC_IMAGE_POOL))]


def _contains_chinese(text: str | None) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _should_use_chinese(destination: str | None, origin: str | None = None) -> bool:
    merged = " ".join(value for value in [destination or "", origin or ""] if value).strip()
    if not merged:
        return False
    if _contains_chinese(merged):
        return True
    lowered = merged.lower()
    compact = lowered.replace(" ", "")
    return any(token in lowered or token.replace(" ", "") in compact for token in GREATER_CHINA_HINTS)


def _display_city_name(city: str, *, use_chinese: bool) -> str:
    if use_chinese:
        return _normalize_city_for_geocode(city)
    return city.strip()


def _classify_event(title: str) -> str:
    lowered = title.lower()
    station_to_station = bool(re.search(r"站\s*(?:至|到|→|->|to)\s*.*站", title, re.IGNORECASE))
    if any(word in lowered for word in ["flight", "train", "transfer", "arrival", "return", "ferry"]) or any(
        token in title for token in ["出发", "到达", "抵达", "前往", "去程", "返程", "回程", "返回", "接驳", "航班", "高铁", "动车", "火车", "乘车", "中转", "机场", "车站"]
    ) or station_to_station:
        return "transport"
    if any(word in lowered for word in ["breakfast", "lunch", "dinner", "restaurant", "cafe", "market"]) or any(
        token in title for token in ["早餐", "午餐", "晚餐", "餐厅", "美食", "夜市", "小吃"]
    ):
        return "food"
    if "hotel" in lowered or "check-in" in lowered or any(token in title for token in ["酒店", "入住", "民宿"]):
        return "hotel"
    return "scenic"


def _sort_key(value: str) -> int:
    try:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return 0


def _default_day_theme(day_index: int, *, use_chinese: bool = False) -> str:
    source = DEFAULT_DAY_THEMES_ZH if use_chinese else DEFAULT_DAY_THEMES_EN
    return source[day_index % len(source)]


def _normalize_day_theme(theme: str | None, day_index: int, *, use_chinese: bool = False) -> str:
    if not theme:
        return _default_day_theme(day_index, use_chinese=use_chinese)
    cleaned = theme.strip()
    if not cleaned:
        return _default_day_theme(day_index, use_chinese=use_chinese)
    if use_chinese and not _contains_chinese(cleaned):
        return _default_day_theme(day_index, use_chinese=True)
    lowered = cleaned.lower()
    if lowered in GENERIC_DAY_THEMES or any(lowered.startswith(prefix) for prefix in ("day ", "d1 ", "d2 ")):
        return _default_day_theme(day_index, use_chinese=use_chinese)
    return cleaned


def _is_generic_activity_title(title: str) -> bool:
    lowered = title.lower().strip()
    if re.fullmatch(r"activity\s*\d+", lowered):
        return True
    if re.fullmatch(r"d\d+[-.\s]*activity\s*\d*", lowered):
        return True
    if re.fullmatch(r"(景点|活动)\s*\d+", title.strip()):
        return True
    return lowered in {"activity", "景点", "活动", "推荐景点", "推荐活动"}


def _is_food_focused_style(style: str | None) -> bool:
    if not style:
        return False
    lowered = style.lower()
    return "food" in lowered or any(token in style for token in ["美食", "餐", "吃"])


def _is_generic_hotel_reference(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {
        "hotel",
        "hotel check-in",
        "city check-in",
        "central hotel",
        "recommended hotel",
        "recommended area",
    }:
        return True
    if any(token in text for token in ["酒店入住", "换城入住", "推荐区域", "市中心酒店"]):
        return True
    if re.fullmatch(r"(hotel|酒店)\s*\d*", lowered):
        return True
    return False


def _suggest_city_hotel_with_model(
    *,
    city: str,
    destination: str,
    use_chinese: bool,
    resolved_model: ResolvedModelConfig | None,
    model_client: ModelApiClient | None,
) -> str | None:
    if model_client is None or resolved_model is None or resolved_model.source == "mock":
        return None
    city_label = _normalize_city_for_geocode(city)
    prompt = (
        "你是旅行规划助手。请只输出严格 JSON：{\"hotel_name\":\"\"}。"
        "给定城市后，返回一个看起来真实、常见、且位于该城市的酒店名称，不要返回泛化词（如市中心酒店/推荐酒店）。"
        if use_chinese
        else "You are a travel planner. Output strict JSON only: {\"hotel_name\":\"\"}. "
        "Given a city, return one plausible real hotel name in that city, not generic placeholders."
    )
    try:
        raw = model_client.complete_json(
            resolved_model=resolved_model,
            system_prompt="You output valid JSON only.",
            user_prompt=f"{prompt}\nCity: {city_label}\nDestination context: {destination}",
        )
        parsed = _extract_json_object(raw)
        hotel_name = str(parsed.get("hotel_name") or "").strip()
        if hotel_name and not _is_generic_hotel_reference(hotel_name):
            return hotel_name
    except Exception:
        return None
    return None


def _estimate_hotel_nightly_with_model(
    *,
    city: str,
    hotel_name: str,
    use_chinese: bool,
    resolved_model: ResolvedModelConfig | None,
    model_client: ModelApiClient | None,
) -> float | None:
    if model_client is None or resolved_model is None or resolved_model.source == "mock":
        return None
    city_label = _normalize_city_for_geocode(city)
    prompt = (
        "请根据城市与酒店名估算每晚房价（人民币），并只输出严格 JSON：{\"nightly_rmb\": 420}。"
        "要求输出一个合理整数，范围 120 到 5000。"
        if use_chinese
        else "Estimate a reasonable nightly room price in CNY from city and hotel name. "
        "Output strict JSON only: {\"nightly_rmb\": 420}. Must be an integer between 120 and 5000."
    )
    try:
        raw = model_client.complete_json(
            resolved_model=resolved_model,
            system_prompt="You output valid JSON only.",
            user_prompt=f"{prompt}\nCity: {city_label}\nHotel: {hotel_name}",
        )
        parsed = _extract_json_object(raw)
        value = parsed.get("nightly_rmb")
        amount = float(value) if isinstance(value, (int, float, str)) and str(value).strip() else None
        if amount is None:
            return None
        if 120 <= amount <= 5000:
            return float(amount)
    except Exception:
        return None
    return None


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    # Fast-enough planar approximation for city-bound filtering.
    lon1, lat1 = a
    lon2, lat2 = b
    lat_scale = 111.0
    lon_scale = 111.0 * max(0.2, abs(math.cos(math.radians((lat1 + lat2) / 2.0))))
    return (((lon2 - lon1) * lon_scale) ** 2 + ((lat2 - lat1) * lat_scale) ** 2) ** 0.5


# Regional / multi-city destinations need a wider radius for POI filtering.
_WIDE_REGION_TOKENS = {
    "xinjiang", "新疆", "tibet", "西藏", "inner mongolia", "内蒙古",
    "yunnan", "云南", "sichuan", "四川", "qinghai", "青海",
    "gansu", "甘肃", "heilongjiang", "黑龙江", "guangxi", "广西",
    "north xinjiang", "south xinjiang", "northern xinjiang", "southern xinjiang",
    "北疆", "南疆", "川西", "滇西",
}


def _is_north_xinjiang_destination(destination: str) -> bool:
    lowered = _normalize_city_for_geocode(destination).lower().strip()
    return any(token in lowered for token in {"north xinjiang", "northern xinjiang", "北疆"})

_REGION_ANCHORS: dict[str, tuple[float, float]] = {
    "新疆": (87.61, 43.82), # Urumqi
    "北疆": (87.61, 43.82),
    "南疆": (75.99, 39.47), # Kashgar
    "xinjiang": (87.61, 43.82),
    "西藏": (91.14, 29.64), # Lhasa
    "tibet": (91.14, 29.64),
    "内蒙古": (111.76, 40.84), # Hohhot
    "inner mongolia": (111.76, 40.84),
    "云南": (102.71, 25.04), # Kunming
    "yunnan": (102.71, 25.04),
    "四川": (104.06, 30.65), # Chengdu
    "sichuan": (104.06, 30.65),
    "青海": (101.77, 36.62), # Xining
    "qinghai": (101.77, 36.62),
    "甘肃": (103.82, 36.05), # Lanzhou
    "gansu": (103.82, 36.05),
    "黑龙江": (126.64, 45.75), # Harbin
    "heilongjiang": (126.64, 45.75),
    "广西": (108.36, 22.81), # Nanning
    "guangxi": (108.36, 22.81),
    "海南": (110.32, 20.03), # Haikou
    "hainan": (110.32, 20.03),
}

_CITY_ANCHORS: dict[str, tuple[float, float]] = {
    "beijing": (116.4074, 39.9042),
    "shanghai": (121.4737, 31.2304),
    "shenzhen": (114.0579, 22.5431),
    "guangzhou": (113.2644, 23.1291),
    "hangzhou": (120.1551, 30.2741),
    "xiamen": (118.0894, 24.4798),
    "chengdu": (104.0665, 30.5728),
    "nanjing": (118.7969, 32.0603),
    "suzhou": (120.5853, 31.2989),
    "wuhan": (114.3054, 30.5931),
    "changsha": (112.9388, 28.2282),
    "urumqi": (87.6168, 43.8256),
    "yining": (81.3179, 43.9228),
    "ili": (81.3242, 43.9169),
    "altay": (88.1396, 47.8484),
    "burqin": (86.8619, 48.2011),
    "fuyun": (89.5268, 46.9944),
    "buerjin": (86.8619, 48.2011),
    "bole": (82.0722, 44.9060),
    "klamayi": (84.8892, 45.5799),
    "kuitun": (84.9000, 44.4269),
    "aletai": (88.1396, 47.8484),
    "阿勒泰": (88.1396, 47.8484),
    "阿勒泰地区": (88.1396, 47.8484),
    "布尔津": (86.8619, 48.2011),
    "布尔津县": (86.8619, 48.2011),
    "富蕴": (89.5268, 46.9944),
    "富蕴县": (89.5268, 46.9944),
    "博乐": (82.0722, 44.9060),
    "博乐市": (82.0722, 44.9060),
    "克拉玛依": (84.8892, 45.5799),
    "奎屯": (84.9000, 44.4269),
    "霍城": (80.8788, 44.0477),
    "霍城县": (80.8788, 44.0477),
    "新源": (83.2585, 43.4340),
    "新源县": (83.2585, 43.4340),
    "hong kong": (114.1694, 22.3193),
    "香港": (114.1694, 22.3193),
    "北京": (116.4074, 39.9042),
    "上海": (121.4737, 31.2304),
    "深圳": (114.0579, 22.5431),
    "广州": (113.2644, 23.1291),
    "杭州": (120.1551, 30.2741),
    "厦门": (118.0894, 24.4798),
    "成都": (104.0665, 30.5728),
    "乌鲁木齐": (87.6168, 43.8256),
    "伊宁": (81.3179, 43.9228),
    "伊犁": (81.3242, 43.9169),
}

_CITY_ZH_ALIAS: dict[str, str] = {
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
    "aletai": "阿勒泰",
    "fuyun": "富蕴",
    "burqin": "布尔津",
    "buerjin": "布尔津",
    "bole": "博乐",
    "klamayi": "克拉玛依",
    "kuitun": "奎屯",
    "kanas": "喀纳斯",
    "sailimu": "赛里木湖",
    "yining": "伊宁",
    "ili": "伊犁",
}


def _normalize_city_for_geocode(city: str) -> str:
    cleaned = city.strip()
    lowered = cleaned.lower()
    return _CITY_ZH_ALIAS.get(lowered, cleaned)


def _fallback_attractions_for(destination: str) -> list[tuple[str, str]]:
    normalized = _normalize_city_for_geocode(destination).strip()
    keys = [destination.strip(), destination.strip().lower(), normalized, normalized.lower()]
    for key in keys:
        if key in FALLBACK_ATTRACTIONS:
            return FALLBACK_ATTRACTIONS[key]
    return FALLBACK_ATTRACTIONS.get(destination.lower(), [])


def _extract_city_from_text(text: str) -> str | None:
    lowered = text.lower()
    compact = lowered.replace(" ", "")
    for key in _CITY_ANCHORS:
        key_lower = key.lower()
        key_compact = key_lower.replace(" ", "")
        if key_lower in lowered or key_compact in compact:
            return _normalize_city_for_geocode(key)
    return None

def _resolve_destination_anchor(destination: str) -> tuple[float, float] | None:
    normalized_destination = _normalize_city_for_geocode(destination)
    lowered = normalized_destination.lower().strip()
    compact = lowered.replace(" ", "")
    for key, anchor in _CITY_ANCHORS.items():
        key_lower = key.lower()
        if key_lower in lowered or key_lower.replace(" ", "") in compact:
            return anchor
    for key, anchor in _REGION_ANCHORS.items():
        if key in lowered:
            return anchor
    if not AMAP_TRAVEL.available():
        return None
    geocoded = AMAP_TRAVEL.geocode_city(normalized_destination)
    if geocoded:
        return geocoded
    poi = AMAP_TRAVEL.lookup_place(normalized_destination, normalized_destination)
    if poi and poi.latitude is not None and poi.longitude is not None:
        return (poi.longitude, poi.latitude)
    return None

def _destination_radius_km(destination: str) -> float:
    """Return max allowed distance (km) from destination center for POI validation."""
    lowered = _normalize_city_for_geocode(destination).lower().strip()
    if _is_north_xinjiang_destination(lowered):
        return 780.0
    if any(token in lowered for token in _WIDE_REGION_TOKENS):
        return 1200.0
    return 80.0


def _is_multi_city_itinerary(
    destination: str,
    timeline_days: list[DayPlan],
    logistics: TravelLogistics | None = None,
) -> bool:
    normalized_destination = _normalize_city_for_geocode(destination)
    destination_lower = normalized_destination.lower().strip()
    if any(token in destination_lower for token in _WIDE_REGION_TOKENS):
        return True

    distinct_city_hints: set[str] = set()
    transport_hops = 0
    for day in timeline_days:
        for event in day.events:
            combined_text = f"{event.title} {event.location}".strip()
            if any(token in combined_text.lower() for token in _WIDE_REGION_TOKENS):
                return True
            city_hint = _extract_city_from_text(combined_text)
            if city_hint and city_hint.lower() != destination_lower:
                distinct_city_hints.add(city_hint.lower())
            if _classify_event(event.title) == "transport":
                transport_hops += 1

    if logistics:
        origin_hint = _normalize_city_for_geocode(logistics.origin).lower().strip()
        if origin_hint and origin_hint not in {"your city", destination_lower}:
            distinct_city_hints.add(origin_hint)
    return len(distinct_city_hints) >= 2 or transport_hops >= 3


def _effective_route_radius_km(
    destination: str,
    timeline_days: list[DayPlan],
    logistics: TravelLogistics | None = None,
) -> float:
    base = _destination_radius_km(destination)
    if _is_north_xinjiang_destination(destination):
        return max(base, 780.0)
    if _is_multi_city_itinerary(destination, timeline_days, logistics):
        return max(base, 1200.0)
    return base


def _validate_amap_poi(
    poi: Any,
    destination_center: tuple[float, float] | None,
    max_radius_km: float,
) -> bool:
    """Return True if the POI's coordinates are within max_radius_km of destination_center."""
    if poi is None:
        return False
    if poi.latitude is None or poi.longitude is None:
        return True  # No coordinates to check, pass through
    if destination_center is None:
        return True  # No anchor to compare, pass through
    dist = _distance_km(destination_center, (poi.longitude, poi.latitude))
    if dist > max_radius_km:
        logger.info(
            "[validate] skip out-of-region POI name=%s dist=%.0fkm max=%skm",
            getattr(poi, 'name', '?'), dist, max_radius_km,
        )
        return False
    return True


def _default_departure_dates(duration_days: int) -> tuple[datetime, datetime]:
    today = datetime.now(timezone.utc)
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    outbound = (today + timedelta(days=days_until_saturday)).replace(hour=8, minute=0, second=0, microsecond=0)
    inbound = outbound + timedelta(days=max(duration_days, 1))
    return outbound, inbound


def _choose_transport_mode(origin: str, destination: str) -> str:
    origin_lower = origin.lower()
    destination_lower = destination.lower()
    if origin in {"Your city", "你的城市"} or destination in {"Custom Destination", "待定目的地"}:
        return "Best available transfer"
    if _is_north_xinjiang_destination(destination):
        return "Flight"
    if any(token in origin_lower for token in ["hong kong", "tokyo", "singapore"]) or any(
        token in destination_lower for token in ["hong kong", "tokyo", "singapore"]
    ):
        return "Flight"
    origin_anchor = _resolve_destination_anchor(origin)
    destination_anchor = _resolve_destination_anchor(destination)
    if origin_anchor and destination_anchor and _distance_km(origin_anchor, destination_anchor) >= 1500:
        return "Flight"
    origin_is_mainland = any(city in origin_lower for city in MAINLAND_CITY_HINTS) or any(city in origin for city in MAINLAND_CITY_HINTS_ZH)
    destination_is_mainland = any(city in destination_lower for city in MAINLAND_CITY_HINTS) or any(
        city in destination for city in MAINLAND_CITY_HINTS_ZH
    )
    if origin_is_mainland and destination_is_mainland:
        return "High-speed rail"
    return "Flight"


def _format_schedule_range(date_value: datetime, schedule: str | None, *, approximate: bool, use_chinese: bool = False) -> str:
    label = date_value.strftime("%Y-%m-%d") if use_chinese else date_value.strftime("%a, %b %d")
    if schedule:
        return f"{label} {schedule}"
    if approximate:
        return f"{label} 预计" if use_chinese else f"{label} approximate"
    return label


def _normalize_budget_preference(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if _parse_cost_amount(cleaned) is not None:
        return cleaned
    if any(token in lowered for token in ("low", "budget", "economy", "省钱", "实惠", "低预算")):
        return "low"
    if any(token in lowered for token in ("high", "luxury", "premium", "奢华", "高预算", "高端")):
        return "high"
    if any(token in lowered for token in ("balanced", "balance", "mid-range", "midrange", "moderate", "中等", "均衡", "平衡")):
        return "balanced"
    return cleaned


def _normalize_defaults(parsed: dict[str, str | int | None], *, interaction_mode: str) -> dict[str, str | int | None]:
    normalized = dict(parsed)
    if isinstance(normalized.get("origin"), str):
        normalized["origin"] = _normalize_city_for_geocode(str(normalized.get("origin") or ""))
    if isinstance(normalized.get("destination"), str):
        normalized["destination"] = _normalize_city_for_geocode(str(normalized.get("destination") or ""))
    if normalized.get("duration_days") is None:
        normalized["duration_days"] = 3
    if normalized.get("budget") is None and interaction_mode == "direct":
        normalized["budget"] = "balanced"
    elif isinstance(normalized.get("budget"), str):
        normalized["budget"] = _normalize_budget_preference(str(normalized.get("budget")))
    if normalized.get("style") is None and interaction_mode == "direct":
        normalized["style"] = "Balanced"
    if normalized.get("travelers") is None:
        normalized["travelers"] = 1 if interaction_mode == "direct" else None
    if normalized.get("origin") is None:
        normalized["origin"] = "Your city" if interaction_mode == "direct" else None
    if normalized.get("destination") is None and interaction_mode == "direct":
        normalized["destination"] = "Custom Destination"
    use_chinese = _should_use_chinese(
        str(normalized.get("destination")) if normalized.get("destination") else None,
        str(normalized.get("origin")) if normalized.get("origin") else None,
    )
    if use_chinese:
        if normalized.get("origin") in {"Your city", None} and interaction_mode == "direct":
            normalized["origin"] = "你的城市"
        if normalized.get("destination") in {"Custom Destination", None} and interaction_mode == "direct":
            normalized["destination"] = "待定目的地"
    return normalized


def _planning_questions(parsed: dict[str, str | int | None]) -> list[ClarificationQuestion]:
    questions: list[ClarificationQuestion] = []
    if parsed.get("origin") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="origin",
                label="Start",
                question="Where are you starting from?",
                suggestions=["Shenzhen", "Guangzhou", "Singapore"],
            )
        )
    if parsed.get("destination") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="destination",
                label="Destination",
                question="Where do you want to go?",
                suggestions=["Hong Kong", "Tokyo", "Hangzhou"],
            )
        )
    if parsed.get("travelers") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="travelers",
                label="Travelers",
                question="How many people are traveling?",
                suggestions=["1", "2", "3", "4"],
            )
        )
    if parsed.get("budget") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="budget",
                label="Budget",
                question="Choose a budget level:",
                suggestions=["low", "balance", "high"],
            )
        )
    if parsed.get("style") in (None, ""):
        questions.append(
            ClarificationQuestion(
                id="style",
                label="Preference",
                question="What travel style do you prefer?",
                suggestions=["Relaxed", "Food focused", "Family friendly", "Packed"],
            )
        )
    return questions[:5]


def _build_day(day_index: int, destination: str, style: str | None, budget: str | None) -> DayPlan:
    use_chinese = _should_use_chinese(destination)
    normalized_destination = _display_city_name(destination, use_chinese=use_chinese)
    theme = _default_day_theme(day_index, use_chinese=use_chinese)
    day_title = f"第{day_index + 1}天" if use_chinese else f"Day {day_index + 1}"
    base_hour = 9
    events: list[TimelineEvent] = []
    fallback_pool = _fallback_attractions_for(normalized_destination)
    scenic_stops: list[tuple[str, str]] = []
    if fallback_pool:
        start = day_index * 3
        seen_titles: set[str] = set()
        cursor = start
        while len(scenic_stops) < 3 and len(seen_titles) < len(fallback_pool):
            name, address = fallback_pool[cursor % len(fallback_pool)]
            cursor += 1
            if name in seen_titles:
                continue
            seen_titles.add(name)
            scenic_stops.append((name, address))
    if use_chinese:
        if not scenic_stops:
            scenic_stops = [
                (f"{normalized_destination}核心景点", normalized_destination),
                (f"{normalized_destination}地标景点", normalized_destination),
                (f"{normalized_destination}人文街区", normalized_destination),
            ]
        while len(scenic_stops) < 3:
            fallback_label = f"{normalized_destination}推荐打卡点{len(scenic_stops) + 1}"
            scenic_stops.append((fallback_label, normalized_destination))
        labels = [
            (scenic_stops[0][0], scenic_stops[0][1], "15 分钟", "¥0", "从交通顺路的核心景点开始，减少首段移动成本。"),
            (scenic_stops[1][0], scenic_stops[1][1], "20 分钟", "¥120", "第二站安排同片区代表景点，保持路线连续。"),
            (scenic_stops[2][0], scenic_stops[2][1], "15 分钟", "¥80", "下午继续在相邻片区游览，避免跨城折返。"),
        ]
    else:
        labels = [
            ("Neighborhood Walk", f"{normalized_destination} center", "15 min", "$0", "Start with a walkable anchor zone to reduce transit overhead."),
            ("Signature Landmark", f"{normalized_destination} landmark", "18 min", "$25", "Prioritize one headline attraction at a comfortable pace."),
            ("Local Culture Stop", f"{normalized_destination} historic district", "15 min", "$15", "Layer in a second meaningful stop instead of routine meal filler."),
        ]
    if _is_food_focused_style(style):
        if use_chinese:
            labels.append(("高分美食站", f"{normalized_destination}美食街区", "12 分钟", "¥120", "加入一站口碑本地美食，贴合美食导向行程。"))
        else:
            labels.append(
                ("Standout Food Pick", f"{normalized_destination} dining district", "12 min", "$30", "Include one worthwhile food stop because the trip is food-led.")
            )
    budget_profile = _normalize_budget_preference(budget)
    for index, (label, location, travel, cost, description) in enumerate(labels):
        if budget_profile == "low" and cost not in {"$0", "¥0"}:
            cost = "¥60" if use_chinese else "$15"
        elif budget_profile == "high":
            cost = "¥300" if use_chinese else "$60"
        start_hour = base_hour + index * 3
        events.append(
            TimelineEvent(
                id=f"d{day_index + 1}-e{index + 1}",
                start_time=f"{start_hour:02d}:00",
                end_time=f"{start_hour + 2:02d}:00",
                title=label,
                location=location,
                travel_time_from_previous=travel,
                cost_estimate=cost,
                description=description
                if style != "Packed pace"
                else ("更紧凑的节奏，适合高密度打卡。" if use_chinese else "A denser cadence tuned for a high-energy day."),
                image_url=_placeholder_image(_classify_event(label)) if _classify_event(label) in {"scenic", "food"} else None,
                risk_flags=[],
            )
        )
    return DayPlan(day_index=day_index, title=day_title, theme=theme, events=events)


def _north_xinjiang_day_templates() -> list[list[tuple[str, str, str]]]:
    # (title, location, description)
    return [
        [
            ("天山天池风景区", "昌吉回族自治州阜康市天山天池景区", "从乌鲁木齐出发前往天池，适应高原气候并开启北疆环线。"),
            ("新疆国际大巴扎", "乌鲁木齐市天山区解放南路8号", "傍晚在大巴扎感受丝路夜市氛围。"),
        ],
        [
            ("可可托海国家地质公园", "阿勒泰地区富蕴县可可托海镇", "北上进入阿勒泰山地，安排全天地质公园深度游。"),
            ("可可托海三号矿坑", "阿勒泰地区富蕴县可可托海镇", "补充工业遗址与矿业历史打卡。"),
        ],
        [
            ("五彩滩风景区", "阿勒泰地区布尔津县五彩滩景区", "沿额尔齐斯河前往布尔津，日落时段观赏雅丹地貌。"),
            ("布尔津河堤夜市", "阿勒泰地区布尔津县河堤夜市", "夜间在布尔津补给并休整。"),
        ],
        [
            ("喀纳斯湖景区", "阿勒泰地区布尔津县喀纳斯景区", "进入喀纳斯核心区，安排完整湖区游览。"),
            ("观鱼台", "阿勒泰地区喀纳斯景区观鱼台", "登高俯瞰湖面与山谷，避免往返折返。"),
        ],
        [
            ("禾木村", "阿勒泰地区布尔津县禾木哈纳斯蒙古族乡", "转场禾木，体验图瓦村落与森林河谷景观。"),
            ("禾木观景台", "阿勒泰地区禾木景区观景台", "傍晚在观景台完成日落拍摄。"),
        ],
        [
            ("世界魔鬼城", "克拉玛依市乌尔禾区世界魔鬼城景区", "南下乌尔禾，串联地貌景观保持线路单向推进。"),
            ("乌尔禾胡杨林", "克拉玛依市乌尔禾区胡杨林景区", "补充同片区轻徒步，减少跨区移动。"),
        ],
        [
            ("赛里木湖风景名胜区", "博尔塔拉蒙古自治州博乐市赛里木湖景区", "西行至赛里木湖，全天湖区环线游览。"),
            ("果子沟大桥", "伊犁哈萨克自治州霍城县连霍高速果子沟大桥", "下山经果子沟进入伊犁河谷。"),
        ],
        [
            ("喀赞其民俗旅游区", "伊犁哈萨克自治州伊宁市喀赞其民俗旅游区", "在伊宁安排人文街区与轻松城市节奏。"),
            ("六星街", "伊犁哈萨克自治州伊宁市六星街", "同城步行串联，减少重复交通。"),
        ],
        [
            ("新疆维吾尔自治区博物馆", "乌鲁木齐市沙依巴克区西北路132号", "返程回到乌鲁木齐，安排室内文化参观。"),
            ("红山公园", "乌鲁木齐市水磨沟区红山路", "傍晚轻松观景，保证返程前留足休息时间。"),
        ],
        [
            ("自治区博物馆文创街区", "乌鲁木齐市沙依巴克区西北路132号", "最后一天安排市区收尾，衔接返程航班。"),
            ("地窝堡机场出发准备", "乌鲁木齐地窝堡国际机场", "预留值机和安检时间，避免末日赶路。"),
        ],
    ]


_NORTH_XINJIANG_SCENIC_COORDS: dict[str, tuple[float, float]] = {
    # value = (latitude, longitude)
    "天山天池风景区": (43.8922, 88.1217),
    "新疆国际大巴扎": (43.7797, 87.6177),
    "可可托海国家地质公园": (47.2156, 89.8963),
    "可可托海三号矿坑": (47.2363, 89.5270),
    "五彩滩风景区": (48.1258, 86.7082),
    "布尔津河堤夜市": (48.0606, 86.8726),
    "喀纳斯湖景区": (48.6934, 86.9861),
    "观鱼台": (48.7054, 87.0273),
    "禾木村": (48.4459, 87.1518),
    "禾木观景台": (48.4436, 87.1489),
    "世界魔鬼城": (46.1398, 85.7792),
    "乌尔禾胡杨林": (46.0798, 85.7246),
    "赛里木湖风景名胜区": (44.6178, 81.1757),
    "果子沟大桥": (44.3097, 81.0720),
    "喀赞其民俗旅游区": (43.9122, 81.3302),
    "六星街": (43.9196, 81.3225),
    "新疆维吾尔自治区博物馆": (43.8066, 87.5889),
    "红山公园": (43.8204, 87.6178),
    "自治区博物馆文创街区": (43.8066, 87.5889),
    "地窝堡机场出发准备": (43.9071, 87.4742),
}


def _north_xinjiang_scenic_coord(title: str) -> tuple[float, float] | None:
    return _NORTH_XINJIANG_SCENIC_COORDS.get(title.strip())


def _force_north_xinjiang_logistics(logistics: TravelLogistics, *, use_chinese: bool) -> None:
    logistics.destination = "北疆" if use_chinese else "North Xinjiang"
    logistics.outbound_transport = "去程航班" if use_chinese else "Outbound flight"
    logistics.return_transport = "返程航班" if use_chinese else "Return flight"


def _enforce_north_xinjiang_loop(
    timeline_days: list[DayPlan],
    logistics: TravelLogistics,
    *,
    requested_destination: str | None = None,
) -> None:
    north_xinjiang_requested = _is_north_xinjiang_destination(logistics.destination) or (
        bool(requested_destination) and _is_north_xinjiang_destination(str(requested_destination))
    )
    if not timeline_days or not north_xinjiang_requested:
        return
    language_hint = str(requested_destination) if requested_destination else logistics.destination
    use_chinese = _should_use_chinese(language_hint, logistics.origin)
    templates = _north_xinjiang_day_templates()
    for day in timeline_days:
        template = templates[min(day.day_index, len(templates) - 1)]
        preserved = [event for event in day.events if _classify_event(event.title) in {"transport", "hotel"}]
        scenic_events: list[TimelineEvent] = []
        start_slots = ["09:30", "14:30"]
        end_slots = ["12:00", "17:30"]
        for idx, (title, location, description) in enumerate(template[:2]):
            coords = _north_xinjiang_scenic_coord(title)
            scenic_events.append(
                TimelineEvent(
                    id=f"d{day.day_index + 1}-nx-s{idx + 1}",
                    start_time=start_slots[idx],
                    end_time=end_slots[idx],
                    title=title,
                    location=location,
                    travel_time_from_previous="25 分钟" if use_chinese else "25 min",
                    cost_estimate=None,
                    description=description,
                    image_url=None,
                    latitude=coords[0] if coords else None,
                    longitude=coords[1] if coords else None,
                    risk_flags=[],
                )
            )
        day.events = preserved + scenic_events
        day.events.sort(key=lambda event: _sort_key(event.start_time))

    _force_north_xinjiang_logistics(logistics, use_chinese=use_chinese)
    if timeline_days:
        first_day = timeline_days[0]
        last_day = timeline_days[-1]
        for event in first_day.events:
            if _classify_event(event.title) == "transport":
                event.title = "抵达乌鲁木齐地窝堡国际机场" if use_chinese else "Arrive at Urumqi Diwopu International Airport"
                event.location = (
                    f"{logistics.origin} 至 乌鲁木齐地窝堡国际机场"
                    if use_chinese
                    else f"{logistics.origin} to Urumqi Diwopu International Airport"
                )
                event.description = "搭乘航班抵达乌鲁木齐，正式开始北疆环线。" if use_chinese else "Fly into Urumqi to start the North Xinjiang loop."
                break
        for event in last_day.events:
            if _classify_event(event.title) == "transport":
                event.title = "乌鲁木齐地窝堡国际机场返程" if use_chinese else "Return via Urumqi Diwopu International Airport"
                event.location = (
                    f"乌鲁木齐地窝堡国际机场 至 {logistics.origin}"
                    if use_chinese
                    else f"Urumqi Diwopu International Airport to {logistics.origin}"
                )
                event.description = "环线回到乌鲁木齐后返程，形成闭环不绕路。" if use_chinese else "Return home from Urumqi to complete the loop."
                break


def _city_stay_lengths_by_day(
    timeline_days: list[DayPlan],
    destination: str,
) -> dict[int, int]:
    day_cities: list[str] = []
    for day in timeline_days:
        day_cities.append((_day_primary_city(day, destination) or _normalize_city_for_geocode(destination)).strip())
    lengths: dict[int, int] = {}
    idx = 0
    while idx < len(day_cities):
        city = day_cities[idx]
        cursor = idx + 1
        while cursor < len(day_cities) and day_cities[cursor] == city:
            cursor += 1
        block = cursor - idx
        for j in range(idx, cursor):
            lengths[j] = block
        idx = cursor
    return lengths


def _apply_known_ticket_prices(destination: str, timeline_days: list[DayPlan]) -> None:
    destination_text = _normalize_city_for_geocode(destination).lower().strip()
    contains_beijing = destination_text in {"北京", "beijing"} or "北京" in destination_text or "beijing" in destination_text
    if not contains_beijing:
        for day in timeline_days:
            for event in day.events:
                if _classify_event(event.title) != "scenic":
                    continue
                combined = f"{event.title} {event.location}"
                if any(keyword in combined for keywords, _ in BEIJING_TICKET_RULES for keyword in keywords):
                    contains_beijing = True
                    break
            if contains_beijing:
                break
    if not contains_beijing:
        return

    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "scenic":
                continue
            combined = f"{event.title} {event.location}"
            for keywords, label in BEIJING_TICKET_RULES:
                if any(keyword in combined for keyword in keywords):
                    event.cost_estimate = label
                    break


def _ensure_city_hotel_policy(
    destination: str,
    timeline_days: list[DayPlan],
    logistics: TravelLogistics,
    *,
    resolved_model: ResolvedModelConfig | None = None,
    model_client: ModelApiClient | None = None,
) -> None:
    if not timeline_days:
        return
    use_chinese = _should_use_chinese(destination, logistics.origin)
    day_cities = [(_day_primary_city(day, destination) or _normalize_city_for_geocode(destination)).strip() for day in timeline_days]
    blocks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(day_cities):
        city = day_cities[start]
        end = start + 1
        while end < len(day_cities) and day_cities[end] == city:
            end += 1
        blocks.append((start, end - 1, city))
        start = end

    def pick_city_hotel(city: str, fallback_name: str | None = None) -> str:
        normalized_city = _normalize_city_for_geocode(city)
        if fallback_name and not _is_generic_hotel_reference(fallback_name):
            return fallback_name
        if AMAP_TRAVEL.available():
            hotels = AMAP_TRAVEL.fetch_candidates(normalized_city).get("hotels", [])
            if hotels and hotels[0].name:
                return hotels[0].name
        suggested = _suggest_city_hotel_with_model(
            city=normalized_city,
            destination=destination,
            use_chinese=use_chinese,
            resolved_model=resolved_model,
            model_client=model_client,
        )
        if suggested:
            return suggested
        return f"{normalized_city}市中心酒店" if use_chinese else f"{normalized_city} Central Hotel"

    last_day_index = len(timeline_days) - 1
    for block_start, block_end, city in blocks:
        existing_events: list[TimelineEvent] = []
        for day_index in range(block_start, block_end + 1):
            day = timeline_days[day_index]
            for event in day.events:
                if _classify_event(event.title) == "hotel":
                    existing_events.append(event)
        canonical_hotel = pick_city_hotel(
            city,
            next((event.location for event in existing_events if event.location and not _is_generic_hotel_reference(event.location)), None),
        )
        start_day = timeline_days[block_start]
        if block_start == last_day_index and any(
            _classify_event(event.title) == "transport" and event.id.endswith("-return")
            for event in start_day.events
        ):
            start_day.events = [event for event in start_day.events if _classify_event(event.title) != "hotel"]
            continue
        start_day_hotels = [event for event in start_day.events if _classify_event(event.title) == "hotel"]
        if start_day_hotels:
            keep_event = start_day_hotels[0]
            keep_event.location = canonical_hotel
            keep_event.title = "酒店入住" if use_chinese else "Hotel Check-in"
            keep_event.start_time = keep_event.start_time or "20:00"
            keep_event.end_time = keep_event.end_time or "21:00"
            keep_event.description = (
                f"在{city}办理 {canonical_hotel} 入住，建议连续入住{block_end - block_start + 1}晚。"
                if use_chinese
                else f"Check in at {canonical_hotel} in {city} for {block_end - block_start + 1} night(s)."
            )
            start_day.events = [event for event in start_day.events if _classify_event(event.title) != "hotel" or event.id == keep_event.id]
        else:
            start_day.events.append(
                TimelineEvent(
                    id=f"d{start_day.day_index + 1}-hotel",
                    start_time="20:00",
                    end_time="21:00",
                    title="酒店入住" if use_chinese else "Hotel Check-in",
                    location=canonical_hotel,
                    travel_time_from_previous="20 分钟" if use_chinese else "20 min",
                    cost_estimate=None,
                    description=(
                        f"在{city}办理 {canonical_hotel} 入住，建议连续入住{block_end - block_start + 1}晚。"
                        if use_chinese
                        else f"Check in at {canonical_hotel} in {city} for {block_end - block_start + 1} night(s)."
                    ),
                    image_url=None,
                    risk_flags=[],
                )
            )
        for day_index in range(block_start + 1, block_end + 1):
            day = timeline_days[day_index]
            day.events = [event for event in day.events if _classify_event(event.title) != "hotel"]

    last_day = timeline_days[-1]
    if any(_classify_event(event.title) == "transport" and event.id.endswith("-return") for event in last_day.events):
        last_day.events = [event for event in last_day.events if _classify_event(event.title) != "hotel"]

    logistics.hotel_name = next(
        (
            event.location
            for day in timeline_days
            for event in day.events
            if _classify_event(event.title) == "hotel" and event.location.strip()
        ),
        logistics.hotel_name,
    )
    for day in timeline_days:
        day.events.sort(key=lambda event: _sort_key(event.start_time))


def _default_logistics(parsed: dict[str, str | int | None]) -> TravelLogistics:
    destination = str(parsed.get("destination") or "Custom Destination")
    travelers = int(parsed.get("travelers") or 1)
    origin = str(parsed.get("origin") or "Your city")
    use_chinese = _should_use_chinese(destination, origin)
    destination = _display_city_name(destination, use_chinese=use_chinese)
    origin = _display_city_name(origin, use_chinese=use_chinese)
    if use_chinese and origin == "Your city":
        origin = "你的城市"
    if use_chinese and destination == "Custom Destination":
        destination = "待定目的地"
    transport_mode = _choose_transport_mode(origin, destination)
    outbound_date, return_date = _default_departure_dates(int(parsed.get("duration_days") or 3))
    if transport_mode == "High-speed rail":
        if use_chinese:
            outbound = f"高铁前往{destination}"
            inbound = f"高铁返回{origin}"
        else:
            outbound = f"High-speed rail to {destination}"
            inbound = f"High-speed rail back to {origin}"
    elif transport_mode == "Best available transfer":
        if use_chinese:
            outbound = f"综合交通前往{destination}"
            inbound = f"综合交通返回{origin}"
        else:
            outbound = f"Best available transfer to {destination}"
            inbound = f"Return transfer from {destination}"
    else:
        if use_chinese:
            outbound = f"航班前往{destination}"
            inbound = f"航班返回{origin}"
        else:
            outbound = f"Flight to {destination}"
            inbound = f"Flight back to {origin}"
    hotel_name = f"{destination}市中心酒店" if use_chinese else f"{destination} Central Hotel"
    return TravelLogistics(
        origin=origin,
        destination=destination,
        travelers=travelers,
        outbound_transport=outbound,
        return_transport=inbound,
        outbound_schedule=_format_schedule_range(outbound_date, None, approximate=True, use_chinese=use_chinese),
        return_schedule=_format_schedule_range(return_date, None, approximate=True, use_chinese=use_chinese),
        hotel_name=hotel_name,
    )


def _search_attraction_candidates(destination: str) -> list[tuple[str, str]]:
    service = _active_search_service()
    if not service:
        return []
    use_chinese = _should_use_chinese(destination)
    query = f"{destination} 必去景点 地标 景区 攻略" if use_chinese else f"{destination} famous attractions landmarks travel guide"
    results = service.search(query, num=5)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in results:
        if not _result_mentions_destination(destination, _search_item_text(item)):
            continue
        headline = item.title.split(" - ")[0].split(" | ")[0].strip()
        headline = headline.replace(f"{destination} ", "").strip()
        if not headline or len(headline) < 2:
            continue
        lowered = headline.lower()
        if lowered in seen:
            continue
        if any(token in lowered for token in ["travel guide", "itinerary", "tripadvisor", "best things", "攻略", "路线", "一日游"]):
            continue
        seen.add(lowered)
        candidates.append((headline, destination))
    return candidates[:3]


def _search_food_candidates(destination: str) -> list[tuple[str, str]]:
    service = _active_search_service()
    if not service:
        return []
    use_chinese = _should_use_chinese(destination)
    query = f"{destination} 当地美食 必吃餐厅 排行" if use_chinese else f"{destination} best local restaurants famous food"
    results = service.search(query, num=4)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in results:
        if not _result_mentions_destination(destination, _search_item_text(item)):
            continue
        headline = item.title.split(" - ")[0].split(" | ")[0].strip()
        if not headline or len(headline) < 2:
            continue
        lowered = headline.lower()
        if lowered in seen:
            continue
        if any(token in lowered for token in ["tripadvisor", "best", "guide", "restaurants in"]):
            continue
        seen.add(lowered)
        candidates.append((headline, destination))
    return candidates[:2]


def _active_search_service() -> Any | None:
    if SERPER_TRAVEL.available():
        return SERPER_TRAVEL
    if TAVILY_TRAVEL.available():
        return TAVILY_TRAVEL
    return None


def _search_item_text(item: Any) -> str:
    title = str(getattr(item, "title", "") or "")
    snippet = str(getattr(item, "snippet", "") or "")
    return f"{title} {snippet}".strip()


def _result_mentions_destination(destination: str, text: str) -> bool:
    destination_lower = destination.lower().strip()
    normalized_text = text.lower().strip()
    if not destination_lower:
        return True
    normalized_destination = _normalize_city_for_geocode(destination).lower().strip()
    candidates = {destination_lower, normalized_destination}
    for en_key, zh_alias in _CITY_ZH_ALIAS.items():
        if zh_alias.lower() == normalized_destination:
            candidates.add(en_key.lower())
    compact_text = normalized_text.replace(" ", "")
    for candidate in candidates:
        compact_destination = candidate.replace(" ", "")
        if candidate in normalized_text or compact_destination in compact_text:
            return True
    return False


def _extract_schedule_from_results(results: list[Any]) -> str | None:
    for item in results:
        combined = _search_item_text(item)
        times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", combined)
        if len(times) >= 2:
            return f"{times[0]} - {times[1]}"
        if len(times) == 1:
            return times[0]
    return None


def _extract_price_from_results(results: list[Any]) -> str | None:
    for item in results:
        combined = _search_item_text(item)
        match = re.search(r"(?:HK\$|US\$|\$|CNY\s?|RMB\s?|¥)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", combined, re.IGNORECASE)
        if match:
            symbol_match = re.search(r"(HK\$|US\$|\$|CNY\s?|RMB\s?|¥)", combined, re.IGNORECASE)
            symbol = symbol_match.group(1).strip() if symbol_match else "$"
            return f"{symbol}{match.group(1)}"
        yuan_match = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*元", combined)
        if yuan_match:
            return f"¥{yuan_match.group(1)}"
    return None


def _search_flight_options(origin: str, destination: str, date_value: datetime) -> list[FlightOption]:
    if not SERPER_TRAVEL.available():
        return []
    return SERPER_TRAVEL.search_flights(origin, destination, date_value.strftime("%Y-%m-%d"), num=3)


def _search_hotel_rates(hotel_name: str, destination: str, check_in_date: datetime) -> list[HotelRate]:
    if not SERPER_TRAVEL.available():
        return []
    return SERPER_TRAVEL.search_hotel_rates(hotel_name, destination, check_in_date.strftime("%Y-%m-%d"), num=3)


def _transport_search_destination(destination: str) -> str:
    return "乌鲁木齐" if _is_north_xinjiang_destination(destination) else destination


def _estimate_transport_unit_price_rmb(origin: str, destination: str, *, mode: str) -> float:
    origin_anchor = _resolve_destination_anchor(origin)
    destination_anchor = _resolve_destination_anchor(destination)
    distance_km = None
    if origin_anchor and destination_anchor:
        distance_km = _distance_km(origin_anchor, destination_anchor)
    normalized_mode = mode.lower()
    if normalized_mode == "flight":
        if distance_km is None:
            return 1500.0
        return float(max(700.0, min(2800.0, 380.0 + distance_km * 0.45)))
    if normalized_mode == "train":
        if distance_km is None:
            return 360.0
        return float(max(120.0, min(1300.0, 40.0 + distance_km * 0.33)))
    return 120.0


def _pick_first_price(values: list[str | None]) -> str | None:
    for value in values:
        if value and _parse_cost_amount(value) is not None:
            return value
    return None


def _set_transport_leg_cost(
    timeline_days: list[DayPlan],
    *,
    leg: str,
    cost: str | None,
    fallback_cost: str | None = None,
    label_suffix: str = "",
    travelers: int = 1,
) -> None:
    if not timeline_days:
        return
    normalized_cost = _normalize_price_to_rmb_label(cost) or fallback_cost
    if not normalized_cost:
        return
    is_approximate = str(normalized_cost).startswith("约")
    if travelers >= 1:
        amount = _parse_cost_amount(normalized_cost)
        if amount is not None:
            total = round(amount * travelers)
            unit = round(amount)
            if "车票" in label_suffix:
                normalized_cost = f"¥{total}（车票=¥{unit}×{travelers}人）"
            elif "机票" in label_suffix:
                normalized_cost = f"¥{total}（机票=¥{unit}×{travelers}人）"
            else:
                normalized_cost = f"¥{total}"
    if is_approximate and not normalized_cost.startswith("约"):
        normalized_cost = f"约{normalized_cost}"
    if label_suffix and all(token not in normalized_cost for token in ["车票", "机票", "(transport)"]):
        normalized_cost = f"{normalized_cost}{label_suffix}"
    leg = leg.lower()
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "transport":
                continue
            lowered = event.title.lower()
            if leg == "outbound" and (event.id.endswith("-arrival") or "arrival transfer" in lowered or "出发" in event.title):
                event.cost_estimate = normalized_cost
                return
            if leg == "return" and (event.id.endswith("-return") or "return transfer" in lowered or "返回" in event.title or "返程" in event.title):
                event.cost_estimate = normalized_cost
                return


def _decorate_cost_with_suffix(cost: str, suffix: str) -> str:
    cleaned = cost.strip()
    if not cleaned:
        return cleaned
    if suffix and suffix in cleaned:
        return cleaned
    return f"{cleaned}{suffix}" if suffix else cleaned


def _ensure_approximate_prefix(cost: str) -> str:
    cleaned = cost.strip()
    if not cleaned:
        return cleaned
    if cleaned.startswith("约"):
        return cleaned
    return f"约{cleaned}"


def _is_valid_reference_url(url: str) -> bool:
    lowered = url.strip().lower()
    if not lowered.startswith("http"):
        return False
    if "example.com" in lowered:
        return False
    if "xiaohongshu.com/search_result" in lowered:
        return False
    return True


def _sanitize_reference_links(links: list[ReferenceLink]) -> list[ReferenceLink]:
    sanitized: list[ReferenceLink] = []
    seen_urls: set[str] = set()
    for link in links:
        if not _is_valid_reference_url(link.url):
            continue
        if link.url in seen_urls:
            continue
        seen_urls.add(link.url)
        sanitized.append(link)
    return sanitized


def _merge_reference_links(*groups: list[ReferenceLink]) -> list[ReferenceLink]:
    merged: list[ReferenceLink] = []
    for group in groups:
        merged.extend(group)
    return _sanitize_reference_links(merged)


def _build_search_context(
    destination: str, origin: str, style: str | None
) -> tuple[str, dict[str, list], list[tuple[str, str]]]:
    """Return (context_string, amap_candidates, attraction_candidates).

    Runs Amap, Serper searches **in parallel** to cut wall-clock time.
    """
    # ---- kick off parallel tasks ------------------------------------------------
    tasks: list[tuple] = []
    task_keys: list[str] = []
    search_service = _active_search_service()

    # 0: amap candidates
    if AMAP_TRAVEL.available():
        tasks.append((AMAP_TRAVEL.fetch_candidates, (destination,)))
        task_keys.append("amap")
    # 1: search attractions
    tasks.append((_search_attraction_candidates, (destination,)))
    task_keys.append("search_attractions")
    # 2: search food (conditionally)
    want_food = _is_food_focused_style(style)
    if want_food:
        tasks.append((_search_food_candidates, (destination,)))
        task_keys.append("search_food")
    # 3: transport search
    want_transport = bool(origin and destination and origin not in {"Your city", "你的城市"})
    if want_transport and search_service:
        outbound_date, _ = _default_departure_dates(3)
        use_chinese = _should_use_chinese(destination, origin)
        transport_keyword = "flight" if _choose_transport_mode(origin, destination) == "Flight" else "train"
        if use_chinese:
            transport_query = (
                f"{origin} 到 {destination} {outbound_date.strftime('%Y-%m-%d')} "
                f"{'机票 航班 时刻' if transport_keyword == 'flight' else '高铁 动车 时刻'}"
            )
        else:
            transport_query = f"{origin} to {destination} {outbound_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
        tasks.append((search_service.search, (transport_query, 2)))
        task_keys.append("transport")

    results = parallel_call(tasks) if tasks else []
    result_map = dict(zip(task_keys, results))

    # ---- assemble context string -----------------------------------------------
    amap_candidates: dict[str, list] = result_map.get("amap", {"hotels": [], "restaurants": [], "attractions": []})
    search_attraction_results: list[tuple[str, str]] = result_map.get("search_attractions", [])

    attraction_lines: list[str] = []
    food_lines: list[str] = []

    attraction_lines.extend([f"- {poi.name} ({poi.address})" for poi in amap_candidates.get("attractions", [])[:5]])
    if want_food:
        food_lines.extend([f"- {poi.name} ({poi.address})" for poi in amap_candidates.get("restaurants", [])[:3]])

    attraction_lines.extend([f"- {name} ({address})" for name, address in search_attraction_results])
    if want_food:
        food_lines.extend([f"- {name} ({address})" for name, address in result_map.get("search_food", [])])

    if not attraction_lines:
        fallback = _fallback_attractions_for(destination)
        attraction_lines.extend([f"- {name} ({address})" for name, address in fallback[:4]])

    transport_lines: list[str] = []
    if want_transport:
        for item in result_map.get("transport", []):
            transport_lines.append(f"- {item.title}: {item.snippet}")

    sections = [
        "Grounding context from search results and map providers:",
        "Attractions:",
        *(attraction_lines or ["- None found"]),
    ]
    if food_lines:
        sections.extend(["Food:", *food_lines])
    if transport_lines:
        sections.extend(["Transport:", *transport_lines])
    return "\n".join(sections), amap_candidates, search_attraction_results


def _is_generic_scenic_event(event: TimelineEvent) -> bool:
    lowered = event.title.lower()
    if _is_generic_activity_title(event.title):
        return True
    if re.fullmatch(r"(景点|活动|打卡点)\s*\d*", event.title.strip()):
        return True
    return lowered in GENERIC_SCENIC_TITLES or any(
        token in lowered for token in ["park walk", "observation deck", "scenic stop", "landmark", "highlights"]
    )


def _apply_amap_candidates(
    destination: str,
    timeline_days: list[DayPlan],
    logistics: TravelLogistics,
    *,
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
    resolved_model: ResolvedModelConfig | None = None,
    model_client: ModelApiClient | None = None,
) -> list[ProviderWarning]:
    warnings: list[ProviderWarning] = []
    use_chinese_output = _should_use_chinese(destination)
    if not AMAP_TRAVEL.available() and prefetched_amap is None:
        return warnings

    candidates = prefetched_amap if prefetched_amap is not None else AMAP_TRAVEL.fetch_candidates(destination)

    # --- Resolve a destination anchor for POI validation ---
    destination_center = _resolve_destination_anchor(destination)
    max_radius = _destination_radius_km(destination)

    # --- Filter Amap POIs to only those near the destination ---
    hotels = [poi for poi in candidates.get("hotels", []) if _validate_amap_poi(poi, destination_center, max_radius)]
    restaurants = [poi for poi in candidates.get("restaurants", []) if _validate_amap_poi(poi, destination_center, max_radius)]
    attractions = [poi for poi in candidates.get("attractions", []) if _validate_amap_poi(poi, destination_center, max_radius)]

    fallback = _fallback_attractions_for(destination)
    search_candidates = prefetched_attractions if prefetched_attractions is not None else _search_attraction_candidates(destination)
    attraction_pool: list[tuple[str, str]] = []
    for poi in attractions:
        attraction_pool.append((poi.name, poi.address))
    for name, address in search_candidates:
        attraction_pool.append((name, address))
    if not attraction_pool:
        for name, address in fallback:
            attraction_pool.append((name, address))

    deduped_attractions: list[tuple[str, str]] = []
    seen_attractions: set[str] = set()
    for name, address in attraction_pool:
        key = name.strip().lower()
        if not key or key in seen_attractions:
            continue
        seen_attractions.add(key)
        deduped_attractions.append((name, address))

    if hotels and _is_generic_hotel_reference(logistics.hotel_name):
        logistics.hotel_name = hotels[0].name

    city_hotel_cache: dict[str, Any | None] = {}

    def _resolve_city_hotel(city_name: str) -> Any | None:
        normalized_city = _normalize_city_for_geocode(city_name).strip()
        if not normalized_city:
            return None
        if normalized_city in city_hotel_cache:
            return city_hotel_cache[normalized_city]
        if not AMAP_TRAVEL.available():
            city_hotel_cache[normalized_city] = None
            return None
        city_anchor = _resolve_destination_anchor(normalized_city)
        city_hotels = AMAP_TRAVEL.fetch_candidates(normalized_city).get("hotels", [])
        for poi in city_hotels:
            if poi.latitude is None or poi.longitude is None:
                continue
            if city_anchor is not None and _distance_km(city_anchor, (poi.longitude, poi.latitude)) > 90:
                continue
            city_hotel_cache[normalized_city] = poi
            return poi
        city_hotel_cache[normalized_city] = None
        return None

    restaurant_index = 0
    attraction_index = 0
    for day in timeline_days:
        day_city = (_day_primary_city(day, destination) or _normalize_city_for_geocode(destination)).strip()
        for event in day.events:
            kind = _classify_event(event.title)
            if kind == "food" and restaurant_index < len(restaurants):
                event.title = restaurants[restaurant_index].name
                event.location = restaurants[restaurant_index].address
                if _should_use_chinese(destination):
                    event.description = f"安排在 {restaurants[restaurant_index].name} 体验本地口碑餐饮。"
                else:
                    event.description = f"A worthwhile local food stop at {restaurants[restaurant_index].name}."
                event.latitude = restaurants[restaurant_index].latitude
                event.longitude = restaurants[restaurant_index].longitude
                restaurant_index += 1
            elif kind == "scenic":
                if _is_generic_scenic_event(event) and attraction_index < len(deduped_attractions):
                    event.title = deduped_attractions[attraction_index][0]
                    event.location = deduped_attractions[attraction_index][1]
                    event.description = (
                        f"安排游览 {event.title}，与当日路线顺序衔接。"
                        if use_chinese_output
                        else f"Visit {event.title} as a practical stop on this route."
                    )
                    if attraction_index < len(attractions):
                        event.latitude = attractions[attraction_index].latitude
                        event.longitude = attractions[attraction_index].longitude
                    attraction_index += 1
                elif attraction_index < len(deduped_attractions) and (
                    event.location.lower().endswith("landmark")
                    or any(token in event.location for token in ["地标", "推荐区域", "核心景点", "景点"])
                ):
                    event.title = deduped_attractions[attraction_index][0]
                    event.location = deduped_attractions[attraction_index][1]
                    event.description = (
                        f"安排游览 {event.title}，与当日路线顺序衔接。"
                        if use_chinese_output
                        else f"Visit {event.title} as a practical stop on this route."
                    )
                    if attraction_index < len(attractions):
                        event.latitude = attractions[attraction_index].latitude
                        event.longitude = attractions[attraction_index].longitude
                    attraction_index += 1
            elif kind == "hotel":
                city_hint = _extract_city_tag(f"{event.location} {event.title}") or day_city or logistics.destination
                city_hint = _normalize_city_for_geocode(city_hint)
                city_hotel = _resolve_city_hotel(city_hint)
                if _is_generic_hotel_reference(event.location) or event.location.strip() == logistics.hotel_name.strip():
                    suggested_name = city_hotel.name if city_hotel and city_hotel.name else None
                    if not suggested_name:
                        suggested_name = _suggest_city_hotel_with_model(
                            city=city_hint,
                            destination=destination,
                            use_chinese=use_chinese_output,
                            resolved_model=resolved_model,
                            model_client=model_client,
                        )
                    if not suggested_name:
                        suggested_name = f"{city_hint}市中心酒店" if use_chinese_output else f"{city_hint} Central Hotel"
                    event.location = suggested_name
                if event.latitude is None or event.longitude is None:
                    if city_hotel and city_hotel.latitude is not None and city_hotel.longitude is not None:
                        event.latitude = city_hotel.latitude
                        event.longitude = city_hotel.longitude
                    else:
                        poi = AMAP_TRAVEL.lookup_place(city_hint, event.location) if AMAP_TRAVEL.available() else None
                        if poi and poi.latitude is not None and poi.longitude is not None:
                            event.latitude = poi.latitude
                            event.longitude = poi.longitude
                if use_chinese_output:
                    event.description = f"在{city_hint}办理 {event.location} 入住。"
                else:
                    event.description = f"Check in at {event.location} in {city_hint}."

    first_hotel_name = next(
        (
            event.location
            for day in timeline_days
            for event in day.events
            if _classify_event(event.title) == "hotel" and event.location.strip()
        ),
        None,
    )
    if first_hotel_name:
        logistics.hotel_name = first_hotel_name

    if not hotels and not restaurants and not deduped_attractions:
        warnings.append(
            ProviderWarning(
                source="amap",
                message="Amap did not return candidate POIs for this destination, so the planner used model-only suggestions.",
                severity="low",
            )
        )
    return warnings


def _is_broad_region_hint(value: str | None) -> bool:
    if not value:
        return True
    lowered = _normalize_city_for_geocode(value).lower().strip()
    if not lowered:
        return True
    if any(token in lowered for token in _WIDE_REGION_TOKENS):
        return True
    return lowered in {"china", "中国", "mainland", "mainland china", "新疆", "北疆", "南疆"}


def _compact_match_text(value: str) -> str:
    lowered = _normalize_city_for_geocode(value).lower().strip()
    lowered = re.sub(r"^d\d+[-.、]?\d*[-.、\s]*", "", lowered)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", lowered)


def _text_overlap_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    overlap = sum(1 for char in left if char in right)
    return overlap / max(len(left), len(right), 1)


def _fallback_scenic_poi(
    event: TimelineEvent,
    city_hints: list[str],
    destination_center: tuple[float, float] | None,
    max_radius: float,
) -> Any | None:
    if not AMAP_TRAVEL.available():
        return None
    query_text = _compact_match_text(f"{event.title} {event.location}")
    generic_event = _is_generic_scenic_event(event)
    best_score = float("-inf")
    best_poi = None
    for city in city_hints:
        normalized_city = _normalize_city_for_geocode(city)
        if not normalized_city or _is_broad_region_hint(normalized_city):
            continue
        city_candidates = AMAP_TRAVEL.fetch_candidates(normalized_city).get("attractions", [])
        for poi in city_candidates[:12]:
            if poi.latitude is None or poi.longitude is None:
                continue
            if destination_center is not None and _distance_km(destination_center, (poi.longitude, poi.latitude)) > max_radius:
                continue
            poi_text = _compact_match_text(f"{poi.name} {poi.address}")
            score = _text_overlap_score(query_text, poi_text)
            if generic_event:
                score += 0.22
            if _compact_match_text(event.location) and _compact_match_text(event.location) in poi_text:
                score += 0.18
            if score > best_score:
                best_score = score
                best_poi = poi
    if best_poi is None:
        return None
    if best_score >= 0.2 or (generic_event and best_score >= 0.1):
        return best_poi
    return None


def _hydrate_event_geocodes(destination: str, timeline_days: list[DayPlan], logistics: TravelLogistics) -> None:
    if not AMAP_TRAVEL.available():
        return
    normalized_destination = _normalize_city_for_geocode(destination)
    destination_center = _resolve_destination_anchor(normalized_destination)
    max_radius = _effective_route_radius_km(normalized_destination, timeline_days, logistics)
    events_to_geocode: list[tuple[TimelineEvent, list[str], list[str]]] = []
    for day in timeline_days:
        day_city_hint = _day_primary_city(day, normalized_destination) or normalized_destination
        if _is_broad_region_hint(day_city_hint):
            day_city_hint = normalized_destination
        for event in day.events:
            if _classify_event(event.title) == "transport":
                event.latitude = None
                event.longitude = None
                continue
            if (
                destination_center is not None
                and event.latitude is not None
                and event.longitude is not None
                and _distance_km(destination_center, (event.longitude, event.latitude)) > max_radius
            ):
                logger.info(
                    "[geocode] reset out-of-region existing point destination=%s event=%s location=%s",
                    destination,
                    event.title,
                    event.location,
                )
                event.latitude = None
                event.longitude = None
            if event.latitude is not None and event.longitude is not None:
                continue
            variants: list[str] = []
            if event.location and event.location != logistics.hotel_name:
                variants.append(event.location)
            variants.append(event.title)
            deduped_variants = [value for value in dict.fromkeys(item.strip() for item in variants if item and item.strip())]
            explicit_city = _extract_city_from_text(f"{event.location} {event.title}")
            city_candidates = [
                explicit_city or "",
                day_city_hint,
                normalized_destination,
            ]
            deduped_cities: list[str] = []
            for city in city_candidates:
                normalized_city = _normalize_city_for_geocode(city)
                if not normalized_city:
                    continue
                if normalized_city in deduped_cities:
                    continue
                deduped_cities.append(normalized_city)
            if not deduped_cities:
                deduped_cities = [normalized_destination]
            events_to_geocode.append((event, deduped_cities, deduped_variants))
    if not events_to_geocode:
        return
    query_pairs = list(
        dict.fromkeys(
            (city, keyword)
            for _, cities, keywords in events_to_geocode
            for city in cities
            for keyword in keywords
        )
    )
    lookup_map: dict[tuple[str, str], Any] = {}
    if query_pairs:
        pois = parallel_map(lambda pair: AMAP_TRAVEL.lookup_place(pair[0], pair[1]), query_pairs)
        lookup_map = {pair: poi for pair, poi in zip(query_pairs, pois)}
    resolved_count = 0
    unresolved: list[str] = []
    for event, city_hints, keywords in events_to_geocode:
        matched = False
        for city in city_hints:
            for keyword in keywords:
                poi = lookup_map.get((city, keyword))
                if poi and poi.latitude is not None and poi.longitude is not None:
                    if destination_center is not None:
                        point = (poi.longitude, poi.latitude)
                        if _distance_km(destination_center, point) > max_radius:
                            logger.info(
                                "[geocode] skip out-of-region point destination=%s city=%s keyword=%s dist=%.0fkm max=%skm",
                                destination,
                                city,
                                keyword,
                                _distance_km(destination_center, point),
                                max_radius,
                            )
                            continue
                    event.latitude = poi.latitude
                    event.longitude = poi.longitude
                    if _classify_event(event.title) == "scenic" and _is_generic_scenic_event(event):
                        event.title = poi.name
                        if poi.address:
                            event.location = poi.address
                    resolved_count += 1
                    matched = True
                    break
            if matched:
                break
        if not matched and _classify_event(event.title) == "scenic":
            fallback_poi = _fallback_scenic_poi(event, city_hints, destination_center, max_radius)
            if fallback_poi and fallback_poi.latitude is not None and fallback_poi.longitude is not None:
                event.latitude = fallback_poi.latitude
                event.longitude = fallback_poi.longitude
                if _is_generic_scenic_event(event):
                    event.title = fallback_poi.name
                if not event.location or event.location in {"推荐区域", "Recommended area"}:
                    event.location = fallback_poi.address or fallback_poi.name
                resolved_count += 1
                matched = True
        if not matched and keywords:
            unresolved.append(keywords[0])
    logger.info(
        "[geocode] destination=%s resolved=%s/%s unresolved=%s",
        destination,
        resolved_count,
        len(events_to_geocode),
        unresolved[:5],
    )


def _build_day_routes(destination: str, timeline_days: list[DayPlan]) -> None:
    destination_center = _resolve_destination_anchor(destination)
    max_radius = _effective_route_radius_km(destination, timeline_days)
    day_data: list[tuple[DayPlan, list[tuple[float, float]], list[str]]] = []
    for day in timeline_days:
        ordered_points: list[tuple[float, float]] = []
        labels: list[str] = []
        for event in day.events:
            if _classify_event(event.title) != "scenic":
                continue
            if event.latitude is None or event.longitude is None:
                continue
            point = (event.longitude, event.latitude)
            if destination_center is not None and _distance_km(destination_center, point) > max_radius:
                logger.info(
                    "[route] skip out-of-region route point destination=%s event=%s location=%s",
                    destination,
                    event.title,
                    event.location,
                )
                continue
            if ordered_points and ordered_points[-1] == point:
                continue
            ordered_points.append(point)
            labels.append(event.title)
        day_data.append((day, ordered_points, labels))

    def _build_route(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return AMAP_TRAVEL.build_route_points(pts) if pts else []

    route_results = parallel_call([(_build_route, (pts,)) for _, pts, _ in day_data])

    for (day, ordered_points, labels), route_points in zip(day_data, route_results):
        if route_points:
            day.route_points = [
                RoutePoint(
                    label=labels[min(index, len(labels) - 1)],
                    latitude=point[1],
                    longitude=point[0],
                )
                for index, point in enumerate(route_points)
            ]
        else:
            day.route_points = [
                RoutePoint(label=labels[index], latitude=point[1], longitude=point[0])
                for index, point in enumerate(ordered_points)
            ]


def _reference_links(destination: str) -> list[ReferenceLink]:
    service = _active_search_service()
    safe = quote_plus(destination)
    use_chinese = _should_use_chinese(destination)
    query_plan = (
        [
            (f"{destination} 旅游攻略 行程", "攻略"),
            (f"{destination} 游记 路线", "游记"),
            (f"{destination} 旅行 论坛", "论坛"),
        ]
        if use_chinese
        else [
            (f"{destination} travel blog itinerary", "Travel blog"),
            (f"{destination} trip report 3 day itinerary", "Trip report"),
            (f"site:reddit.com/r/travel {destination} itinerary", "Traveler forum"),
        ]
    )
    links: list[ReferenceLink] = []
    if service:
        search_results = parallel_call([(service.search, (query, 2)) for query, _ in query_plan])
        for (_, label), results in zip(query_plan, search_results):
            for item in results:
                links.append(ReferenceLink(title=item.title, url=item.link, label=label))
        links = _sanitize_reference_links(links)
        if links:
            return links[:6]
    return [
        ReferenceLink(
            title=f"{destination} travel blog search" if not use_chinese else f"{destination} 旅游攻略搜索",
            url=f"https://www.google.com/search?q={safe}+travel+blog+itinerary" if not use_chinese else f"https://www.google.com/search?q={safe}+旅游+攻略+行程",
            label="Travel blog" if not use_chinese else "攻略",
        ),
        ReferenceLink(
            title=f"{destination} trip report search" if not use_chinese else f"{destination} 游记搜索",
            url=f"https://www.google.com/search?q={safe}+trip+report+itinerary" if not use_chinese else f"https://www.google.com/search?q={safe}+游记+路线",
            label="Trip report" if not use_chinese else "游记",
        ),
        ReferenceLink(
            title=f"{destination} traveler forum search" if not use_chinese else f"{destination} 旅行论坛搜索",
            url=f"https://www.google.com/search?q={safe}+reddit+travel+itinerary" if not use_chinese else f"https://www.google.com/search?q={safe}+旅行+论坛",
            label="Traveler forum" if not use_chinese else "论坛",
        ),
    ]


def _apply_live_search(
    logistics: TravelLogistics,
    timeline_days: list[DayPlan],
    *,
    resolved_model: ResolvedModelConfig | None = None,
    model_client: ModelApiClient | None = None,
) -> tuple[list[ReferenceLink], list[ProviderWarning]]:
    warnings: list[ProviderWarning] = []
    references: list[ReferenceLink] = []
    duration_days = max(len(timeline_days), 1)
    travelers = max(int(logistics.travelers or 1), 1)
    use_chinese = _should_use_chinese(logistics.destination, logistics.origin)
    transport_search_destination = _transport_search_destination(logistics.destination)
    outbound_lower = logistics.outbound_transport.lower()
    transport_keyword = "flight" if ("flight" in outbound_lower or any(token in logistics.outbound_transport for token in ["航班", "飞机"])) else "train"
    transport_label_suffix = "（机票）" if (use_chinese and transport_keyword == "flight") else ("（车票）" if use_chinese else " (transport)")
    schedule_service = _active_search_service()
    food_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "food"]
    day_city_by_index = {
        day.day_index: (_day_primary_city(day, logistics.destination) or _normalize_city_for_geocode(logistics.destination)).strip()
        for day in timeline_days
    }
    city_hotel_by_city: dict[str, str] = {}
    for day in timeline_days:
        day_city = day_city_by_index.get(day.day_index, _normalize_city_for_geocode(logistics.destination))
        for event in day.events:
            if _classify_event(event.title) != "hotel":
                continue
            hotel_name = str(event.location or "").strip()
            if not hotel_name:
                continue
            city_hint = _normalize_city_for_geocode(_extract_city_tag(f"{hotel_name} {day_city}") or day_city)
            if city_hint not in city_hotel_by_city:
                city_hotel_by_city[city_hint] = hotel_name
    if not city_hotel_by_city:
        city_hotel_by_city[_normalize_city_for_geocode(logistics.destination)] = logistics.hotel_name

    if not schedule_service and not SERPER_TRAVEL.available():
        estimated_unit = _estimate_transport_unit_price_rmb(
            logistics.origin,
            transport_search_destination,
            mode="flight" if transport_keyword == "flight" else "train",
        )
        fallback_transport_cost = f"约¥{round(estimated_unit)}"
        _set_transport_leg_cost(
            timeline_days,
            leg="outbound",
            cost=None,
            fallback_cost=fallback_transport_cost,
            label_suffix=transport_label_suffix,
            travelers=travelers,
        )
        _set_transport_leg_cost(
            timeline_days,
            leg="return",
            cost=None,
            fallback_cost=fallback_transport_cost,
            label_suffix=transport_label_suffix,
            travelers=travelers,
        )
        nightly_by_city: dict[str, tuple[float, bool]] = {}
        for city, hotel_name in city_hotel_by_city.items():
            guessed = _estimate_hotel_nightly_with_model(
                city=city,
                hotel_name=hotel_name,
                use_chinese=use_chinese,
                resolved_model=resolved_model,
                model_client=model_client,
            )
            if guessed is not None:
                nightly_by_city[city] = (guessed, True)
            else:
                nightly_by_city[city] = (420.0, True)
        stay_lengths = _city_stay_lengths_by_day(timeline_days, logistics.destination)
        for day in timeline_days:
            stay_days = max(stay_lengths.get(day.day_index, 1), 1)
            day_city = day_city_by_index.get(day.day_index, _normalize_city_for_geocode(logistics.destination))
            nightly_amount, is_estimated = nightly_by_city.get(day_city, (420.0, True))
            hotel_total_label = _format_currency(nightly_amount * stay_days)
            if is_estimated:
                hotel_total_label = _ensure_approximate_prefix(hotel_total_label)
            if use_chinese:
                hotel_total_amount = f"{hotel_total_label}（房费=¥{round(nightly_amount)}×{stay_days}天）"
            else:
                hotel_total_amount = _decorate_cost_with_suffix(hotel_total_label, " (room)")
            for event in day.events:
                kind = _classify_event(event.title)
                if kind == "hotel":
                    event.cost_estimate = hotel_total_amount
        return references, warnings

    outbound_date, return_date = _default_departure_dates(duration_days)
    transport_site = "google.com/travel/flights" if transport_keyword == "flight" else "12306"
    if use_chinese:
        outbound_query = (
            f"site:{transport_site} {logistics.origin} 到 {transport_search_destination} "
            f"{outbound_date.strftime('%Y-%m-%d')} {'机票 航班 起飞 到达' if transport_keyword == 'flight' else '高铁 动车 出发 到达'}"
        )
        return_query = (
            f"site:{transport_site} {transport_search_destination} 到 {logistics.origin} "
            f"{return_date.strftime('%Y-%m-%d')} {'机票 航班 起飞 到达' if transport_keyword == 'flight' else '高铁 动车 出发 到达'}"
        )
    else:
        outbound_query = (
            f"site:{transport_site} {logistics.origin} to {transport_search_destination} "
            f"{outbound_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
        )
        return_query = (
            f"site:{transport_site} {transport_search_destination} to {logistics.origin} "
            f"{return_date.strftime('%Y-%m-%d')} {transport_keyword} departure arrival time"
        )
    task_defs: list[tuple[str, Any, tuple[Any, ...]]] = []
    hotel_task_meta: list[tuple[str, str, str, str]] = []
    if schedule_service:
        task_defs.extend(
            [
                ("outbound_results", schedule_service.search, (outbound_query, 2)),
                ("return_results", schedule_service.search, (return_query, 2)),
            ]
        )
        for idx, (city, hotel_name) in enumerate(city_hotel_by_city.items()):
            hotel_key = f"hotel_results_{idx}"
            rate_key = f"hotel_rates_{idx}"
            hotel_query = (
                f"{hotel_name} {city} 酒店 每晚 价格 预订 评价"
                if use_chinese
                else f"{hotel_name} {city} hotel nightly price booking reviews"
            )
            task_defs.append((hotel_key, schedule_service.search, (hotel_query, 2)))
            task_defs.append((rate_key, _search_hotel_rates, (hotel_name, city, outbound_date)))
            hotel_task_meta.append((hotel_key, rate_key, city, hotel_name))

    if schedule_service and transport_keyword != "flight":
        task_defs.extend(
            [
                (
                    "alternate_flight_outbound",
                    schedule_service.search,
                    (
                        (
                            f"site:google.com/travel/flights {logistics.origin} 到 {transport_search_destination} "
                            f"{outbound_date.strftime('%Y-%m-%d')} 航班 起飞 到达"
                            if use_chinese
                            else f"site:google.com/travel/flights {logistics.origin} to {transport_search_destination} "
                            f"{outbound_date.strftime('%Y-%m-%d')} flight departure arrival time"
                        ),
                        1,
                    ),
                ),
                (
                    "alternate_flight_return",
                    schedule_service.search,
                    (
                        (
                            f"site:google.com/travel/flights {transport_search_destination} 到 {logistics.origin} "
                            f"{return_date.strftime('%Y-%m-%d')} 航班 起飞 到达"
                            if use_chinese
                            else f"site:google.com/travel/flights {transport_search_destination} to {logistics.origin} "
                            f"{return_date.strftime('%Y-%m-%d')} flight departure arrival time"
                        ),
                        1,
                    ),
                ),
            ]
        )

    # Dedicated Serper functions for flights (origin, destination, date based).
    task_defs.extend(
        [
            ("flight_options_outbound", _search_flight_options, (logistics.origin, transport_search_destination, outbound_date)),
            ("flight_options_return", _search_flight_options, (transport_search_destination, logistics.origin, return_date)),
        ]
    )

    for event in food_events:
        if schedule_service:
            food_query = (
                f"{event.title} {event.location} 菜单 评价 人均"
                if use_chinese
                else f"{event.title} {event.location} menu reviews"
            )
            task_defs.append((f"food_{event.id}", schedule_service.search, (food_query, 2)))

    task_results = parallel_call([(fn, args) for _, fn, args in task_defs]) if task_defs else []
    result_map: dict[str, Any] = {key: value for (key, _, _), value in zip(task_defs, task_results)}

    outbound_results = result_map.get("outbound_results", [])
    return_results = result_map.get("return_results", [])
    outbound_options: list[FlightOption] = result_map.get("flight_options_outbound", [])
    return_options: list[FlightOption] = result_map.get("flight_options_return", [])

    outbound_schedule = _extract_schedule_from_results(outbound_results) or next(
        (option.schedule for option in outbound_options if option.schedule), None
    )
    return_schedule = _extract_schedule_from_results(return_results) or next(
        (option.schedule for option in return_options if option.schedule), None
    )
    if outbound_schedule:
        logistics.outbound_schedule = _format_schedule_range(outbound_date, outbound_schedule, approximate=False, use_chinese=use_chinese)
    if return_schedule:
        logistics.return_schedule = _format_schedule_range(return_date, return_schedule, approximate=False, use_chinese=use_chinese)

    if use_chinese:
        outbound_label = "去程航班" if transport_keyword == "flight" else "去程铁路"
        return_label = "返程航班" if transport_keyword == "flight" else "返程铁路"
    else:
        outbound_label = "Flight search" if transport_keyword == "flight" else "Rail search"
        return_label = "Return flight" if transport_keyword == "flight" else "Return rail"
    for item in outbound_results[:1]:
        references.append(ReferenceLink(title=item.title, url=item.link, label=outbound_label))
    for item in return_results[:1]:
        references.append(ReferenceLink(title=item.title, url=item.link, label=return_label))
    for option in outbound_options[:1]:
        references.append(ReferenceLink(title=option.title, url=option.link, label="航班选项" if use_chinese else "Flight option"))
    for option in return_options[:1]:
        references.append(ReferenceLink(title=option.title, url=option.link, label="返程航班选项" if use_chinese else "Return flight option"))

    if transport_keyword != "flight":
        flight_results = result_map.get("alternate_flight_outbound", [])
        flight_return_results = result_map.get("alternate_flight_return", [])
        for item in flight_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="备选航班" if use_chinese else "Alternate flights"))
        for item in flight_return_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="返程航班" if use_chinese else "Return flights"))

    outbound_price_raw = _extract_price_from_results(outbound_results) or _pick_first_price([option.price for option in outbound_options])
    return_price_raw = _extract_price_from_results(return_results) or _pick_first_price([option.price for option in return_options])
    outbound_price = _normalize_price_to_rmb_label(outbound_price_raw)
    return_price = _normalize_price_to_rmb_label(return_price_raw)
    estimated_unit = _estimate_transport_unit_price_rmb(
        logistics.origin,
        transport_search_destination,
        mode="flight" if transport_keyword == "flight" else "train",
    )
    fallback_transport_cost = f"约¥{round(estimated_unit)}"

    _set_transport_leg_cost(
        timeline_days,
        leg="outbound",
        cost=outbound_price,
        fallback_cost=fallback_transport_cost,
        label_suffix=transport_label_suffix,
        travelers=travelers,
    )
    _set_transport_leg_cost(
        timeline_days,
        leg="return",
        cost=return_price,
        fallback_cost=fallback_transport_cost,
        label_suffix=transport_label_suffix,
        travelers=travelers,
    )

    nightly_by_city: dict[str, tuple[float, bool]] = {}
    if hotel_task_meta:
        for hotel_key, rate_key, city, hotel_name in hotel_task_meta:
            hotel_results = result_map.get(hotel_key, [])
            hotel_rates: list[HotelRate] = result_map.get(rate_key, [])
            hotel_price_raw = _extract_price_from_results(hotel_results) or _pick_first_price([rate.nightly_price for rate in hotel_rates])
            hotel_nightly_amount = _parse_cost_amount(hotel_price_raw)
            is_estimated = False
            if hotel_nightly_amount is None:
                guessed = _estimate_hotel_nightly_with_model(
                    city=city,
                    hotel_name=hotel_name,
                    use_chinese=use_chinese,
                    resolved_model=resolved_model,
                    model_client=model_client,
                )
                if guessed is not None:
                    hotel_nightly_amount = guessed
                    is_estimated = True
            if hotel_nightly_amount is None:
                hotel_nightly_amount = 420.0
                is_estimated = True
            nightly_by_city[city] = (hotel_nightly_amount, is_estimated)
            for item in hotel_results[:1]:
                references.append(ReferenceLink(title=item.title, url=item.link, label="酒店搜索" if use_chinese else "Hotel search"))
            for rate in hotel_rates[:1]:
                references.append(ReferenceLink(title=rate.title, url=rate.link, label="酒店价格" if use_chinese else "Hotel rate"))
    else:
        for city, hotel_name in city_hotel_by_city.items():
            guessed = _estimate_hotel_nightly_with_model(
                city=city,
                hotel_name=hotel_name,
                use_chinese=use_chinese,
                resolved_model=resolved_model,
                model_client=model_client,
            )
            if guessed is not None:
                nightly_by_city[city] = (guessed, True)
            else:
                nightly_by_city[city] = (420.0, True)

    stay_lengths = _city_stay_lengths_by_day(timeline_days, logistics.destination)
    for day in timeline_days:
        stay_days = max(stay_lengths.get(day.day_index, 1), 1)
        day_city = day_city_by_index.get(day.day_index, _normalize_city_for_geocode(logistics.destination))
        nightly_amount, is_estimated = nightly_by_city.get(day_city, (420.0, True))
        total_hotel_amount = _format_currency(nightly_amount * stay_days, "¥")
        if is_estimated:
            total_hotel_amount = _ensure_approximate_prefix(total_hotel_amount)
        if use_chinese:
            total_hotel_amount = f"{total_hotel_amount}（房费=¥{round(nightly_amount)}×{stay_days}天）"
        else:
            total_hotel_amount = _decorate_cost_with_suffix(total_hotel_amount, " (room)")
        for event in day.events:
            if _classify_event(event.title) == "hotel":
                event.cost_estimate = total_hotel_amount

    for event in food_events:
        food_results = result_map.get(f"food_{event.id}", [])
        price_raw = _extract_price_from_results(food_results)
        price = _normalize_price_to_rmb_label(price_raw)
        if price:
            event.cost_estimate = price
        elif not event.cost_estimate:
            event.cost_estimate = "约¥90"
        for item in food_results[:1]:
            references.append(ReferenceLink(title=item.title, url=item.link, label="餐厅评价" if use_chinese else "Food reviews"))

    return _sanitize_reference_links(references), warnings


def _ensure_cost_estimates(timeline_days: list[DayPlan]) -> None:
    def _default_cost_label(event: TimelineEvent) -> str | None:
        kind = _classify_event(event.title)
        if kind == "hotel":
            return "约¥420"
        if kind == "food":
            return "约¥90"
        if kind == "scenic":
            return None
        if kind == "transport":
            return None
        return "约¥60"

    for day in timeline_days:
        for event in day.events:
            raw_cost = str(event.cost_estimate or "")
            normalized = _normalize_price_to_rmb_label(event.cost_estimate)
            if normalized:
                if any(token in raw_cost.lower() for token in ["approx", "estimated"]) or any(token in raw_cost for token in ["约", "预估"]):
                    event.cost_estimate = f"约{normalized}"
                else:
                    event.cost_estimate = normalized
                continue
            event.cost_estimate = _default_cost_label(event)


def _assign_food_images(timeline_days: list[DayPlan]) -> None:
    food_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "food"]
    for index, event in enumerate(food_events):
        if not event.image_url:
            event.image_url = FOOD_IMAGE_POOL[index % len(FOOD_IMAGE_POOL)]


def _assign_scenic_images(destination: str, timeline_days: list[DayPlan]) -> None:
    # Scenic images should come from live lookup/search, not static cache pools.
    return


def _backfill_missing_scenic_images_with_serper(
    destination: str,
    timeline_days: list[DayPlan],
    references: list[VisualReference],
) -> list[VisualReference]:
    if not SERPER_TRAVEL.available():
        return references
    existing_urls: set[str] = {
        ref.image_url for ref in references if ref.image_url
    }
    use_chinese = _should_use_chinese(destination)
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "scenic" or event.image_url:
                continue
            queries: list[str] = []
            if use_chinese:
                queries.append(f"{event.title} {destination} 景区 实拍")
                if event.location and event.location != destination:
                    queries.append(f"{event.location} {destination} 景点 实拍")
            else:
                queries.append(f"{event.title} {destination} landmark photo")
                if event.location and event.location != destination:
                    queries.append(f"{event.location} {destination} attraction")

            for query in queries:
                try:
                    items = SERPER_TRAVEL.search_images_live(query, num=4)
                except Exception as exc:
                    logger.warning("[serper] live scenic image search failed event=%s query=%s err=%s", event.title, query, exc)
                    continue
                chosen = next(
                    (
                        item
                        for item in items
                        if item.image_url and item.source_url and _is_valid_reference_url(item.source_url)
                    ),
                    None,
                )
                if not chosen:
                    continue
                event.image_url = chosen.image_url
                if chosen.image_url not in existing_urls:
                    existing_urls.add(chosen.image_url)
                    references.append(
                        VisualReference(title=event.title, image_url=chosen.image_url, source_url=chosen.source_url)
                    )
                break
    return references


def _image_match_score(event: TimelineEvent, destination: str, title: str, source_url: str | None) -> int:
    source = f"{title} {source_url or ''}".lower()
    score = 0
    lowered_title = event.title.lower().strip()
    lowered_location = event.location.lower().strip()
    lowered_destination = destination.lower().strip()
    if lowered_title and lowered_title in source:
        score += 12
    if lowered_location and lowered_location in source:
        score += 4
    if lowered_destination and lowered_destination in source:
        score += 2
    zh_tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", f"{event.title} {event.location}")
    en_tokens = [
        token.lower()
        for token in re.split(r"[\s,/()_-]+", f"{event.title} {event.location}")
        if len(token) >= 3
    ]
    for token in zh_tokens + en_tokens:
        if token in source:
            score += 3
    return score


def _scenic_image_cache_key(destination: str, event: TimelineEvent) -> str:
    return "|".join(
        [
            _normalize_city_for_geocode(destination).lower().strip(),
            event.title.strip().lower(),
        ]
    )


def _get_cached_scenic_payload(destination: str, event: TimelineEvent) -> dict[str, Any] | None:
    cache_key = _scenic_image_cache_key(destination, event)
    payload = get_cached_json("scenic.image", cache_key, max_age_seconds=SCENIC_IMAGE_CACHE_TTL_SECONDS)
    return payload if isinstance(payload, dict) else None


def _get_cached_scenic_image(destination: str, event: TimelineEvent) -> VisualReference | None:
    payload = _get_cached_scenic_payload(destination, event)
    if not payload or str(payload.get("status") or "").lower() == "miss":
        return None
    image_url = str(payload.get("image_url") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    title = str(payload.get("title") or event.title).strip() or event.title
    if not image_url or not source_url or not _is_valid_reference_url(source_url):
        return None
    return VisualReference(title=title, image_url=image_url, source_url=source_url)


def _set_cached_scenic_image(destination: str, event: TimelineEvent, reference: VisualReference) -> None:
    if not reference.image_url or not reference.source_url:
        return
    cache_key = _scenic_image_cache_key(destination, event)
    set_cached_json(
        "scenic.image",
        cache_key,
        {
            "title": reference.title,
            "image_url": reference.image_url,
            "source_url": reference.source_url,
        },
    )


def _set_cached_scenic_miss(destination: str, event: TimelineEvent) -> None:
    cache_key = _scenic_image_cache_key(destination, event)
    set_cached_json("scenic.image", cache_key, {"status": "miss"})


def _scenic_image_query(destination: str, event: TimelineEvent, *, use_chinese: bool) -> str:
    if use_chinese:
        if "颐和园" in event.title:
            return "颐和园 北京 景区 实拍"
        if "故宫" in event.title:
            return "故宫博物院 北京 景区 实拍"
        return f"{event.title} {destination} 景区 实拍"
    return f"{event.title} {destination} landmark photo"


def _replace_scenic_images_with_serper_live(
    destination: str,
    timeline_days: list[DayPlan],
    references: list[VisualReference],
) -> list[VisualReference]:
    if not SERPER_TRAVEL.available():
        return references
    deduped_references: list[VisualReference] = []
    seen_urls: set[str] = set()
    use_chinese = _should_use_chinese(destination)
    query_results_cache: dict[tuple[str, str], list[Any]] = {}
    event_choice_cache: dict[str, Any | None] = {}
    scenic_events = [event for day in timeline_days for event in day.events if _classify_event(event.title) == "scenic"]
    for event in scenic_events:
        fallback_image = _scenic_image_for(f"{destination}-{event.title}-{event.location}")
        cached_payload = _get_cached_scenic_payload(destination, event)
        if cached_payload and str(cached_payload.get("status") or "").lower() == "miss":
            event.image_url = event.image_url or fallback_image
            continue
        cached_reference = _get_cached_scenic_image(destination, event)
        if cached_reference:
            event.image_url = cached_reference.image_url
            if cached_reference.image_url not in seen_urls:
                seen_urls.add(cached_reference.image_url)
                deduped_references.append(cached_reference)
            continue

        # If the event already has an image in memory, keep it and skip API calls.
        if event.image_url:
            continue

        event_key = f"{event.title}|{event.location}"
        if event_key in event_choice_cache:
            chosen_cached = event_choice_cache[event_key]
            if chosen_cached is None:
                event.image_url = event.image_url or fallback_image
                continue
            event.image_url = chosen_cached.image_url
            if chosen_cached.image_url not in seen_urls:
                seen_urls.add(chosen_cached.image_url)
                deduped_references.append(
                    VisualReference(title=event.title, image_url=chosen_cached.image_url, source_url=chosen_cached.source_url)
                )
            continue

        query = _scenic_image_query(destination, event, use_chinese=use_chinese)
        best_item = None
        best_score = -1
        items = query_results_cache.get(("cached", query))
        if items is None:
            items = SERPER_TRAVEL.search_images_cached_only(query, num=8)
            query_results_cache[("cached", query)] = items
        if not items:
            items = query_results_cache.get(("live", query))
            if items is None:
                try:
                    items = SERPER_TRAVEL.search_images_live(query, num=8)
                except Exception as exc:
                    logger.warning("[serper] live image replace failed event=%s query=%s err=%s", event.title, query, exc)
                    items = []
                query_results_cache[("live", query)] = items
        for item in items:
            if not item.image_url or not item.source_url or not _is_valid_reference_url(item.source_url):
                continue
            score = _image_match_score(event, destination, item.title, item.source_url)
            if score > best_score:
                best_score = score
                best_item = item

        # Require a minimum relevance to avoid mismatched attractions.
        if best_item and best_score >= 6:
            event_choice_cache[event_key] = best_item
            event.image_url = best_item.image_url
            reference = VisualReference(title=event.title, image_url=best_item.image_url, source_url=best_item.source_url)
            _set_cached_scenic_image(destination, event, reference)
            if best_item.image_url not in seen_urls:
                seen_urls.add(best_item.image_url)
                deduped_references.append(reference)
        else:
            event_choice_cache[event_key] = None
            event.image_url = event.image_url or fallback_image
            _set_cached_scenic_miss(destination, event)
    return deduped_references


def _extract_city_tag(value: str) -> str | None:
    candidate = _extract_city_from_text(value)
    if candidate:
        return candidate
    zh_match = re.search(r"([\u4e00-\u9fff]{2,8}(?:市|县|区|州|盟))", value)
    if zh_match:
        return zh_match.group(1)
    en_match = re.search(r"\b([A-Za-z][A-Za-z\s]{2,24})\b", value)
    if en_match:
        token = en_match.group(1).strip()
        lowered = token.lower()
        if lowered not in {"road", "street", "district", "scenic", "park"}:
            return token
    return None


def _day_primary_city(day: DayPlan, destination: str) -> str | None:
    for event in sorted(day.events, key=lambda item: _sort_key(item.start_time)):
        if _classify_event(event.title) == "transport":
            continue
        hint = _extract_city_tag(f"{event.location} {event.title}")
        if hint:
            return _normalize_city_for_geocode(hint)
    return _normalize_city_for_geocode(destination)


def _choose_leg_mode(
    previous_event: TimelineEvent,
    current_event: TimelineEvent,
) -> str:
    if (
        previous_event.latitude is None
        or previous_event.longitude is None
        or current_event.latitude is None
        or current_event.longitude is None
    ):
        return "drive"
    distance = _distance_km(
        (previous_event.longitude, previous_event.latitude),
        (current_event.longitude, current_event.latitude),
    )
    combined_text = f"{previous_event.title} {previous_event.location} {current_event.title} {current_event.location}".lower()
    if any(token in combined_text for token in ["机场", "airport", "航站楼"]) and distance > 120:
        return "flight"
    if any(token in combined_text for token in ["高铁", "火车", "train", "rail"]) and distance > 80:
        return "rail"
    previous_city = _extract_city_tag(f"{previous_event.location} {previous_event.title}") or ""
    current_city = _extract_city_tag(f"{current_event.location} {current_event.title}") or ""
    city_changed = bool(previous_city and current_city and previous_city != current_city)
    if city_changed and distance > 900:
        return "flight"
    if distance <= 1.2:
        return "walk"
    if distance <= 12:
        return "transit"
    if distance <= 220:
        return "drive"
    if city_changed:
        return "drive"
    return "drive"


def _annotate_route_travel_times(destination: str, timeline_days: list[DayPlan]) -> None:
    if not timeline_days:
        return
    use_chinese = _should_use_chinese(destination)
    for day in timeline_days:
        ordered_events = sorted(day.events, key=lambda item: _sort_key(item.start_time))
        previous_visit: TimelineEvent | None = None
        for event in ordered_events:
            if _classify_event(event.title) == "transport":
                continue
            if previous_visit is None:
                event.travel_time_from_previous = "-"
                previous_visit = event
                continue
            if (
                previous_visit.latitude is not None
                and previous_visit.longitude is not None
                and event.latitude is not None
                and event.longitude is not None
            ):
                straight_km = _distance_km(
                    (previous_visit.longitude, previous_visit.latitude),
                    (event.longitude, event.latitude),
                )
                if straight_km >= 350:
                    if use_chinese:
                        event.travel_time_from_previous = "跨城交通：建议拆分行程或改为航班/高铁"
                    else:
                        event.travel_time_from_previous = "Cross-city transfer: split this leg or use flight/rail"
                    previous_visit = event
                    continue
                preferred_mode = _choose_leg_mode(previous_visit, event)
                mode_label_zh, minutes, route_detail = AMAP_TRAVEL.estimate_travel_leg(
                    (previous_visit.longitude, previous_visit.latitude),
                    (event.longitude, event.latitude),
                    preferred_mode=preferred_mode,
                    city=_extract_city_tag(event.location) or destination,
                )
                if use_chinese:
                    suffix = f"（{route_detail}）" if route_detail else ""
                    event.travel_time_from_previous = f"{mode_label_zh}：{minutes}分钟{suffix}"
                else:
                    mode_label_en = {
                        "步行": "Walk",
                        "驾车": "Drive",
                        "公共交通": "Transit",
                        "高铁": "Rail",
                        "航班": "Flight",
                    }.get(mode_label_zh, "Transit")
                    suffix = f" ({route_detail})" if route_detail else ""
                    event.travel_time_from_previous = f"{mode_label_en}: {minutes} min{suffix}"
            elif not event.travel_time_from_previous or event.travel_time_from_previous in {"15 min", "15 分钟", "approximate", "预估"}:
                event.travel_time_from_previous = "交通：约30分钟" if use_chinese else "Transit: ~30 min"
            previous_visit = event


def _is_rail_transport_mode(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ["rail", "train", "high-speed"]) or any(token in str(text or "") for token in ["高铁", "动车", "火车"])


def _station_label(city: str, *, use_chinese: bool) -> str:
    normalized = _normalize_city_for_geocode(city).strip()
    if not normalized:
        return "目的地站" if use_chinese else "Destination Station"
    if use_chinese:
        if normalized.endswith("站") or normalized.endswith("机场"):
            return normalized
        return f"{normalized}站"
    lowered = normalized.lower()
    if "station" in lowered or "airport" in lowered:
        return normalized
    return f"{normalized} Station"


def _inject_logistics_events(timeline_days: list[DayPlan], logistics: TravelLogistics) -> None:
    if not timeline_days:
        return
    first_day = timeline_days[0]
    last_day = timeline_days[-1]
    use_chinese = _should_use_chinese(logistics.destination, logistics.origin)
    first_day_has_transport = any(_classify_event(event.title) == "transport" for event in first_day.events)
    last_day_has_transport = any(_classify_event(event.title) == "transport" for event in last_day.events)
    rail_outbound = _is_rail_transport_mode(logistics.outbound_transport)
    rail_return = _is_rail_transport_mode(logistics.return_transport) or rail_outbound
    origin_station = _station_label(logistics.origin, use_chinese=use_chinese)
    destination_station = _station_label(logistics.destination, use_chinese=use_chinese)

    if not first_day_has_transport:
        if rail_outbound:
            first_day.events.append(
                TimelineEvent(
                    id=f"d{first_day.day_index + 1}-arrival",
                    start_time="07:00",
                    end_time="09:30",
                    title=f"{origin_station}至{destination_station}" if use_chinese else f"{origin_station} to {destination_station}",
                    location=origin_station,
                    travel_time_from_previous="-",
                    cost_estimate=None,
                    description=(
                        f"搭乘高铁从{origin_station}前往{destination_station}。"
                        if use_chinese
                        else f"Take high-speed rail from {origin_station} to {destination_station}."
                    ),
                    image_url=None,
                    risk_flags=[],
                )
            )
        else:
            first_day.events.append(
                TimelineEvent(
                    id=f"d{first_day.day_index + 1}-arrival",
                    start_time="07:00",
                    end_time="08:30",
                    title="去程交通" if use_chinese else "Outbound Transport",
                    location=f"{logistics.origin} 至 {logistics.destination}" if use_chinese else f"{logistics.origin} to {logistics.destination}",
                    travel_time_from_previous="-",
                    cost_estimate=None,
                    description=(
                        f"先完成主交通段：{logistics.outbound_transport}。"
                        if use_chinese
                        else f"Take the main inbound leg via {logistics.outbound_transport}."
                    ),
                    image_url=None,
                    risk_flags=[],
                )
            )
    if not any(
        "hotel" in event.title.lower()
        or "check-in" in event.title.lower()
        or any(token in event.title for token in ["酒店", "入住"])
        for event in first_day.events
    ):
        first_day.events.append(
            TimelineEvent(
                id=f"d{first_day.day_index + 1}-hotel",
                start_time="15:00",
                end_time="15:45",
                title="酒店入住" if use_chinese else "Hotel Check-in",
                location=logistics.hotel_name,
                travel_time_from_previous="15 分钟" if use_chinese else "15 min",
                cost_estimate=None,
                description=(
                    f"办理 {logistics.hotel_name} 入住，短暂休整后继续行程。"
                    if use_chinese
                    else f"Check in at {logistics.hotel_name} and reset before the next stop."
                ),
                image_url=None,
                risk_flags=[],
            )
        )
    if not last_day_has_transport:
        if rail_return:
            last_day.events.append(
                TimelineEvent(
                    id=f"d{last_day.day_index + 1}-return",
                    start_time="17:30",
                    end_time="20:20",
                    title=f"{destination_station}至{origin_station}" if use_chinese else f"{destination_station} to {origin_station}",
                    location=destination_station,
                    travel_time_from_previous="45 分钟" if use_chinese else "45 min",
                    cost_estimate=None,
                    description=(
                        f"搭乘高铁从{destination_station}返回{origin_station}。"
                        if use_chinese
                        else f"Return by high-speed rail from {destination_station} to {origin_station}."
                    ),
                    image_url=None,
                    risk_flags=[],
                )
            )
        else:
            last_day.events.append(
                TimelineEvent(
                    id=f"d{last_day.day_index + 1}-return",
                    start_time="19:00",
                    end_time="21:00",
                    title="返程交通" if use_chinese else "Return Transport",
                    location=f"{logistics.destination} 至 {logistics.origin}" if use_chinese else f"{logistics.destination} to {logistics.origin}",
                    travel_time_from_previous="25 分钟" if use_chinese else "25 min",
                    cost_estimate=None,
                    description=(
                        f"通过 {logistics.return_transport} 完成返程，结束本次行程。"
                        if use_chinese
                        else f"Wrap the trip with the outbound leg home via {logistics.return_transport}."
                    ),
                    image_url=None,
                    risk_flags=[],
                )
            )

    for day in timeline_days:
        day.events.sort(key=lambda event: _sort_key(event.start_time))


def _dedupe_terminal_transport_events(timeline_days: list[DayPlan], logistics: TravelLogistics | None = None) -> None:
    if not timeline_days:
        return

    generic_titles = {"到达接驳", "arrival transfer", "返程接驳", "return transfer", "去程交通", "outbound transport", "返程交通", "return transport"}

    def _pick_canonical(events: list[TimelineEvent], *, prefer_arrival: bool) -> TimelineEvent | None:
        if not events:
            return None
        concrete = [event for event in events if event.title.strip().lower() not in generic_titles]
        if concrete:
            return sorted(concrete, key=lambda item: _sort_key(item.start_time))[0]
        for event in events:
            lowered = event.title.lower()
            if prefer_arrival and ("arrival transfer" in lowered or any(token in event.title for token in ["到达", "抵达", "接驳", "出发", "去程"])):
                return event
            if (not prefer_arrival) and ("return transfer" in lowered or any(token in event.title for token in ["返程", "返回", "离开"])):
                return event
        return sorted(events, key=lambda item: _sort_key(item.start_time))[0]

    first_day = timeline_days[0]
    last_day = timeline_days[-1]
    first_transports = [event for event in first_day.events if _classify_event(event.title) == "transport"]
    last_transports = [event for event in last_day.events if _classify_event(event.title) == "transport"]

    keep_first = _pick_canonical(first_transports, prefer_arrival=True)
    keep_last = _pick_canonical(last_transports, prefer_arrival=False)

    if len(first_transports) > 1 and keep_first:
        first_day.events = [event for event in first_day.events if _classify_event(event.title) != "transport" or event.id == keep_first.id]
    if len(last_transports) > 1 and keep_last:
        last_day.events = [event for event in last_day.events if _classify_event(event.title) != "transport" or event.id == keep_last.id]

    if keep_first and keep_first.id != f"d{first_day.day_index + 1}-arrival":
        keep_first.id = f"d{first_day.day_index + 1}-arrival"
    if keep_last and keep_last.id != f"d{last_day.day_index + 1}-return":
        keep_last.id = f"d{last_day.day_index + 1}-return"

    if logistics is not None:
        use_chinese = _should_use_chinese(logistics.destination, logistics.origin)
        origin_station = _station_label(logistics.origin, use_chinese=use_chinese)
        destination_station = _station_label(logistics.destination, use_chinese=use_chinese)
        if keep_first and keep_first.title.strip().lower() in generic_titles and _is_rail_transport_mode(logistics.outbound_transport):
            keep_first.title = f"{origin_station}至{destination_station}" if use_chinese else f"{origin_station} to {destination_station}"
            keep_first.location = origin_station
            keep_first.description = (
                f"搭乘高铁从{origin_station}前往{destination_station}。"
                if use_chinese
                else f"Take high-speed rail from {origin_station} to {destination_station}."
            )
        if keep_last and keep_last.title.strip().lower() in generic_titles and (
            _is_rail_transport_mode(logistics.return_transport) or _is_rail_transport_mode(logistics.outbound_transport)
        ):
            keep_last.title = f"{destination_station}至{origin_station}" if use_chinese else f"{destination_station} to {origin_station}"
            keep_last.location = destination_station
            keep_last.description = (
                f"搭乘高铁从{destination_station}返回{origin_station}。"
                if use_chinese
                else f"Return by high-speed rail from {destination_station} to {origin_station}."
            )

    first_day.events.sort(key=lambda event: _sort_key(event.start_time))
    last_day.events.sort(key=lambda event: _sort_key(event.start_time))


def _search_event_visual(destination: str, event: TimelineEvent) -> VisualReference | None:
    kind = _classify_event(event.title)
    if kind not in {"scenic", "food"}:
        event.image_url = None
        return None
    if kind == "food":
        if not event.image_url:
            event.image_url = _food_image_for(f"{destination}-{event.title}-{event.location}")
        return None

    if _is_generic_activity_title(event.title):
        event.image_url = None
        return None

    use_chinese = _should_use_chinese(destination, event.location)
    if use_chinese:
        candidates = [f"{event.title} {destination} 景区 实拍"]
        if event.location and event.location != destination:
            candidates.append(f"{event.location} {destination} 景点")
        candidates.append(f"{destination} {event.title} 风景")
    else:
        candidates = [f"\"{event.title}\" {destination} landmark"]
        if event.location and event.location != destination:
            candidates.append(f"{event.location} {destination}")
        candidates.append(f"{destination} {event.title}")

    for candidate in candidates:
        reference = IMAGE_LOOKUP.verified_image(candidate)
        if reference and reference.image_url:
            event.image_url = reference.image_url
            return VisualReference(title=event.title, image_url=reference.image_url, source_url=reference.source_url)

    event.image_url = None
    return None


def _enrich_visuals(destination: str, timeline_days: list[DayPlan]) -> list[VisualReference]:
    references: list[VisualReference] = []
    seen_urls: set[str] = set()
    pending_events: list[TimelineEvent] = []
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "scenic":
                continue
            pending_events.append(event)
            if len(pending_events) >= 60:
                break
        if len(pending_events) >= 60:
            break
    if not pending_events:
        return references

    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    futures = {}
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="img-enrich") as pool:
        for event in pending_events:
            futures[pool.submit(_search_event_visual, destination, event)] = event
            
        for future in as_completed(futures):
            event = futures[future]
            try:
                # 15s timeout per image search chain (which tries up to 3 queries)
                res = future.result(timeout=15)
                if res and res.image_url and res.source_url and _is_valid_reference_url(res.source_url):
                    if res.image_url not in seen_urls:
                        seen_urls.add(res.image_url)
                        references.append(res)
            except Exception as exc:
                # Assuming 'logger' is defined elsewhere in the module
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("[enrich] image search failed for event '%s': %s", event.title, exc)

    return references


def _base_trip_fields(
    *,
    trip_id: str,
    now: str,
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str,
) -> dict[str, object]:
    provider_warnings: list[ProviderWarning] = []
    if resolved_model.source == "mock":
        provider_warnings.append(
            ProviderWarning(source="model", message="Using mock model fallback because backend/.env is incomplete.", severity="medium")
        )
    return {
        "trip_id": trip_id,
        "interaction_mode": interaction_mode,
        "selected_model_id": resolved_model.model_id,
        "model_source": resolved_model.source,
        "query": query,
        "provider_warnings": provider_warnings,
        "created_at": now,
        "updated_at": now,
    }


def _parse_cost_amount(cost: str | None) -> float | None:
    if not cost:
        return None
    lowered = cost.strip().lower()
    if lowered in {"free", "$0", "0"}:
        return 0.0
    if lowered in {"approximate", "预估"}:
        return None
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", cost)
    if not match:
        return None
    try:
        base_amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    currency_multiplier = 1.0
    lowered_full = cost.lower()
    if "hk$" in lowered_full:
        currency_multiplier = 0.92
    elif "us$" in lowered_full or "$" in cost:
        currency_multiplier = 7.2
    elif "cny" in lowered_full or "rmb" in lowered_full or "¥" in cost:
        currency_multiplier = 1.0
    return base_amount * currency_multiplier


def _normalize_price_to_rmb_label(price: str | None) -> str | None:
    amount = _parse_cost_amount(price)
    if amount is None:
        return None
    return f"¥{round(amount)}"


def _estimate_transport_one_way(logistics: TravelLogistics) -> float:
    destination_for_search = _transport_search_destination(logistics.destination)
    lowered = logistics.outbound_transport.lower()
    if any(token in lowered for token in ["flight", "plane", "air"]) or any(token in logistics.outbound_transport for token in ["航班", "飞机"]):
        return _estimate_transport_unit_price_rmb(logistics.origin, destination_for_search, mode="flight")
    if any(token in lowered for token in ["rail", "train", "high-speed"]) or any(token in logistics.outbound_transport for token in ["高铁", "动车", "火车"]):
        return _estimate_transport_unit_price_rmb(logistics.origin, destination_for_search, mode="train")
    if "ferry" in lowered or any(token in logistics.outbound_transport for token in ["轮渡", "船"]):
        return 55.0
    return 90.0


def _format_currency(amount: float, symbol: str = "¥") -> str:
    return f"{symbol}{round(amount)}"


def _find_transport_leg_price(timeline_days: list[DayPlan], leg: str) -> float | None:
    leg = leg.lower()
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "transport":
                continue
            lowered = event.title.lower()
            if leg == "outbound" and (event.id.endswith("-arrival") or "arrival transfer" in lowered or "出发" in event.title):
                return _parse_cost_amount(event.cost_estimate)
            if leg == "return" and (event.id.endswith("-return") or "return transfer" in lowered or "返回" in event.title or "返程" in event.title):
                return _parse_cost_amount(event.cost_estimate)
    return None


def _transport_bucket(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["flight", "plane", "air", "航班", "飞机", "机场"]):
        return "flight"
    if any(token in lowered for token in ["train", "rail", "high-speed", "动车", "高铁", "火车"]):
        return "rail"
    if any(token in lowered for token in ["rent", "car rental", "self-drive", "租车", "自驾"]):
        return "car_rental"
    return "city"


def _estimate_budget_summary(
    parsed: dict[str, str | int | None],
    logistics: TravelLogistics,
    timeline_days: list[DayPlan],
) -> BudgetSummary:
    travelers = max(int(logistics.travelers or 1), 1)
    room_count = max((travelers + 1) // 2, 1)
    duration_days = max(len(timeline_days), 1)

    use_chinese = _should_use_chinese(logistics.destination, logistics.origin)
    notes: list[str] = []
    currency_symbol = "¥"
    hotel_amount = None
    hotel_total_override = None
    labeled_hotel_totals: list[float] = []
    for day in timeline_days:
        for event in day.events:
            if _classify_event(event.title) != "hotel":
                continue
            amount = _parse_cost_amount(event.cost_estimate)
            if amount is None:
                continue
            lowered_cost = str(event.cost_estimate or "").lower()
            if any(token in lowered_cost for token in ["房费", "room)", "stay total"]):
                labeled_hotel_totals.append(amount)
            elif hotel_amount is None:
                hotel_amount = amount
    if labeled_hotel_totals:
        hotel_total_override = sum(labeled_hotel_totals)
        hotel_amount = hotel_total_override / max(duration_days, 1)
    if hotel_amount is None:
        hotel_amount = 120.0
        notes.append("酒店价格为预估值。" if use_chinese else "Hotel price uses approximate estimate.")

    ticket_totals_by_day: list[float] = []
    for day in timeline_days:
        day_total = 0.0
        for event in day.events:
            kind = _classify_event(event.title)
            amount = _parse_cost_amount(event.cost_estimate)
            if amount is None:
                if kind == "scenic":
                    amount = 0.0
                elif kind == "transport":
                    amount = None
                else:
                    amount = 0.0
            if kind == "scenic":
                day_total += amount * travelers
        ticket_totals_by_day.append(day_total)

    outbound_event_price = _find_transport_leg_price(timeline_days, "outbound")
    return_event_price = _find_transport_leg_price(timeline_days, "return")
    if outbound_event_price is None:
        notes.append("去程交通费用为预估值。" if use_chinese else "Outbound transport price uses estimate.")
    if return_event_price is None:
        notes.append("返程交通费用为预估值。" if use_chinese else "Return transport price uses estimate.")
    outbound_total = outbound_event_price if outbound_event_price is not None else (_estimate_transport_one_way(logistics) * travelers)
    return_total = return_event_price if return_event_price is not None else (_estimate_transport_one_way(logistics) * travelers)

    flight_total = 0.0
    rail_total = 0.0
    city_transport_total = 0.0
    car_rental_total = 0.0

    outbound_bucket = _transport_bucket(logistics.outbound_transport)
    return_bucket = _transport_bucket(logistics.return_transport)
    if outbound_bucket == "flight":
        flight_total += outbound_total
    elif outbound_bucket == "rail":
        rail_total += outbound_total
    elif outbound_bucket == "car_rental":
        car_rental_total += outbound_total
    else:
        city_transport_total += outbound_total
    if return_bucket == "flight":
        flight_total += return_total
    elif return_bucket == "rail":
        rail_total += return_total
    elif return_bucket == "car_rental":
        car_rental_total += return_total
    else:
        city_transport_total += return_total

    hotel_total = hotel_amount * room_count * duration_days
    if hotel_total_override is not None:
        hotel_total = hotel_total_override
    ticket_total = sum(ticket_totals_by_day)
    transport_total = flight_total + rail_total + city_transport_total + car_rental_total
    trip_total_value = round(transport_total + hotel_total + ticket_total)
    hotel_daily_share = hotel_total / max(duration_days, 1)
    current_day_value = round(
        (ticket_totals_by_day[0] if ticket_totals_by_day else 0.0)
        + hotel_daily_share
        + outbound_total
    )

    raw_budget = str(parsed.get("budget") or "").strip().lower()
    normalized_budget = _normalize_budget_preference(raw_budget)
    numeric_budget = _parse_cost_amount(raw_budget) if raw_budget else None
    if numeric_budget is not None:
        target = numeric_budget
    elif normalized_budget == "low":
        target = 180.0 * travelers * duration_days + transport_total
    elif normalized_budget == "high":
        target = 420.0 * travelers * duration_days + transport_total
    else:
        target = 300.0 * travelers * duration_days + transport_total

    ratio = trip_total_value / max(target, 1.0)
    if ratio <= 1.0:
        status = "on_track"
    elif ratio <= 1.2:
        status = "watch"
    else:
        status = "over"

    return BudgetSummary(
        trip_total_estimate=_format_currency(trip_total_value, currency_symbol),
        current_day_estimate=_format_currency(current_day_value, currency_symbol),
        budget_status=status,
        transport_total_estimate=_format_currency(transport_total, currency_symbol),
        flight_total_estimate=_format_currency(flight_total, currency_symbol),
        rail_total_estimate=_format_currency(rail_total, currency_symbol),
        city_transport_total_estimate=_format_currency(city_transport_total, currency_symbol),
        car_rental_total_estimate=_format_currency(car_rental_total, currency_symbol),
        hotel_total_estimate=_format_currency(hotel_total, currency_symbol),
        ticket_total_estimate=_format_currency(ticket_total, currency_symbol),
        notes=list(dict.fromkeys(notes)),
    )


def _extract_json_object(content: str) -> dict[str, object]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(cleaned[start : end + 1])


def _merge_parsed(
    heuristic: dict[str, str | int | None],
    extracted: dict[str, str | int | None],
) -> dict[str, str | int | None]:
    merged = dict(heuristic)
    for key, value in extracted.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _extract_constraints_with_model(
    query: str,
    resolved_model: ResolvedModelConfig,
    model_client: ModelApiClient | None,
) -> dict[str, str | int | None]:
    if model_client is None or resolved_model.source == "mock":
        return {}

    prompt = (
        "Extract structured travel constraints from the user request. "
        "Return strict JSON only with this shape: "
        "{\"origin\":null,\"destination\":null,\"travelers\":null,\"budget\":null,"
        "\"style\":null,\"duration_days\":null}. "
        "Use null for unknown values. "
        "Budget should be a short string like \"low\", \"balanced\", \"high\", or \"$1200\". "
        "Style should be a short label like \"Relaxed\", \"Food focused\", \"Family friendly\", or \"Packed\". "
        "Destination and origin can be any city or place name."
    )
    try:
        raw = model_client.complete_json(
            resolved_model=resolved_model,
            system_prompt="You extract travel constraints. Output valid JSON only.",
            user_prompt=f"{prompt}\nUser request: {query}",
        )
        parsed = _extract_json_object(raw)
    except Exception:
        return {}
    result: dict[str, str | int | None] = {}

    origin = parsed.get("origin")
    destination = parsed.get("destination")
    travelers = parsed.get("travelers")
    budget = parsed.get("budget")
    style = parsed.get("style")
    duration_days = parsed.get("duration_days")

    if isinstance(origin, str):
        result["origin"] = origin.strip().title()
    if isinstance(destination, str):
        result["destination"] = destination.strip().title()
    if isinstance(travelers, int):
        result["travelers"] = max(1, min(travelers, 12))
    elif isinstance(travelers, str) and travelers.strip().isdigit():
        result["travelers"] = max(1, min(int(travelers.strip()), 12))
    if isinstance(budget, str):
        result["budget"] = budget.strip()
    if isinstance(style, str):
        result["style"] = style.strip().title()
    if isinstance(duration_days, int):
        result["duration_days"] = max(1, min(duration_days, 10))
    elif isinstance(duration_days, str) and duration_days.strip().isdigit():
        result["duration_days"] = max(1, min(int(duration_days.strip()), 10))
    return result


def _planning_system_prompt() -> str:
    return (
        "You are a travel planning assistant.\n"
        "The user will provide free-form travel requirements.\n"
        "You must use the provided grounding context from search and map results to build a realistic trip.\n"
        "Choose practical transport, select well-known POIs, avoid filler meals, and only include standout food recommendations.\n"
        "CRITICAL ROUTING RULES:\n"
        "- Group attractions that are geographically close together on the same day.\n"
        "- Within each day, order events so the route flows in one direction without backtracking.\n"
        "- Minimize total transit time by visiting nearby POIs consecutively.\n"
        "- When the itinerary enters a new city, add a same-day hotel check-in event in that city and choose a reasonable hotel name for that city.\n"
        "- If the itinerary remains in a single city, keep one stable hotel and do not switch hotels day by day.\n"
        "- Each day must have 4-6 meaningful events spanning from ~08:00 to ~21:00.\n"
        "- Spread activities evenly across the day with reasonable gaps (1-2 hours per event).\n"
        "- Do NOT leave large empty blocks; cover morning, afternoon, and evening.\n"
        "Output valid JSON only with no markdown fences."
    )


def _planning_draft_system_prompt() -> str:
    return (
        "You are a travel planning assistant.\n"
        "The user's requirements will follow.\n"
        "Generate an initial structured itinerary draft in JSON.\n"
        "Do not use markdown fences.\n"
        "Do not add routine lunch or dinner filler unless the trip is explicitly food-focused.\n"
        "Group attractions by geographic area or district for each day.\n"
        "Order events within each day to flow geographically without backtracking across the city.\n"
        "If you move into a new city, add a same-day hotel check-in in that city with a realistic hotel name.\n"
        "If the whole itinerary is single-city, keep one hotel for the full stay and do not add hotel switches.\n"
        "Each day must have 4-6 events covering morning (~08:00) through evening (~21:00)."
    )


def _prune_routine_food_events(timeline_days: list[DayPlan], style: str | None) -> None:
    keep_food = _is_food_focused_style(style)
    generic_food_tokens = {"local lunch", "light lunch before departure", "hotel breakfast", "breakfast"}
    for day in timeline_days:
        filtered: list[TimelineEvent] = []
        food_kept = False
        for event in day.events:
            kind = _classify_event(event.title)
            lowered = event.title.lower()
            if kind == "food":
                standout = not any(token == lowered for token in generic_food_tokens) and any(
                    token in lowered for token in ["馆", "restaurant", "cafe", "bistro", "food", "market", "roast", "hotpot", "sushi"]
                )
                if keep_food and not food_kept:
                    filtered.append(event)
                    food_kept = True
                elif standout and not food_kept:
                    filtered.append(event)
                    food_kept = True
                continue
            filtered.append(event)
        day.events = filtered


class PlannerGraphState(TypedDict, total=False):
    query: str
    resolved_model: ResolvedModelConfig
    interaction_mode: str
    existing_trip_id: str | None
    model_client: ModelApiClient | None
    now: str
    trip_id: str
    base_fields: dict[str, object]
    heuristic: dict[str, str | int | None]
    extracted: dict[str, str | int | None]
    parsed: dict[str, str | int | None]
    clarification_questions: list[ClarificationQuestion]
    search_context: str
    prefetched_amap: dict[str, list]
    prefetched_attractions: list[tuple[str, str]]
    draft_content: str
    refined_content: str
    model_payload: dict[str, object] | None
    trip: TripState


def _build_draft_llm_prompt(query: str, parsed: dict[str, str | int | None], interaction_mode: str) -> str:
    destination = parsed.get("destination") or "the destination"
    duration_days = parsed.get("duration_days") or 3
    budget = parsed.get("budget") or "balanced"
    style = parsed.get("style") or "Balanced"
    travelers = parsed.get("travelers") or 1
    origin = parsed.get("origin") or "the departure city"
    transport_mode = _choose_transport_mode(str(origin), str(destination))
    outbound_date, return_date = _default_departure_dates(int(duration_days))
    return (
        "Create a realistic travel itinerary draft from the user requirements. "
        "Return strict JSON only with this shape: "
        "{\"plan_summary\":{\"headline\":\"\",\"body\":\"\",\"highlights\":[\"\",\"\"]},"
        "\"travel_logistics\":{\"origin\":\"\",\"destination\":\"\",\"travelers\":1,"
        "\"outbound_transport\":\"\",\"return_transport\":\"\",\"outbound_schedule\":\"\","
        "\"return_schedule\":\"\",\"hotel_name\":\"\"},"
        "\"days\":[{\"theme\":\"\",\"events\":[{\"start_time\":\"08:00\",\"end_time\":\"09:30\","
        "\"title\":\"\",\"location\":\"\",\"travel_time_from_previous\":\"10 min\","
        "\"cost_estimate\":\"$20\",\"description\":\"\",\"risk_flags\":[\"\"]}]}],"
        "\"budget_summary\":{\"trip_total_estimate\":\"$480\",\"current_day_estimate\":\"$120\",\"budget_status\":\"on_track\"},"
        "\"map_preview\":{\"route_label\":\"\",\"stops\":[\"\",\"\"],\"total_transit_time\":\"1h 00m\"},"
        "\"reference_links\":[{\"title\":\"\",\"url\":\"https://example.com\",\"label\":\"\"}]}. "
        f"Mode: {interaction_mode}.\n"
        f"User request: {query}\n"
        f"Origin: {origin}\n"
        f"Destination: {destination}\n"
        f"Travelers: {travelers}\n"
        f"Duration days: {duration_days}\n"
        f"Budget: {budget}\n"
        f"Style: {style}\n"
        f"Recommended transport mode: {transport_mode}\n"
        f"If no user date is present, use outbound date {outbound_date.strftime('%Y-%m-%d')} and return date {return_date.strftime('%Y-%m-%d')}.\n"
        "Make exactly one day object per travel day. Prioritize well-known attractions and landmark areas. "
        "Do not insert routine lunch or dinner fillers. Only add a food stop if it is a notable local recommendation or the user is food-focused. "
        "Each day MUST have 4-6 meaningful events spanning from ~08:00 to ~21:00. "
        "IMPORTANT: Group geographically close attractions on the same day. "
        "Order each day's events STRICTLY by physical proximity to form a logical route without backtracking (e.g., A -> B -> C, where A is near B, and B is near C). "
        "Visit nearby POIs consecutively to minimize transit time between stops. "
        "Spread activities evenly across morning, afternoon, and evening — no large empty gaps. "
        "Travel logistics should be practical. You MUST select a centrally located hotel near the destination's primary attractions to minimize daily commuting. "
        "If the route enters a different city than the previous day, include a same-day hotel check-in event in that new city and use a plausible local hotel name. "
        "If all days are within one city, keep a single consistent hotel for all days and do not switch hotels. "
        "Pick a transport mode first, then provide realistic departure and arrival time windows. "
        "If an exact price is unknown, write approximate. "
        "CRITICAL: If the destination is within Greater China (Mainland, Hong Kong, Macau, Taiwan), you MUST output the `destination`, `title`, and `location` fields in Simplified Chinese (e.g., '北京' instead of 'Beijing', '故宫' instead of 'Forbidden City'), even if the user query is in English. This is strictly required for the map API to geocode correctly."
    )


def _build_refinement_prompt(
    query: str,
    parsed: dict[str, str | int | None],
    interaction_mode: str,
    draft_json: str,
    search_context: str,
) -> str:
    destination = parsed.get("destination") or "the destination"
    return (
        f"You are a travel planning assistant.\n"
        f"The user's requirements are: {query}.\n"
        "Now let's plan the journey from the start city to the target city.\n"
        "You are given:\n"
        "1. An initial itinerary draft from a large model.\n"
        "2. Search and map grounding context with REAL POIs and their addresses.\n"
        "Use both to produce a better final itinerary.\n"
        "REFINEMENT RULES:\n"
        "- Replace any generic or hallucinated POIs with real ones from the grounding context.\n"
        "- STRICTLY reorder events within each day based on actual geographic proximity to create a logical, linear route without any backtracking.\n"
        "- Ensure each day has 4-6 events from ~08:00 to ~21:00, spread evenly.\n"
        "- Group geographically close POIs on the same day.\n"
        "- If the route enters a new city, add a hotel check-in event in that city on the same day and choose a realistic local hotel.\n"
        "- If the itinerary is single-city, keep one stable hotel throughout all days and avoid hotel changes.\n"
        "- Choose a centrally located hotel from the grounding context if applicable, near the main attractions.\n"
        "- Keep only meaningful food stops (famous local specialties, not routine meals).\n"
        "- CRITICAL: If the destination is within Greater China (Mainland, Hong Kong, Macau, Taiwan), you MUST output the `destination`, `title`, and `location` fields in Simplified Chinese (e.g., '北京' instead of 'Beijing', '故宫' instead of 'Forbidden City'). This is strictly required for the map API to geocode correctly.\n"
        "Return strict JSON only in the same schema as the draft.\n\n"
        f"Mode: {interaction_mode}\n"
        f"Initial draft JSON:\n{draft_json}\n\n"
        f"{search_context}\n"
    )


def _trip_from_fallback(
    *,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
    resolved_model: ResolvedModelConfig | None = None,
    model_client: ModelApiClient | None = None,
) -> TripState:
    destination = str(parsed["destination"])
    query_text = str(base_fields.get("query") or "")
    north_xinjiang_requested = _is_north_xinjiang_destination(destination) or _is_north_xinjiang_destination(query_text)
    origin = str(parsed.get("origin") or "Your city")
    use_chinese = _should_use_chinese(destination, origin)
    duration_days = int(parsed["duration_days"])
    budget = parsed.get("budget")
    style = parsed.get("style")
    logistics = _default_logistics(parsed)
    timeline_days = [
        _build_day(index, destination, style if isinstance(style, str) else None, budget if isinstance(budget, str) else None)
        for index in range(duration_days)
    ]
    provider_warnings = list(base_fields["provider_warnings"])
    provider_warnings.extend(
        _apply_amap_candidates(
            destination,
            timeline_days,
            logistics,
            prefetched_amap=prefetched_amap,
            prefetched_attractions=prefetched_attractions,
            resolved_model=resolved_model,
            model_client=model_client,
        )
    )
    _inject_logistics_events(timeline_days, logistics)
    _enforce_north_xinjiang_loop(
        timeline_days,
        logistics,
        requested_destination=destination if north_xinjiang_requested else None,
    )
    _dedupe_terminal_transport_events(timeline_days, logistics)
    _ensure_city_hotel_policy(
        logistics.destination,
        timeline_days,
        logistics,
        resolved_model=resolved_model,
        model_client=model_client,
    )
    _prune_routine_food_events(timeline_days, style if isinstance(style, str) else None)
    _hydrate_event_geocodes(logistics.destination, timeline_days, logistics)
    _annotate_route_travel_times(logistics.destination, timeline_days)
    _build_day_routes(logistics.destination, timeline_days)
    _ensure_cost_estimates(timeline_days)
    _assign_food_images(timeline_days)
    live_references, live_warnings = _apply_live_search(
        logistics,
        timeline_days,
        resolved_model=resolved_model,
        model_client=model_client,
    )
    _apply_known_ticket_prices(logistics.destination, timeline_days)
    provider_warnings.extend(live_warnings)
    computed_budget = _estimate_budget_summary(parsed, logistics, timeline_days)
    if base_fields["model_source"] != "mock":
        provider_warnings.append(
            ProviderWarning(
                source="model",
                message=(
                    "模型返回格式不可解析，已使用本地兜底行程。"
                    if use_chinese
                    else "The model response could not be parsed, so a local fallback itinerary was used."
                ),
                severity="medium",
            )
        )
    image_references = _replace_scenic_images_with_serper_live(logistics.destination, timeline_days, [])
    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    return TripState(
        **trip_fields,
        view_state="partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready",
        plan_summary=PlanSummary(
            headline=f"{duration_days}天{logistics.destination}行程已生成" if use_chinese else f"{duration_days}-day {logistics.destination} plan ready",
            body=(
                "行程已包含抵达、住宿、每日节奏与返程，可直接执行。"
                if use_chinese
                else "The itinerary includes arrival, hotel, daily pacing, and the return leg so the full trip is executable."
            ),
            highlights=(["已含交通住宿", "结构化时间线", "预算可跟踪"] if use_chinese else ["Logistics Included", "Structured Timeline", "Budget Aware"]),
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=computed_budget,
        memory_summary=MemorySummary(
            fixed_anchors=(["酒店入住", logistics.hotel_name] if use_chinese else ["Hotel check-in", logistics.hotel_name]),
            open_constraints=[],
            user_preferences=[value for value in [style, budget] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="itinerary_generation",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=f"{logistics.destination}完整路线" if use_chinese else f"{logistics.destination} full-trip route",
            stops=[event.location for event in timeline_days[0].events[:4]],
            total_transit_time="约2小时10分钟" if use_chinese else "2h 10m",
            image_references=image_references,
        ),
        travel_logistics=logistics,
        reference_links=_merge_reference_links(live_references, _reference_links(logistics.destination)),
        planning_trace=[],
    )


def _trip_from_model(
    *,
    parsed: dict[str, str | int | None],
    base_fields: dict[str, object],
    model_payload: dict[str, object],
    prefetched_amap: dict[str, list] | None = None,
    prefetched_attractions: list[tuple[str, str]] | None = None,
    resolved_model: ResolvedModelConfig | None = None,
    model_client: ModelApiClient | None = None,
) -> TripState:
    duration_days = int(parsed["duration_days"])
    days_payload = model_payload.get("days")
    if not isinstance(days_payload, list):
        days_payload = []

    timeline_days: list[DayPlan] = []
    style_value = parsed.get("style") if isinstance(parsed.get("style"), str) else None
    budget_value = parsed.get("budget") if isinstance(parsed.get("budget"), str) else None
    destination_value = str(parsed.get("destination") or "Custom Destination")
    query_text = str(base_fields.get("query") or "")
    north_xinjiang_requested = _is_north_xinjiang_destination(destination_value) or _is_north_xinjiang_destination(query_text)
    origin_value = str(parsed.get("origin") or "Your city")
    use_chinese = _should_use_chinese(destination_value, origin_value)
    model_fallback_day_count = 0
    for day_index in range(duration_days):
        raw_day = days_payload[day_index] if day_index < len(days_payload) else {}
        raw_events = raw_day.get("events") if isinstance(raw_day, dict) else []
        events: list[TimelineEvent] = []
        fallback_day: DayPlan | None = None
        if isinstance(raw_events, list):
            for event_index, raw_event in enumerate(raw_events[:8]):
                if not isinstance(raw_event, dict):
                    continue
                title = str(raw_event.get("title", f"Activity {event_index + 1}"))
                kind = _classify_event(title)
                events.append(
                    TimelineEvent(
                        id=f"d{day_index + 1}-e{event_index + 1}",
                        start_time=str(raw_event.get("start_time", f"{9 + event_index * 3:02d}:00")),
                        end_time=str(raw_event.get("end_time", f"{11 + event_index * 3:02d}:00")),
                        title=title if not _is_generic_activity_title(title) else (f"活动{event_index + 1}" if use_chinese else title),
                        location=str(raw_event.get("location", "推荐区域" if use_chinese else "Recommended area")),
                        travel_time_from_previous=str(raw_event.get("travel_time_from_previous", "15 分钟" if use_chinese else "15 min")),
                        cost_estimate=str(raw_event.get("cost_estimate")) if raw_event.get("cost_estimate") is not None else None,
                        description=str(raw_event.get("description", "基于你的偏好推荐此站点。" if use_chinese else "A suggested stop based on your selected constraints.")),
                        image_url=_placeholder_image(kind) if kind in {"scenic", "food"} else None,
                        risk_flags=[str(flag) for flag in raw_event.get("risk_flags", []) if isinstance(flag, (str, int, float))],
                    )
                )
        if not events:
            fallback_day = _build_day(day_index, destination_value, style_value, budget_value)
            events = fallback_day.events
            model_fallback_day_count += 1
        raw_theme = str(raw_day.get("theme")) if isinstance(raw_day, dict) and raw_day.get("theme") is not None else None
        theme = _normalize_day_theme(raw_theme or (fallback_day.theme if fallback_day else None), day_index, use_chinese=use_chinese)
        raw_title = str(raw_day.get("title")) if isinstance(raw_day, dict) and raw_day.get("title") is not None else None
        if raw_title and raw_title.strip():
            candidate_title = raw_title.strip()
            if use_chinese and (re.fullmatch(r"day\s*\d+.*", candidate_title.lower()) or not _contains_chinese(candidate_title)):
                day_title = f"第{day_index + 1}天"
            else:
                day_title = candidate_title
        else:
            day_title = f"第{day_index + 1}天" if use_chinese else f"Day {day_index + 1}"
        timeline_days.append(DayPlan(day_index=day_index, title=day_title, theme=theme, events=events))

    summary_payload = model_payload.get("plan_summary") if isinstance(model_payload.get("plan_summary"), dict) else {}
    budget_payload = model_payload.get("budget_summary") if isinstance(model_payload.get("budget_summary"), dict) else {}
    map_payload = model_payload.get("map_preview") if isinstance(model_payload.get("map_preview"), dict) else {}
    logistics_payload = model_payload.get("travel_logistics") if isinstance(model_payload.get("travel_logistics"), dict) else {}
    links_payload = model_payload.get("reference_links") if isinstance(model_payload.get("reference_links"), list) else []

    default_logistics = _default_logistics(parsed)
    logistics = TravelLogistics(
        origin=str(logistics_payload.get("origin", default_logistics.origin)),
        destination=str(logistics_payload.get("destination", default_logistics.destination)),
        travelers=int(logistics_payload.get("travelers", default_logistics.travelers)),
        outbound_transport=str(logistics_payload.get("outbound_transport", default_logistics.outbound_transport)),
        return_transport=str(logistics_payload.get("return_transport", default_logistics.return_transport)),
        outbound_schedule=str(logistics_payload.get("outbound_schedule", default_logistics.outbound_schedule)),
        return_schedule=str(logistics_payload.get("return_schedule", default_logistics.return_schedule)),
        hotel_name=str(
            logistics_payload.get(
                "hotel_name",
                f"{_normalize_city_for_geocode(str(parsed.get('destination') or '待定目的地'))}市中心酒店"
                if use_chinese
                else f"{parsed.get('destination') or 'Central'} Grand Hotel",
            )
        ),
    )
    if north_xinjiang_requested:
        _force_north_xinjiang_logistics(logistics, use_chinese=use_chinese)
    provider_warnings = list(base_fields["provider_warnings"])
    if model_fallback_day_count > 0:
        provider_warnings.append(
            ProviderWarning(
                source="model",
                message=(
                    f"模型返回了 {model_fallback_day_count} 个空白天，已使用本地模板补齐。"
                    if use_chinese
                    else f"Model returned {model_fallback_day_count} empty day(s); fallback day templates were used."
                ),
                severity="medium",
            )
        )
    provider_warnings.extend(
        _apply_amap_candidates(
            logistics.destination,
            timeline_days,
            logistics,
            prefetched_amap=prefetched_amap,
            prefetched_attractions=prefetched_attractions,
            resolved_model=resolved_model,
            model_client=model_client,
        )
    )
    _inject_logistics_events(timeline_days, logistics)
    _enforce_north_xinjiang_loop(
        timeline_days,
        logistics,
        requested_destination=destination_value if north_xinjiang_requested else None,
    )
    _dedupe_terminal_transport_events(timeline_days, logistics)
    _ensure_city_hotel_policy(
        logistics.destination,
        timeline_days,
        logistics,
        resolved_model=resolved_model,
        model_client=model_client,
    )
    _prune_routine_food_events(timeline_days, parsed.get("style") if isinstance(parsed.get("style"), str) else None)
    _hydrate_event_geocodes(logistics.destination, timeline_days, logistics)
    _annotate_route_travel_times(logistics.destination, timeline_days)
    _build_day_routes(logistics.destination, timeline_days)
    _ensure_cost_estimates(timeline_days)
    _assign_food_images(timeline_days)
    image_references = _replace_scenic_images_with_serper_live(logistics.destination, timeline_days, [])

    reference_links = _sanitize_reference_links([
        ReferenceLink(
            title=str(item.get("title", "外部参考" if use_chinese else "External reference")),
            url=str(item.get("url", "https://www.google.com")),
            label=str(item.get("label", "打开" if use_chinese else "Open")),
        )
        for item in links_payload[:3]
        if isinstance(item, dict)
    ])
    if not reference_links:
        reference_links = _reference_links(logistics.destination)
    live_references, live_warnings = _apply_live_search(
        logistics,
        timeline_days,
        resolved_model=resolved_model,
        model_client=model_client,
    )
    _apply_known_ticket_prices(logistics.destination, timeline_days)
    provider_warnings.extend(live_warnings)
    computed_budget = _estimate_budget_summary(parsed, logistics, timeline_days)
    reference_links = _merge_reference_links(live_references, reference_links, _reference_links(logistics.destination))

    trip_fields = {**base_fields, "provider_warnings": provider_warnings}
    return TripState(
        **trip_fields,
        view_state="partial_itinerary_with_warnings" if provider_warnings else "itinerary_ready",
        plan_summary=PlanSummary(
            headline=str(summary_payload.get("headline", f"{duration_days}天{logistics.destination}行程已生成" if use_chinese else f"{duration_days}-day {logistics.destination} plan ready")),
            body=str(summary_payload.get("body", "已生成结构化行程，可直接执行。" if use_chinese else "A structured itinerary generated by the selected model.")),
            highlights=[str(item) for item in summary_payload.get("highlights", []) if isinstance(item, (str, int, float))][:4],
        ),
        clarification_questions=[],
        timeline_days=timeline_days,
        budget_summary=BudgetSummary(
            trip_total_estimate=computed_budget.trip_total_estimate,
            current_day_estimate=computed_budget.current_day_estimate,
            budget_status=str(budget_payload.get("budget_status", computed_budget.budget_status))
            if str(budget_payload.get("budget_status", computed_budget.budget_status)) in {"on_track", "watch", "over"}
            else computed_budget.budget_status,
            transport_total_estimate=computed_budget.transport_total_estimate,
            flight_total_estimate=computed_budget.flight_total_estimate,
            rail_total_estimate=computed_budget.rail_total_estimate,
            city_transport_total_estimate=computed_budget.city_transport_total_estimate,
            car_rental_total_estimate=computed_budget.car_rental_total_estimate,
            hotel_total_estimate=computed_budget.hotel_total_estimate,
            ticket_total_estimate=computed_budget.ticket_total_estimate,
            notes=[
                str(item)
                for item in (
                    budget_payload.get("notes")
                    if isinstance(budget_payload.get("notes"), list)
                    else computed_budget.notes
                )
                if isinstance(item, (str, int, float))
            ],
        ),
        memory_summary=MemorySummary(
            fixed_anchors=["酒店入住", logistics.hotel_name] if use_chinese else ["Hotel check-in", logistics.hotel_name],
            open_constraints=[],
            user_preferences=[value for value in [parsed.get("style"), parsed.get("budget")] if isinstance(value, str)],
            last_selected_model=base_fields["selected_model_id"],
            route_mode="model_generated",
        ),
        conflict_warnings=[],
        map_preview=MapPreview(
            route_label=str(map_payload.get("route_label", f"{logistics.destination}完整路线" if use_chinese else f"{logistics.destination} complete route")),
            stops=[str(item) for item in map_payload.get("stops", []) if isinstance(item, (str, int, float))][:6],
            total_transit_time=str(map_payload.get("total_transit_time", "约2小时" if use_chinese else "2h 00m")),
            image_references=image_references,
        ),
        travel_logistics=logistics,
        reference_links=reference_links,
        planning_trace=[],
    )


def _run_langgraph_planner(
    *,
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str,
    existing_trip_id: str | None,
    model_client: ModelApiClient | None,
) -> TripState:
    def extract_node(state: PlannerGraphState) -> PlannerGraphState:
        logger.info("[trip:%s] request received mode=%s model=%s query=%s", state["trip_id"], state["interaction_mode"], state["resolved_model"].model_id, state["query"][:160])
        heuristic = parse_intent(state["query"])
        extracted = _extract_constraints_with_model(state["query"], state["resolved_model"], state.get("model_client"))
        parsed = _normalize_defaults(_merge_parsed(heuristic, extracted), interaction_mode=state["interaction_mode"])
        clarification_questions = _planning_questions(parsed) if state["interaction_mode"] == "planning" else []
        logger.info(
            "[trip:%s] extract complete origin=%s destination=%s travelers=%s budget=%s style=%s duration=%s clarifications=%s",
            state["trip_id"],
            parsed.get("origin"),
            parsed.get("destination"),
            parsed.get("travelers"),
            parsed.get("budget"),
            parsed.get("style"),
            parsed.get("duration_days"),
            len(clarification_questions),
        )
        return {
            "heuristic": heuristic,
            "extracted": extracted,
            "parsed": parsed,
            "clarification_questions": clarification_questions,
        }

    def route_after_extract(state: PlannerGraphState) -> str:
        if state["interaction_mode"] == "planning" and state.get("clarification_questions"):
            return "end_clarification"
        return "search"

    def end_clarification_node(state: PlannerGraphState) -> PlannerGraphState:
        logger.info("[trip:%s] returning clarification brief", state["trip_id"])
        parsed = state["parsed"]
        base_fields = state["base_fields"]
        destination = str(parsed.get("destination") or "destination")
        trip = TripState(
            **base_fields,
            view_state="needs_clarification",
            plan_summary=PlanSummary(
                headline="Fill the planning brief first",
                body="Planning mode collects the trip brief up front, then generates the itinerary in one pass.",
                highlights=["Structured Brief", "Less Rework"],
            ),
            clarification_questions=state.get("clarification_questions", []),
            timeline_days=[],
            budget_summary=BudgetSummary(
                trip_total_estimate="Pending brief",
                current_day_estimate="Pending brief",
                budget_status="watch",
            ),
            memory_summary=MemorySummary(
                fixed_anchors=[],
                open_constraints=[question.label for question in state.get("clarification_questions", [])],
                user_preferences=[str(parsed.get("style"))] if parsed.get("style") else [],
                last_selected_model=resolved_model.model_id,
                route_mode="planning_brief",
            ),
            conflict_warnings=[],
            map_preview=MapPreview(route_label="Visual route unlocks after the brief is complete", stops=[], total_transit_time="Pending"),
            travel_logistics=_default_logistics({**parsed, "destination": destination if destination != "destination" else None}),
            reference_links=[],
            planning_trace=[],
        )
        return {"trip": trip}

    def search_and_draft_node(state: PlannerGraphState) -> PlannerGraphState:
        """Run search and draft LLM call in parallel to save wall-clock time.

        Each leg is independently error-tolerant: if either times out,
        we continue with whatever succeeded.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        parsed = state["parsed"]
        destination = str(parsed.get("destination") or "Custom Destination")
        origin = str(parsed.get("origin") or "Your city")
        style = parsed.get("style") if isinstance(parsed.get("style"), str) else None

        def _do_search() -> tuple[str, dict[str, list], list[tuple[str, str]]]:
            return _build_search_context(destination, origin, style)

        def _do_draft() -> str:
            if state["resolved_model"].source == "mock" or state.get("model_client") is None:
                return ""
            draft_system, draft_user = render_chat_prompts(
                _planning_draft_system_prompt(),
                _build_draft_llm_prompt(state["query"], state["parsed"], state["interaction_mode"]),
            )
            return state["model_client"].complete_json(
                resolved_model=state["resolved_model"],
                system_prompt=draft_system,
                user_prompt=draft_user,
            )

        logger.info("[trip:%s] search+draft parallel start", state["trip_id"])

        # Run both in parallel with individual error handling
        search_context = "Grounding context from search results and map providers:\nAttractions:\n- None found"
        prefetched_amap: dict[str, list] = {}
        prefetched_attractions: list[tuple[str, str]] = []
        draft_content = ""

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="plan-io") as pool:
            search_future = pool.submit(_do_search)
            draft_future = pool.submit(_do_draft)

            try:
                search_result = search_future.result(timeout=30)
                search_context, prefetched_amap, prefetched_attractions = search_result
            except Exception as exc:
                logger.warning("[trip:%s] search leg failed, continuing with empty context: %s", state["trip_id"], exc)

            try:
                draft_content = draft_future.result(timeout=90)
            except Exception as exc:
                logger.warning("[trip:%s] draft leg failed, continuing with empty draft: %s", state["trip_id"], exc)

        logger.info(
            "[trip:%s] search+draft parallel complete amap_attractions=%s amap_hotels=%s search_attractions=%s draft_len=%s",
            state["trip_id"],
            len(prefetched_amap.get("attractions", [])),
            len(prefetched_amap.get("hotels", [])),
            len(prefetched_attractions),
            len(draft_content),
        )
        return {
            "search_context": search_context,
            "prefetched_amap": prefetched_amap,
            "prefetched_attractions": prefetched_attractions,
            "draft_content": draft_content,
        }

    def refine_node(state: PlannerGraphState) -> PlannerGraphState:
        if state["resolved_model"].source == "mock" or state.get("model_client") is None:
            logger.info("[trip:%s] refine skipped (mock/no model client)", state["trip_id"])
            return {"refined_content": "", "model_payload": None}
        logger.info("[trip:%s] refine LLM call start", state["trip_id"])
        refine_system, refine_user = render_chat_prompts(
            _planning_system_prompt(),
            _build_refinement_prompt(
                state["query"],
                state["parsed"],
                state["interaction_mode"],
                state.get("draft_content") or "{}",
                state.get("search_context") or "Grounding context from search results and map providers:\nAttractions:\n- None found",
            ),
        )
        refined_content = state["model_client"].complete_json(
            resolved_model=state["resolved_model"],
            system_prompt=refine_system,
            user_prompt=refine_user,
        )
        model_payload: dict[str, object] | None = None
        try:
            model_payload = _extract_json_object(refined_content)
            logger.info("[trip:%s] refine parse succeeded", state["trip_id"])
        except (ValueError, TypeError, json.JSONDecodeError):
            try:
                model_payload = _extract_json_object(state.get("draft_content") or "")
                logger.info("[trip:%s] refine parse failed, using draft payload", state["trip_id"])
            except (ValueError, TypeError, json.JSONDecodeError):
                model_payload = None
                logger.info("[trip:%s] refine parse failed, falling back to local itinerary", state["trip_id"])
        return {"refined_content": refined_content, "model_payload": model_payload}

    def enrich_node(state: PlannerGraphState) -> PlannerGraphState:
        if state.get("model_payload"):
            logger.info("[trip:%s] enrich using model payload", state["trip_id"])
            try:
                trip = _trip_from_model(
                    parsed=state["parsed"],
                    base_fields=state["base_fields"],
                    model_payload=state["model_payload"],
                    prefetched_amap=state.get("prefetched_amap"),
                    prefetched_attractions=state.get("prefetched_attractions"),
                    resolved_model=state.get("resolved_model"),
                    model_client=state.get("model_client"),
                )
            except Exception as exc:
                logger.warning("[trip:%s] enrich model payload failed, fallback builder used: %s", state["trip_id"], exc)
                trip = _trip_from_fallback(
                    parsed=state["parsed"],
                    base_fields=state["base_fields"],
                    prefetched_amap=state.get("prefetched_amap"),
                    prefetched_attractions=state.get("prefetched_attractions"),
                    resolved_model=state.get("resolved_model"),
                    model_client=state.get("model_client"),
                )
        else:
            logger.info("[trip:%s] enrich using fallback builder", state["trip_id"])
            trip = _trip_from_fallback(
                parsed=state["parsed"],
                base_fields=state["base_fields"],
                prefetched_amap=state.get("prefetched_amap"),
                prefetched_attractions=state.get("prefetched_attractions"),
                resolved_model=state.get("resolved_model"),
                model_client=state.get("model_client"),
            )
        logger.info("[trip:%s] trip ready view_state=%s days=%s warnings=%s", state["trip_id"], trip.view_state, len(trip.timeline_days), len(trip.provider_warnings))
        return {"trip": trip}

    graph = StateGraph(PlannerGraphState)
    graph.add_node("extract", extract_node)
    graph.add_node("end_clarification", end_clarification_node)
    graph.add_node("search_and_draft", search_and_draft_node)
    graph.add_node("refine", refine_node)
    graph.add_node("enrich", enrich_node)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract",
        route_after_extract,
        {
            "end_clarification": "end_clarification",
            "search": "search_and_draft",
        },
    )
    graph.add_edge("end_clarification", END)
    graph.add_edge("search_and_draft", "refine")
    graph.add_edge("refine", "enrich")
    graph.add_edge("enrich", END)

    compiled = graph.compile()
    now = datetime.now(timezone.utc).isoformat()
    trip_id = existing_trip_id or uuid4().hex
    base_fields = _base_trip_fields(
        trip_id=trip_id,
        now=now,
        query=query,
        resolved_model=resolved_model,
        interaction_mode=interaction_mode,
    )
    final_state = compiled.invoke(
        PlannerGraphState(
            query=query,
            resolved_model=resolved_model,
            interaction_mode=interaction_mode,
            existing_trip_id=existing_trip_id,
            model_client=model_client,
            now=now,
            trip_id=trip_id,
            base_fields=base_fields,
        )
    )
    return final_state["trip"]


def build_trip_state(
    query: str,
    resolved_model: ResolvedModelConfig,
    interaction_mode: str = "direct",
    existing_trip_id: str | None = None,
    model_client: ModelApiClient | None = None,
) -> TripState:
    return _run_langgraph_planner(
        query=query,
        resolved_model=resolved_model,
        interaction_mode=interaction_mode,
        existing_trip_id=existing_trip_id,
        model_client=model_client,
    )
