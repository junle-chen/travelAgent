import { useEffect, useState } from 'react';

import type { TimelineEvent } from '../lib/models';

interface TimelineEventCardProps {
  event: TimelineEvent;
}

const FALLBACK_SCENIC_IMAGE =
  'https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1200&q=80';
const FALLBACK_FOOD_IMAGE =
  'https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=1200&q=80';

function inferFallbackImage(event: TimelineEvent): string {
  const text = `${event.title} ${event.location}`.toLowerCase();
  const isFood = ['restaurant', 'food', 'cafe', 'menu', '餐', '美食', '小吃', '夜市'].some((token) => text.includes(token));
  return isFood ? FALLBACK_FOOD_IMAGE : FALLBACK_SCENIC_IMAGE;
}

export function TimelineEventCard({ event }: TimelineEventCardProps) {
  const fallbackImage = inferFallbackImage(event);
  const [imageSrc, setImageSrc] = useState(event.image_url || '');
  const [didFallback, setDidFallback] = useState(false);
  const hasImage = Boolean(imageSrc);
  const useChinese = /[\u4e00-\u9fff]/.test(`${event.title}${event.location}${event.description}`);
  const transitLabel = useChinese ? '交通' : 'Transit';

  useEffect(() => {
    setImageSrc(event.image_url || '');
    setDidFallback(false);
  }, [event.id, event.image_url]);

  return (
    <article className="grid gap-4 rounded-[1.75rem] border border-white/70 bg-white/90 p-4 shadow-sm sm:grid-cols-[8rem_1fr]">
      <div>
        <p className="text-sm font-semibold text-lagoon">{event.start_time} - {event.end_time}</p>
        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-400">{transitLabel} {event.travel_time_from_previous}</p>
      </div>
      <div className={`grid gap-4 ${hasImage ? 'md:grid-cols-[8rem_1fr]' : ''}`}>
        {hasImage ? (
          <div className="overflow-hidden rounded-3xl bg-slate-200">
            <img
              src={imageSrc}
              alt={event.title}
              className="h-28 w-full object-cover"
              onError={() => {
                if (!didFallback) {
                  setDidFallback(true);
                  setImageSrc(fallbackImage);
                  return;
                }
                setImageSrc('');
              }}
            />
          </div>
        ) : null}
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-lg font-semibold text-ink">{event.title}</h4>
            {event.cost_estimate ? (
              <span className="rounded-full bg-sand px-2.5 py-1 text-xs font-semibold text-tide">{event.cost_estimate}</span>
            ) : null}
            {event.risk_flags.map((flag) => (
              <span key={flag} className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
                {flag}
              </span>
            ))}
          </div>
          <p className="mt-1 text-sm font-medium text-slate-500">{event.location}</p>
          <p className="mt-3 text-sm leading-6 text-slate-600">{event.description}</p>
        </div>
      </div>
    </article>
  );
}
