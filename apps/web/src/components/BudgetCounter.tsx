import type { TripState } from '../lib/models';

interface BudgetCounterProps {
  trip: TripState;
}

export function BudgetCounter({ trip }: BudgetCounterProps) {
  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Basic Budget</p>
      <div className="mt-4 space-y-3 text-sm text-slate-600">
        {trip.budget_summary.transport_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Transport</span>
            <span className="font-semibold text-ink">{trip.budget_summary.transport_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.hotel_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Stay</span>
            <span className="font-semibold text-ink">{trip.budget_summary.hotel_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.ticket_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Tickets</span>
            <span className="font-semibold text-ink">{trip.budget_summary.ticket_total_estimate}</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
