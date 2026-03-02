import type { TimelineEvent } from '../lib/models';

interface TimelineEventCardProps {
  event: TimelineEvent;
}

export function TimelineEventCard({ event }: TimelineEventCardProps) {
  return (
    <article className="grid gap-4 rounded-[1.75rem] border border-white/70 bg-white/90 p-4 shadow-sm sm:grid-cols-[8rem_1fr]">
      <div>
        <p className="text-sm font-semibold text-lagoon">{event.start_time} - {event.end_time}</p>
        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-400">Transit {event.travel_time_from_previous}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-[8rem_1fr]">
        <div className="overflow-hidden rounded-3xl bg-slate-200">
          {event.image_url ? (
            <img src={event.image_url} alt={event.title} className="h-28 w-full object-cover" />
          ) : (
            <div className="flex h-28 items-center justify-center text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
              No image
            </div>
          )}
        </div>
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
