import type { TripState } from '../lib/models';

interface ItineraryHeaderProps {
  trip: TripState;
}

export function ItineraryHeader({ trip }: ItineraryHeaderProps) {
  return (
    <section className="rounded-[2rem] bg-[linear-gradient(135deg,rgba(14,116,144,0.98),rgba(13,148,136,0.96))] p-6 text-white shadow-panel">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-white/70">Travel Plan</p>
          <h2 className="mt-3 max-w-5xl font-display text-4xl leading-tight sm:text-5xl">{trip.plan_summary.headline}</h2>
          <p className="mt-4 max-w-3xl text-base leading-8 text-white/85">{trip.plan_summary.body}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm font-medium">
          <span className="rounded-full bg-white/15 px-3 py-1.5">{trip.selected_model_id}</span>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        {trip.plan_summary.highlights.map((highlight) => (
          <span key={highlight} className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em]">
            {highlight}
          </span>
        ))}
      </div>
    </section>
  );
}
