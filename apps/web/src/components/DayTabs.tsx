import type { DayPlan } from '../lib/models';

interface DayTabsProps {
  days: DayPlan[];
  activeDay: number;
  onChange: (dayIndex: number) => void;
}

export function DayTabs({ days, activeDay, onChange }: DayTabsProps) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {days.map((day) => (
        <button
          key={day.day_index}
          type="button"
          onClick={() => onChange(day.day_index)}
          className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition ${
            day.day_index === activeDay
              ? 'bg-ink text-white'
              : 'bg-white/80 text-slate-600 hover:bg-white'
          }`}
        >
          {day.title} · {day.theme}
        </button>
      ))}
    </div>
  );
}
