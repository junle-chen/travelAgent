import { useMemo, useState } from 'react';

import type { TripState } from '../lib/models';
import { BudgetCounter } from './BudgetCounter';
import { ConflictBanner } from './ConflictBanner';
import { DayRouteMap } from './DayRouteMap';
import { DayTabs } from './DayTabs';
import { ItineraryHeader } from './ItineraryHeader';
import { MapPreviewCard } from './MapPreviewCard';
import { MemorySummaryPanel } from './MemorySummaryPanel';
import { ReferenceLinksPanel } from './ReferenceLinksPanel';
import { Timeline } from './Timeline';
import { TravelLogisticsCard } from './TravelLogisticsCard';
import { TravelSearchPanel } from './TravelSearchPanel';

interface ItineraryWorkspaceProps {
  trip: TripState;
}

export function ItineraryWorkspace({ trip }: ItineraryWorkspaceProps) {
  const [activeDay, setActiveDay] = useState(0);
  const day = useMemo(() => trip.timeline_days[activeDay] ?? trip.timeline_days[0], [activeDay, trip.timeline_days]);

  if (!day) {
    return null;
  }

  const warnings = [...trip.provider_warnings, ...trip.conflict_warnings];

  return (
    <div className="space-y-6">
      <ItineraryHeader trip={trip} />
      <ConflictBanner warnings={warnings} />
      <TravelLogisticsCard trip={trip} />
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="space-y-4 overflow-hidden">
          <DayTabs days={trip.timeline_days} activeDay={day.day_index} onChange={setActiveDay} />
          <Timeline day={day} />
          <DayRouteMap days={trip.timeline_days} destination={trip.travel_logistics.destination} />
          <ReferenceLinksPanel trip={trip} />
        </div>
        <div className="space-y-4">
          <BudgetCounter trip={trip} />
          <MemorySummaryPanel trip={trip} />
          <TravelSearchPanel trip={trip} />
          <MapPreviewCard trip={trip} />
        </div>
      </div>
    </div>
  );
}
