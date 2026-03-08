import { useEffect, useMemo, useRef, useState } from 'react';

import type { DayPlan } from '../lib/models';

interface DayRouteMapProps {
  days: DayPlan[];
  destination: string;
}

type RouteStop = {
  index: number;
  dayIndex: number;
  title: string;
  location: string;
  startTime: string;
  endTime: string;
  travelFromPrevious: string;
  travelMode: string;
  latitude: number;
  longitude: number;
};

type LegInfo = {
  summary: string;
  detail: string;
};

type TransitPayload = {
  route?: {
    transits?: Array<{
      duration?: string;
      segments?: Array<{
        bus?: {
          buslines?: Array<{ name?: string }>;
        };
      }>;
    }>;
  };
};

const DAY_PALETTE = ['#0f766e', '#2563eb', '#d97706', '#db2777', '#7c3aed', '#0ea5e9', '#16a34a', '#dc2626'];

const CITY_ANCHORS: Record<string, [number, number]> = {
  beijing: [116.4074, 39.9042],
  shanghai: [121.4737, 31.2304],
  shenzhen: [114.0579, 22.5431],
  guangzhou: [113.2644, 23.1291],
  hangzhou: [120.1551, 30.2741],
  xiamen: [118.0894, 24.4798],
  chengdu: [104.0665, 30.5728],
  'hong kong': [114.1694, 22.3193],
  北京: [116.4074, 39.9042],
  上海: [121.4737, 31.2304],
  深圳: [114.0579, 22.5431],
  广州: [113.2644, 23.1291],
  杭州: [120.1551, 30.2741],
  厦门: [118.0894, 24.4798],
  成都: [104.0665, 30.5728],
  香港: [114.1694, 22.3193],
};

function isRouteEvent(title: string) {
  const lowered = title.toLowerCase();
  const englishTransport = ['flight', 'train', 'transfer', 'arrival', 'return', 'ferry'];
  const chineseTransport = ['出发', '到达', '抵达', '前往', '返回', '返程', '接驳', '航班', '高铁', '动车', '火车', '乘车', '中转', '机场', '车站'];
  return !englishTransport.some((token) => lowered.includes(token)) && !chineseTransport.some((token) => title.includes(token));
}

function toMinutes(value: string) {
  const [hour, minute] = value.split(':');
  const h = Number(hour);
  const m = Number(minute);
  if (Number.isNaN(h) || Number.isNaN(m)) {
    return 0;
  }
  return h * 60 + m;
}

