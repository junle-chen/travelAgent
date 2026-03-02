import type { TripState } from '../lib/models';

interface BudgetCounterProps {
  trip: TripState;
}

export function BudgetCounter({ trip }: BudgetCounterProps) {
  const tone = {
    on_track: 'bg-emerald-100 text-emerald-800',
    watch: 'bg-amber-100 text-amber-800',
    over: 'bg-rose-100 text-rose-800',
  }[trip.budget_summary.budget_status];

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Budget</p>
      <div className="mt-4 space-y-3 text-sm text-slate-600">
        <div className="flex items-center justify-between">
          <span>Trip total</span>
          <span className="font-semibold text-ink">{trip.budget_summary.trip_total_estimate}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Current day</span>
          <span className="font-semibold text-ink">{trip.budget_summary.current_day_estimate}</span>
        </div>
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
          {trip.budget_summary.budget_status.replace('_', ' ')}
        </span>
      </div>
    </section>
  );
}
