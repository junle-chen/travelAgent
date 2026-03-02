import type { TripState } from '../lib/models';

interface MapPreviewCardProps {
  trip: TripState;
}

export function MapPreviewCard({ trip }: MapPreviewCardProps) {
  const references = trip.map_preview.image_references ?? [];

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Route & Visuals</p>
      <p className="mt-4 text-base font-semibold text-ink">{trip.map_preview.route_label}</p>
      <p className="mt-1 text-sm text-slate-500">Transit total {trip.map_preview.total_transit_time}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {trip.map_preview.stops.length ? (
          trip.map_preview.stops.map((stop) => (
            <span key={stop} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
              {stop}
            </span>
          ))
        ) : (
          <span className="text-sm text-slate-500">Waiting for enough data to render a route preview.</span>
        )}
      </div>
      <div className="mt-5 space-y-3">
        {references.length ? (
          references.map((reference) => (
            <a
              key={`${reference.title}-${reference.image_url ?? 'none'}`}
              href={reference.source_url ?? undefined}
              target={reference.source_url ? '_blank' : undefined}
              rel={reference.source_url ? 'noreferrer' : undefined}
              className="block overflow-hidden rounded-3xl border border-slate-200 bg-slate-50"
            >
              {reference.image_url ? (
                <img src={reference.image_url} alt={reference.title} className="h-32 w-full object-cover" />
              ) : (
                <div className="flex h-32 items-center justify-center text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  No image
                </div>
              )}
              <div className="px-3 py-2 text-sm font-semibold text-ink">{reference.title}</div>
            </a>
          ))
        ) : (
          <div className="rounded-3xl border border-dashed border-slate-200 px-4 py-5 text-sm text-slate-500">
            No visual matches yet. Once the itinerary contains recognizable places, matching images will appear here.
          </div>
        )}
      </div>
    </section>
  );
}
