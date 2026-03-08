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
        {trip.budget_summary.transport_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Transport</span>
            <span className="font-semibold text-ink">{trip.budget_summary.transport_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.flight_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Flights</span>
            <span className="font-semibold text-ink">{trip.budget_summary.flight_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.rail_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Rail</span>
            <span className="font-semibold text-ink">{trip.budget_summary.rail_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.city_transport_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>City transport</span>
            <span className="font-semibold text-ink">{trip.budget_summary.city_transport_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.car_rental_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Car rental</span>
            <span className="font-semibold text-ink">{trip.budget_summary.car_rental_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.hotel_total_estimate ? (
          <div className="flex items-center justify-between">
            <span>Stay</span>
            <span className="font-semibold text-ink">{trip.budget_summary.hotel_total_estimate}</span>
          </div>
        ) : null}
        {trip.budget_summary.notes && trip.budget_summary.notes.length ? (
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
            {trip.budget_summary.notes.join(' · ')}
          </div>
        ) : null}
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
          {trip.budget_summary.budget_status.replace('_', ' ')}
        </span>
      </div>
    </section>
  );
}
