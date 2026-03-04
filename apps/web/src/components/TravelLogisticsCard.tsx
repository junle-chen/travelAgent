import type { TripState } from '../lib/models';

interface TravelLogisticsCardProps {
  trip: TripState;
}

export function TravelLogisticsCard({ trip }: TravelLogisticsCardProps) {
  const logistics = trip.travel_logistics;

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Trip Logistics</p>
      <div className="mt-4 space-y-3 text-sm text-slate-600">
        <div className="flex items-center justify-between gap-3">
          <span>Route</span>
          <span className="font-semibold text-ink">{logistics.origin} → {logistics.destination}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>Travelers</span>
          <span className="font-semibold text-ink">{logistics.travelers}</span>
        </div>
        <div>
          <p className="font-semibold text-ink">Outbound</p>
          <p>{logistics.outbound_transport}</p>
          <p className="text-xs text-slate-500">{logistics.outbound_schedule}</p>
        </div>
        <div>
          <p className="font-semibold text-ink">Return</p>
          <p>{logistics.return_transport}</p>
          <p className="text-xs text-slate-500">{logistics.return_schedule}</p>
        </div>
        <div>
          <p className="font-semibold text-ink">Hotel</p>
          <p>{logistics.hotel_name}</p>
        </div>
      </div>
    </section>
  );
}
