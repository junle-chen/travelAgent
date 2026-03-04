import type { InteractionMode } from '../lib/models';

interface ModeSelectorProps {
  value: InteractionMode;
  onChange: (value: InteractionMode) => void;
}

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  return (
    <div className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 p-1">
      {(['direct', 'planning'] as const).map((mode) => (
        <button
          key={mode}
          type="button"
          onClick={() => onChange(mode)}
          className={`rounded-full px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em] transition ${
            value === mode ? 'bg-ink text-white' : 'text-slate-500 hover:text-ink'
          }`}
        >
          {mode}
        </button>
      ))}
    </div>
  );
}
