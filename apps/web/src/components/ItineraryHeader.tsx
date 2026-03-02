import type { TripState } from '../lib/models';

interface ItineraryHeaderProps {
  trip: TripState;
}

export function ItineraryHeader({ trip }: ItineraryHeaderProps) {
  return (
    <section className="rounded-[2rem] bg-gradient-to-br from-tide to-lagoon p-6 text-white shadow-panel">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-white/80">Trip Workspace</p>
          <h2 className="mt-2 font-display text-4xl">{trip.plan_summary.headline}</h2>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-white/85">{trip.plan_summary.body}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm font-medium">
          <span className="rounded-full bg-white/15 px-3 py-1.5">{trip.selected_model_id}</span>
          <span className="rounded-full bg-white/15 px-3 py-1.5">Config: {trip.model_source}</span>
          <span className="rounded-full bg-white/15 px-3 py-1.5">Updated {new Date(trip.updated_at).toLocaleString()}</span>
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