function inferTravelMode(text: string) {
  const lowered = text.toLowerCase();
  if (['flight', 'plane', 'airport', '航班', '飞机', '机场'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '飞机';
  }
  if (['train', 'rail', 'high-speed', '火车', '高铁', '动车'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '火车';
  }
  if (['walk', 'walking', '步行'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '步行';
  }
  if (['bus', 'coach', '公交', '大巴', '巴士'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '公交';
  }
  if (['car', 'drive', 'taxi', 'ride', '租车', '自驾', '打车', '乘车'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '驾车';
  }
  if (['ferry', 'boat', '轮渡', '船'].some((token) => lowered.includes(token) || text.includes(token))) {
    return '轮渡';
  }
  return '交通';
}

function formatTravelLeg(stop: RouteStop, previous?: RouteStop) {
  if (!previous) {
    return '起点';
  }
  const detail = stop.travelFromPrevious?.trim() || '';
  if (!detail || detail === '-' || /approximate/i.test(detail)) {
    return `${stop.travelMode}：约30分钟`;
  }
  if (detail.includes('：') || detail.includes(':')) {
    return detail;
  }
  return `${stop.travelMode}：${detail}`;
}

function toMinutesFromAmapDuration(duration: unknown): number | null {
  if (duration === undefined || duration === null) {
    return null;
  }
  const raw = Number(duration);
  if (Number.isNaN(raw) || raw <= 0) {
    return null;
  }
  return Math.max(1, Math.round(raw / 60));
}

function estimateByDistanceKm(km: number): number {
  return Math.max(12, Math.round((km / 38) * 60));
}

async function fetchTransitSummary(
  key: string,
  prev: RouteStop,
  curr: RouteStop,
  cityHint: string,
): Promise<{ minutes: number | null; lineSummary: string | null }> {
  try {
    const city = encodeURIComponent(cityHint);
    const origin = `${prev.longitude},${prev.latitude}`;
    const destination = `${curr.longitude},${curr.latitude}`;
    const url =
      `https://restapi.amap.com/v3/direction/transit/integrated?key=${key}` +
      `&origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}` +
      `&city=${city}&cityd=${city}&strategy=0&nightflag=0`;
    const response = await fetch(url);
    if (!response.ok) {
      return { minutes: null, lineSummary: null };
    }
    const payload = (await response.json()) as TransitPayload;
    const transit = payload.route?.transits?.[0];
    if (!transit) {
      return { minutes: null, lineSummary: null };
    }
    const minutes = toMinutesFromAmapDuration(transit.duration);
    const lines: string[] = [];
    for (const segment of transit.segments ?? []) {
      for (const line of segment.bus?.buslines ?? []) {
        const name = (line.name ?? '').trim();
        if (!name) {
          continue;
        }
        lines.push(name.split('(')[0].trim());
      }
    }
    const uniq = [...new Set(lines)].slice(0, 3);
    return {
      minutes,
      lineSummary: uniq.length ? uniq.join(' → ') : null,
    };
  } catch {
    return { minutes: null, lineSummary: null };
  }
}

function distanceKm(a: [number, number], b: [number, number]) {
  const [lon1, lat1] = a;
  const [lon2, lat2] = b;
  const latScale = 111;
  const lonScale = 111 * Math.max(0.2, Math.abs(Math.cos((((lat1 + lat2) / 2) * Math.PI) / 180)));
  return Math.hypot((lon2 - lon1) * lonScale, (lat2 - lat1) * latScale);
}

function resolveDestinationAnchor(destination: string): [number, number] | null {
  const lowered = destination.toLowerCase().trim();
  const compact = lowered.replace(/\s+/g, '');
  for (const [key, anchor] of Object.entries(CITY_ANCHORS)) {
    const keyLower = key.toLowerCase();
    if (lowered.includes(keyLower) || compact.includes(keyLower.replace(/\s+/g, ''))) {
      return anchor;
    }
  }
  return null;
}

function detectCityKey(text: string): string | null {
  const lowered = text.toLowerCase();
  const compact = lowered.replace(/\s+/g, '');
  for (const key of Object.keys(CITY_ANCHORS)) {
    const keyLower = key.toLowerCase();
    const keyCompact = keyLower.replace(/\s+/g, '');
    if (lowered.includes(keyLower) || compact.includes(keyCompact)) {
      return keyLower;
    }
  }
  return null;
}

function normalizePoints(points: Array<{ latitude: number; longitude: number }>) {
  if (!points.length) {
    return [];
  }
  const lats = points.map((point) => point.latitude);
  const lngs = points.map((point) => point.longitude);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const latSpan = Math.max(maxLat - minLat, 0.01);
  const lngSpan = Math.max(maxLng - minLng, 0.01);

  return points.map((point, index) => ({
    ...point,
    x: ((point.longitude - minLng) / lngSpan) * 92 + 4,
    y: 56 - ((point.latitude - minLat) / latSpan) * 48,
    index,
  }));
}

declare global {
  interface Window {
    AMap?: {
      Map: new (container: HTMLElement, options: Record<string, unknown>) => {
        setFitView: (items?: unknown[]) => void;
        destroy?: () => void;
        add?: (items: unknown[]) => void;
        on?: (eventName: string, handler: () => void) => void;
        clearInfoWindow?: () => void;
      };
      Marker: new (options: Record<string, unknown>) => {
        on?: (eventName: string, handler: () => void) => void;
        getPosition?: () => unknown;
      };
      Polyline: new (options: Record<string, unknown>) => {
        on?: (eventName: string, handler: (event?: { lnglat?: unknown }) => void) => void;
      };
      Driving: new (options?: Record<string, unknown>) => {
        search: (
          origin: [number, number],
          destination: [number, number],
          callback: (status: string, result: { routes?: Array<{ time?: number; duration?: number }> }) => void,
        ) => void;
      };
      Walking: new (options?: Record<string, unknown>) => {
        search: (
          origin: [number, number],
          destination: [number, number],
          callback: (status: string, result: { routes?: Array<{ time?: number; duration?: number }> }) => void,
        ) => void;
      };
      InfoWindow: new (options: Record<string, unknown>) => {
        open?: (map: unknown, position: unknown) => void;
        close?: () => void;
      };
      Pixel: new (x: number, y: number) => unknown;
    };
    _AMapSecurityConfig?: {
      securityJsCode?: string;
    };
  }
}

let amapLoaderPromise: Promise<typeof window.AMap> | null = null;

function loadAmapSdk() {
  if (window.AMap) {
    return Promise.resolve(window.AMap);
  }
  const key = import.meta.env.VITE_AMAP_KEY;
  if (!key) {
    return Promise.reject(new Error('Missing VITE_AMAP_KEY'));
  }
  if (amapLoaderPromise) {
    return amapLoaderPromise;
  }

  const securityJsCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE;
  if (securityJsCode && securityJsCode !== key) {
    window._AMapSecurityConfig = { securityJsCode };
  }

  amapLoaderPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-amap-sdk="true"]');
    if (existing) {
      if (window.AMap) {
        resolve(window.AMap);
        return;
      }
      existing.addEventListener('load', () => resolve(window.AMap), { once: true });
      existing.addEventListener('error', () => reject(new Error('Failed to load Amap SDK')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.Scale,AMap.ToolBar,AMap.Driving,AMap.Walking`;
    script.async = true;
    script.dataset.amapSdk = 'true';
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap);
      } else {
        reject(new Error('Amap SDK loaded but not available'));
      }
    };
    script.onerror = () => {
      amapLoaderPromise = null;
      reject(new Error('Failed to load Amap SDK'));
    };
    document.head.appendChild(script);
  });
  return amapLoaderPromise;
}

export function DayRouteMap({ days, destination }: DayRouteMapProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [useFallbackMap, setUseFallbackMap] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const legInfoCacheRef = useRef<Map<string, LegInfo>>(new Map());

  const routeStops = useMemo(() => {
    const flattened: RouteStop[] = [];
    const sortedDays = [...days].sort((a, b) => a.day_index - b.day_index);
    for (const day of sortedDays) {
      const sortedEvents = [...day.events].sort((a, b) => toMinutes(a.start_time) - toMinutes(b.start_time));
      for (const event of sortedEvents) {
        if (!isRouteEvent(event.title)) {
          continue;
        }
        if (typeof event.latitude !== 'number' || typeof event.longitude !== 'number') {
          continue;
        }
        flattened.push({
          index: flattened.length,
          dayIndex: day.day_index,
          title: event.title,
          location: event.location,
          startTime: event.start_time,
          endTime: event.end_time,
          travelFromPrevious: event.travel_time_from_previous,
          travelMode: inferTravelMode(`${event.travel_time_from_previous} ${event.title} ${event.location}`),
          latitude: event.latitude,
          longitude: event.longitude,
        });
      }
    }
    return flattened;
  }, [days]);

  const filteredStops = useMemo(() => {
    if (!routeStops.length) {
      return [];
    }
    const cityKeys = new Set<string>();
    for (const stop of routeStops) {
      const key = detectCityKey(`${stop.location} ${stop.title}`);
      if (key) {
        cityKeys.add(key);
      }
    }
    const first = routeStops[0];
    const hasWideSpan = routeStops.some((stop) => distanceKm([first.longitude, first.latitude], [stop.longitude, stop.latitude]) > 120);
    const isMultiCityRoute = cityKeys.size > 1 || hasWideSpan;
    if (isMultiCityRoute) {
      return routeStops;
    }
    const anchor = resolveDestinationAnchor(destination);
    if (!anchor) {
      return routeStops;
    }
    const thresholdKm = 90;
    const kept = routeStops.filter((stop) => distanceKm(anchor, [stop.longitude, stop.latitude]) <= thresholdKm);
    return kept.length >= 2 ? kept : routeStops;
  }, [destination, routeStops]);

  const dedupedStops = useMemo(() => {
    const deduped: RouteStop[] = [];
    for (const stop of filteredStops) {
      const prev = deduped[deduped.length - 1];
      if (prev && prev.latitude === stop.latitude && prev.longitude === stop.longitude) {
        continue;
      }
      deduped.push(stop);
    }
    return deduped.map((stop, index) => ({ ...stop, index }));
  }, [filteredStops]);
  const previousSameDayByIndex = useMemo(() => {
    const byIndex = new Map<number, RouteStop | undefined>();
    const dayLastStop = new Map<number, RouteStop>();
    for (const stop of dedupedStops) {
      byIndex.set(stop.index, dayLastStop.get(stop.dayIndex));
      dayLastStop.set(stop.dayIndex, stop);
    }
    return byIndex;
  }, [dedupedStops]);

  const dayGroups = useMemo(() => {
    const groups = new Map<number, RouteStop[]>();
    for (const stop of dedupedStops) {
      const existing = groups.get(stop.dayIndex) ?? [];
      existing.push(stop);
      groups.set(stop.dayIndex, existing);
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0]);
  }, [dedupedStops]);

  const points = useMemo(
    () => normalizePoints(dedupedStops.map((stop) => ({ latitude: stop.latitude, longitude: stop.longitude }))),
    [dedupedStops],
  );
  const pointMap = useMemo(
    () => new Map(points.map((point, index) => [dedupedStops[index]?.index, point])),
    [points, dedupedStops],
  );
  const dayPolylines = useMemo(
    () =>
      dayGroups.map(([dayIndex, stops]) => {
        const mapped = stops
          .map((stop) => pointMap.get(stop.index))
          .filter((value): value is NonNullable<typeof value> => Boolean(value));
        return {
          dayIndex,
          points: mapped,
          path: mapped.map((point) => `${point.x},${point.y}`).join(' '),
        };
      }),
    [dayGroups, pointMap],
  );
  const fullPolylinePath = useMemo(
    () => points.map((point) => `${point.x},${point.y}`).join(' '),
    [points],
  );

  useEffect(() => {
    if (!dedupedStops.length) {
      return undefined;
    }
    let disposed = false;
    let mapInstance: {
      destroy?: () => void;
      setFitView?: (items?: unknown[], immediately?: boolean, avoid?: number[]) => void;
      add?: (items: unknown[]) => void;
      on?: (eventName: string, handler: () => void) => void;
      clearInfoWindow?: () => void;
    } | null = null;
    const mapContainer = containerRef.current;
    if (!mapContainer) {
      return undefined;
    }

    loadAmapSdk()
      .then((AMap) => {
        if (disposed || !AMap || !mapContainer) {
          return;
        }
        setUseFallbackMap(false);
        mapContainer.innerHTML = '';

        const centerPoint = dedupedStops[0];
        mapInstance = new AMap.Map(mapContainer, {
          zoom: 12,
          center: [centerPoint.longitude, centerPoint.latitude],
          resizeEnable: true,
          viewMode: '2D',
          mapStyle: 'amap://styles/normal',
          showLabel: true,
        });

        const overlays: unknown[] = [];
        let activeMarkerPopup: { close?: () => void } | null = null;
        let activeLegPopup: { close?: () => void } | null = null;
        let activeMarkerIndex: number | null = null;
        let activeLegIndex: number | null = null;
        const drivingService = new AMap.Driving({});
        const walkingService = new AMap.Walking({});
        const legCache = legInfoCacheRef.current;

        const queryDrivingMinutes = (prev: RouteStop, curr: RouteStop) =>
          new Promise<number | null>((resolve) => {
            drivingService.search(
              [prev.longitude, prev.latitude],
              [curr.longitude, curr.latitude],
              (status, result) => {
                if (status !== 'complete') {
                  resolve(null);
                  return;
                }
                const route = result.routes?.[0];
                resolve(toMinutesFromAmapDuration(route?.time ?? route?.duration));
              },
            );
          });

        const queryWalkingMinutes = (prev: RouteStop, curr: RouteStop) =>
          new Promise<number | null>((resolve) => {
            walkingService.search(
              [prev.longitude, prev.latitude],
              [curr.longitude, curr.latitude],
              (status, result) => {
                if (status !== 'complete') {
                  resolve(null);
                  return;
                }
                const route = result.routes?.[0];
                resolve(toMinutesFromAmapDuration(route?.time ?? route?.duration));
              },
            );
          });

        const resolveLegInfo = async (prev: RouteStop, curr: RouteStop): Promise<LegInfo> => {
          const cacheKey = `${prev.longitude},${prev.latitude}->${curr.longitude},${curr.latitude}`;
          const cached = legCache.get(cacheKey);
          if (cached) {
            return cached;
          }

          const [drivingMinutes, walkingMinutes] = await Promise.all([
            queryDrivingMinutes(prev, curr),
            queryWalkingMinutes(prev, curr),
          ]);
          const transitCity =
            detectCityKey(`${curr.location} ${curr.title}`) ??
            detectCityKey(`${prev.location} ${prev.title}`) ??
            destination;
          const amapKey = import.meta.env.VITE_AMAP_KEY;
          const transit = amapKey
            ? await fetchTransitSummary(amapKey, prev, curr, transitCity)
            : { minutes: null, lineSummary: null };
          const km = distanceKm([prev.longitude, prev.latitude], [curr.longitude, curr.latitude]);
          const driveMins = drivingMinutes ?? estimateByDistanceKm(km);
          const walkMins = walkingMinutes;

          let summary = `驾车：${driveMins}分钟`;
          if (walkMins !== null && walkMins <= 25) {
            summary = `步行：${walkMins}分钟`;
          } else if (
            transit.minutes !== null &&
            transit.minutes > 0 &&
            transit.minutes <= Math.max(driveMins * 1.35, 40)
          ) {
            summary = `公共交通：${transit.minutes}分钟`;
          }

          const detailParts: string[] = [];
          if (transit.minutes !== null) {
            const transitLine = transit.lineSummary ? `（${transit.lineSummary}）` : '';
            detailParts.push(`公交/地铁 ${transit.minutes}分钟${transitLine}`);
          }
          detailParts.push(`打车 ${driveMins}分钟`);
          if (walkMins !== null) {
            detailParts.push(`步行 ${walkMins}分钟`);
          }
          const info: LegInfo = {
            summary,
            detail: detailParts.join(' · '),
          };
          legCache.set(cacheKey, info);
          return info;
        };

        if (dedupedStops.length >= 2) {
          overlays.push(
            new AMap.Polyline({
              path: dedupedStops.map((stop) => [stop.longitude, stop.latitude]),
              strokeColor: '#0f172a',
              strokeWeight: 6,
              strokeOpacity: 0.28,
              showDir: true,
              lineJoin: 'round',
              lineCap: 'round',
            }),
          );
        }

        dayGroups.forEach(([dayIndex, stops]) => {
          if (stops.length < 2) {
            return;
          }
          const dayColor = DAY_PALETTE[dayIndex % DAY_PALETTE.length];
          overlays.push(
            new AMap.Polyline({
              path: stops.map((stop) => [stop.longitude, stop.latitude]),
              strokeColor: dayColor,
              strokeWeight: 4,
              strokeOpacity: 0.9,
              showDir: true,
              lineJoin: 'round',
              lineCap: 'round',
              isOutline: true,
              outlineColor: '#fff',
              borderWeight: 2,
            }),
          );
        });

        for (let index = 1; index < dedupedStops.length; index += 1) {
          const prev = dedupedStops[index - 1];
          const curr = dedupedStops[index];
          const dayColor = DAY_PALETTE[curr.dayIndex % DAY_PALETTE.length];
          const edge = new AMap.Polyline({
            path: [
              [prev.longitude, prev.latitude],
              [curr.longitude, curr.latitude],
            ],
            strokeColor: dayColor,
            strokeWeight: 16,
            strokeOpacity: 0.01,
            lineJoin: 'round',
            lineCap: 'round',
            zIndex: 120,
          });
          edge.on?.('click', async (event) => {
            if (activeLegIndex === index && activeLegPopup) {
              activeLegPopup.close?.();
              activeLegPopup = null;
              activeLegIndex = null;
              return;
            }
            activeMarkerPopup?.close?.();
            activeMarkerPopup = null;
            activeMarkerIndex = null;
            activeLegPopup?.close?.();
            const middleLng = (prev.longitude + curr.longitude) / 2;
            const middleLat = (prev.latitude + curr.latitude) / 2;
            const infoNode = document.createElement('div');
            infoNode.className = 'rounded-2xl bg-white px-3 py-2 text-sm text-slate-700 shadow-lg';
            infoNode.innerHTML = `<div style="font-weight:700;color:#0f172a;margin-bottom:4px;">路段 ${index}</div><div style="color:#0f766e;font-weight:600;">交通时间查询中...</div><div style="margin-top:4px;color:#64748b;">${prev.title} → ${curr.title}</div>`;
            const popup = new AMap.InfoWindow({
              isCustom: true,
              content: infoNode,
              offset: new AMap.Pixel(0, -10),
            });
            popup.open?.(mapInstance, event?.lnglat ?? [middleLng, middleLat]);
            activeLegPopup = popup;
            activeLegIndex = index;
            const info = await resolveLegInfo(prev, curr);
            if (disposed || activeLegIndex !== index) {
              return;
            }
            infoNode.innerHTML = `<div style="font-weight:700;color:#0f172a;margin-bottom:4px;">路段 ${index}</div><div style="color:#0f766e;font-weight:600;">${info.summary}</div><div style="margin-top:4px;color:#64748b;">${prev.title} → ${curr.title}</div><div style="margin-top:4px;color:#64748b;">${info.detail}</div>`;
          });
          overlays.push(edge);
        }

        dedupedStops.forEach((stop, index) => {
          const dayColor = DAY_PALETTE[stop.dayIndex % DAY_PALETTE.length];
          const marker = new AMap.Marker({
            position: [stop.longitude, stop.latitude],
            title: stop.title,
            content: `<div style="width:28px;height:28px;border-radius:999px;background:${dayColor};color:#fff;display:flex;align-items:center;justify-content:center;font:600 12px sans-serif;box-shadow:0 4px 10px rgba(15,23,42,0.22)">${index + 1}</div>`,
            offset: new AMap.Pixel(-14, -14),
          });
          marker.on?.('click', () => {
            if (activeMarkerIndex === index && activeMarkerPopup) {
              activeMarkerPopup.close?.();
              activeMarkerPopup = null;
              activeMarkerIndex = null;
              return;
            }
            activeLegPopup?.close?.();
            activeLegPopup = null;
            activeLegIndex = null;
            activeMarkerPopup?.close?.();
            const previousStop = previousSameDayByIndex.get(stop.index);
            const arrivalInfo = previousStop ? formatTravelLeg(stop, previousStop) : '当日首站';
            const infoNode = document.createElement('div');
            infoNode.className = 'rounded-2xl bg-white px-3 py-2 text-sm text-slate-700 shadow-lg';
            infoNode.innerHTML = `<div style="font-weight:700;color:#0f172a;margin-bottom:4px;">${index + 1}. ${stop.title}</div><div>${stop.location}</div><div style="margin-top:4px;color:#64748b;">Day ${stop.dayIndex + 1} · ${stop.startTime} - ${stop.endTime}</div><div style="margin-top:4px;color:#0f766e;font-weight:600;">到达方式：${arrivalInfo}</div>`;
            const popup = new AMap.InfoWindow({
              isCustom: true,
              content: infoNode,
              offset: new AMap.Pixel(0, -24),
            });
            popup.open?.(mapInstance, marker.getPosition?.() ?? [stop.longitude, stop.latitude]);
            activeMarkerPopup = popup;
            activeMarkerIndex = index;
          });
          overlays.push(marker);
        });
        mapInstance.on?.('click', () => {
          activeMarkerPopup?.close?.();
          activeLegPopup?.close?.();
          activeMarkerPopup = null;
          activeLegPopup = null;
          activeMarkerIndex = null;
          activeLegIndex = null;
        });
        mapInstance.add?.(overlays);
        window.requestAnimationFrame(() => {
          mapInstance?.setFitView?.(overlays, false, [80, 80, 80, 80]);
        });
      })
      .catch(() => {
        if (!disposed) {
          setUseFallbackMap(true);
        }
      });

    return () => {
      disposed = true;
      mapInstance?.destroy?.();
    };
  }, [dedupedStops, dayGroups, previousSameDayByIndex, destination]);

  if (!dedupedStops.length) {
    return null;
  }

  return (
    <section className="rounded-[1.5rem] border border-white/70 bg-white/90 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Trip Route</p>
          <p className="mt-1 text-sm text-slate-600">Full itinerary sequence connected by visit order.</p>
        </div>
        <a
          href={`https://uri.amap.com/marker?position=${dedupedStops[0].longitude},${dedupedStops[0].latitude}`}
          target="_blank"
          rel="noreferrer"
          className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600"
        >
          Open in Amap
        </a>
      </div>
      <div className="mt-4 overflow-hidden rounded-3xl border border-slate-200 bg-[radial-gradient(circle_at_top,_#f8fafc,_#e2e8f0)]">
        {useFallbackMap || !import.meta.env.VITE_AMAP_KEY ? (
          <div className="p-3">
            <svg viewBox="0 0 100 60" className="h-52 w-full">
              {points.length > 1 ? (
                <polyline
                  fill="none"
                  stroke="#1f2937"
                  strokeWidth="2.6"
                  points={fullPolylinePath}
                  strokeOpacity="0.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ) : null}
              {dayPolylines.map((line) => (
                <polyline
                  key={`line-${line.dayIndex}`}
                  fill="none"
                  stroke={DAY_PALETTE[line.dayIndex % DAY_PALETTE.length]}
                  strokeWidth="2"
                  points={line.path}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ))}
              {points.map((point) => (
                <g key={point.index}>
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r={activeIndex === point.index ? 2.8 : 2.1}
                    fill={
                      activeIndex === point.index
                        ? '#0f172a'
                        : DAY_PALETTE[(dedupedStops[point.index]?.dayIndex ?? 0) % DAY_PALETTE.length]
                    }
                    onMouseEnter={() => setActiveIndex(point.index)}
                  />
                  {activeIndex === point.index ? (
                    <text x={point.x + 1.8} y={point.y - 2} fontSize="3" fill="#0f172a">
                      {dedupedStops[point.index]?.title}
                    </text>
                  ) : null}
                </g>
              ))}
            </svg>
          </div>
        ) : (
          <div ref={containerRef} className="h-64 w-full" />
        )}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {dedupedStops.map((stop, idx) => (
          <button
            key={`${stop.dayIndex}-${stop.startTime}-${stop.title}-${idx}`}
            type="button"
            onClick={() => setActiveIndex(idx)}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              activeIndex === idx ? 'text-white' : 'bg-slate-100 text-slate-600'
            }`}
            style={activeIndex === idx ? { backgroundColor: DAY_PALETTE[stop.dayIndex % DAY_PALETTE.length] } : undefined}
          >
            D{stop.dayIndex + 1}-{idx + 1}. {stop.title}
          </button>
        ))}
      </div>
    </section>
  );
}
