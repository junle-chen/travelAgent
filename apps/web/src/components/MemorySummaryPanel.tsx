import type { TripState } from '../lib/models';

interface MemorySummaryPanelProps {
  trip: TripState;
}

export function MemorySummaryPanel({ trip }: MemorySummaryPanelProps) {
  const memory = trip.memory_summary;

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Memory</p>
      <div className="mt-4 space-y-4 text-sm text-slate-600">
        <div>
          <p className="font-semibold text-ink">Route mode</p>
          <p>{memory.route_mode}</p>
        </div>
        <div>
          <p className="font-semibold text-ink">Preferences</p>
          <p>{memory.user_preferences.join(', ') || 'None yet'}</p>
        </div>
        <div>
          <p className="font-semibold text-ink">Open constraints</p>
          <p>{memory.open_constraints.join(', ') || 'None'}</p>
        </div>
        <div>
          <p className="font-semibold text-ink">Fixed anchors</p>
          <p>{memory.fixed_anchors.join(', ') || 'None'}</p>
        </div>
      </div>
    </section>
  );
}
