import { motion } from 'framer-motion';

import type { DayPlan } from '../lib/models';
import { DayRouteMap } from './DayRouteMap';
import { TimelineEventCard } from './TimelineEventCard';

interface TimelineProps {
  day: DayPlan;
}

export function Timeline({ day }: TimelineProps) {
  return (
    <motion.section
      key={day.day_index}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      className="space-y-4"
    >
      {day.events.map((event) => (
        <div key={event.id} className="grid gap-3 sm:grid-cols-[5rem_1fr]">
          <div className="pt-4 text-sm font-semibold text-slate-400">{event.start_time}</div>
          <TimelineEventCard event={event} />
        </div>
      ))}
      <DayRouteMap day={day} />
    </motion.section>
  );
}
