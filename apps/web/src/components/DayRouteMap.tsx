import { useEffect, useMemo, useRef, useState } from 'react';

import type { DayPlan } from '../lib/models';

interface DayRouteMapProps {
    day: DayPlan;
}

function isRouteEvent(title: string) {
    const lowered = title.toLowerCase();
    return !['flight', 'train', 'transfer', 'arrival', 'return', 'ferry'].some((token) => lowered.includes(token));
}

function normalizePoints(points: DayPlan['route_points']) {
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
            };
            Marker: new (options: Record<string, unknown>) => {
                on?: (eventName: string, handler: () => void) => void;
                getPosition?: () => unknown;
            };
            Polyline: new (options: Record<string, unknown>) => unknown;
            InfoWindow: new (options: Record<string, unknown>) => {
                open?: (map: unknown, position: unknown) => void;
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
    } else if (securityJsCode && securityJsCode === key) {
        console.warn('[DayRouteMap] Ignoring VITE_AMAP_SECURITY_JS_CODE because it matches the AMap key; use the dedicated JS security code instead.');
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
        script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.Scale,AMap.ToolBar`;
        script.async = true;
        script.dataset.amapSdk = 'true';
        script.onload = () => {
            if (window.AMap) {
                resolve(window.AMap);
            } else {
                console.warn('[DayRouteMap] Amap SDK script loaded but window.AMap is undefined');
                reject(new Error('Amap SDK loaded but not available'));
            }
        };
        script.onerror = () => {
            console.warn('[DayRouteMap] Failed to load Amap SDK script');
            amapLoaderPromise = null;
            reject(new Error('Failed to load Amap SDK'));
        };
        document.head.appendChild(script);
    });
    return amapLoaderPromise;
}

export function DayRouteMap({ day }: DayRouteMapProps) {
    const [activeIndex, setActiveIndex] = useState(0);
    const [useFallbackMap, setUseFallbackMap] = useState(false);
    const containerRef = useRef<HTMLDivElement | null>(null);
    const points = useMemo(() => normalizePoints(day.route_points ?? []), [day.route_points]);
    const stopMarkers = useMemo(
        () =>
            day.events
                .filter((event) => isRouteEvent(event.title) && typeof event.latitude === 'number' && typeof event.longitude === 'number')
                .map((event, index) => ({
                    index,
                    title: event.title,
                    location: event.location,
                    startTime: event.start_time,
                    endTime: event.end_time,
                    latitude: event.latitude as number,
                    longitude: event.longitude as number,
                })),
        [day.events],
    );
    const markerPoints = points.filter((point, index) => index === 0 || point.label !== points[index - 1].label).slice(0, 10);
    const polyline = points.map((point) => `${point.x},${point.y}`).join(' ');

    useEffect(() => {
        if (!stopMarkers.length && !points.length) {
            return undefined;
        }
        let disposed = false;
        let mapInstance: { destroy?: () => void; setFitView?: (items?: unknown[], immediately?: boolean, avoid?: number[]) => void; add?: (items: unknown[]) => void } | null = null;
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

                const validStopMarkers = stopMarkers.filter(
                    (p) => p.latitude !== 0 && p.longitude !== 0 && Math.abs(p.latitude) > 1 && Math.abs(p.longitude) > 1,
                );

                // Determine center from stop markers or route points
                const centerPoint = validStopMarkers[0] ?? points[0];
                if (!centerPoint) {
                    return;
                }

                mapInstance = new AMap.Map(mapContainer, {
                    zoom: 12,
                    center: [centerPoint.longitude, centerPoint.latitude],
                    resizeEnable: true,
                    viewMode: '2D',
                    zoomEnable: true,
                    dragEnable: true,
                    mapStyle: 'amap://styles/normal',
                    showLabel: true,
                });
                const overlays: unknown[] = [];

                // Draw polyline through stop markers (scenic spots in chronological order)
                if (validStopMarkers.length >= 2) {
                    overlays.push(
                        new AMap.Polyline({
                            path: validStopMarkers.map((p) => [p.longitude, p.latitude]),
                            strokeColor: '#0f766e',
                            strokeWeight: 4,
                            strokeOpacity: 0.85,
                            showDir: true,
                            lineJoin: 'round',
                            lineCap: 'round',
                            isOutline: true,
                            outlineColor: '#fff',
                            borderWeight: 2,
                        }),
                    );
                }

                // Add numbered markers for each scenic stop
                validStopMarkers.forEach((point, index) => {
                    const marker = new AMap.Marker({
                        position: [point.longitude, point.latitude],
                        title: point.title,
                        content: `<div style="width:28px;height:28px;border-radius:999px;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:center;font:600 12px sans-serif;box-shadow:0 4px 10px rgba(15,23,42,0.18)">${index + 1}</div>`,
                        offset: new AMap.Pixel(-14, -14),
                    });
                    marker.on?.('click', () => {
                        const infoNode = document.createElement('div');
                        infoNode.className = 'rounded-2xl bg-white px-3 py-2 text-sm text-slate-700 shadow-lg';
                        infoNode.innerHTML = `<div style="font-weight:700;color:#0f172a;margin-bottom:4px;">${index + 1}. ${point.title}</div><div>${point.location}</div><div style="margin-top:4px;color:#64748b;">${point.startTime} - ${point.endTime}</div>`;
                        const popup = new AMap.InfoWindow({
                            isCustom: true,
                            content: infoNode,
                            offset: new AMap.Pixel(0, -24),
                        });
                        popup.open?.(mapInstance, marker.getPosition?.() ?? [point.longitude, point.latitude]);
                    });
                    overlays.push(marker);
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
    }, [points, stopMarkers]);

    if (!points.length) {
        return null;
    }

    return (
        <section className="rounded-[1.5rem] border border-white/70 bg-white/90 p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <p className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Daily Route</p>
                    <p className="mt-1 text-sm text-slate-600">Amap route points for the full day sequence.</p>
                </div>
                <a
                    href={`https://uri.amap.com/marker?position=${points[0].longitude},${points[0].latitude}`}
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
                            <polyline fill="none" stroke="#0f766e" strokeWidth="2" points={polyline} strokeLinecap="round" strokeLinejoin="round" />
                            {points.map((point) => (
                                <g key={`${point.index}-${point.label}`}>
                                    <circle
                                        cx={point.x}
                                        cy={point.y}
                                        r={activeIndex === point.index ? 2.8 : 2.1}
                                        fill={activeIndex === point.index ? '#0f172a' : '#0f766e'}
                                        onMouseEnter={() => setActiveIndex(point.index)}
                                    />
                                    {activeIndex === point.index ? (
                                        <text x={point.x + 1.8} y={point.y - 2} fontSize="3" fill="#0f172a">
                                            {point.label}
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
                {stopMarkers.slice(0, 10).map((point, idx) => (
                    <button
                        key={`${idx}-${point.title}`}
                        type="button"
                        onClick={() => setActiveIndex(idx)}
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${activeIndex === idx ? 'bg-ink text-white' : 'bg-slate-100 text-slate-600'
                            }`}
                    >
                        {idx + 1}. {point.title}
                    </button>
                ))}
            </div>
        </section>
    );
}
