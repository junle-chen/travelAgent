import { KeyboardEvent } from 'react';

interface QueryComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  compact?: boolean;
}

export function QueryComposer({ value, onChange, onSubmit, loading, compact = false }: QueryComposerProps) {
  const disabled = loading || !value.trim();

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!disabled) {
        onSubmit();
      }
    }
  };

  return (
    <div
      className={`rounded-3xl border border-white/70 bg-white/90 p-4 shadow-panel backdrop-blur ${
        compact ? 'w-full' : 'w-full max-w-4xl'
      }`}
    >
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={compact ? 2 : 5}
        placeholder="Plan a 4-day Tokyo trip next month with a mid-range budget"
        className="w-full resize-none bg-transparent text-base leading-7 text-ink outline-none placeholder:text-slate-400"
      />
      <div className="mt-4 flex items-center justify-between gap-4">
        <p className="text-sm text-slate-500">Press Enter to plan, Shift + Enter for a new line.</p>
        <button
          type="button"
          onClick={onSubmit}
          disabled={disabled}
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-tide disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading ? 'Planning...' : 'Plan Trip'}
        </button>
      </div>
    </div>
  );
}
