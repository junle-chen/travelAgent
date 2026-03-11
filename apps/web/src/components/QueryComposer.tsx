import { KeyboardEvent, ReactNode, useRef } from 'react';

interface QueryComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  compact?: boolean;
  leftControls?: ReactNode;
}

export function QueryComposer({
  value,
  onChange,
  onSubmit,
  loading,
  compact = false,
  leftControls,
}: QueryComposerProps) {
  const disabled = loading || !value.trim();
  const planningPromptIndex = useRef(0);
  const planningPrompts = [
    'Plan a 4-day trip to Beijing from Shanghai.',
    'Plan a 10-day trip to North Xinjiang.',
    'Plan a 6-day trip to Chengdu and Chongqing from Shenzhen.',
  ];

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Tab') {
      event.preventDefault();
      const nextPrompt = planningPrompts[planningPromptIndex.current % planningPrompts.length];
      planningPromptIndex.current += 1;
      onChange(nextPrompt);
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!disabled) {
        onSubmit();
      }
    }
  };

  return (
    <div
      className={`rounded-[2rem] border border-white/80 bg-white/92 p-5 shadow-panel backdrop-blur ${
        compact ? 'w-full' : 'w-full'
      }`}
    >
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={compact ? 3 : 7}
        placeholder="plan a 4-day trip to beijing from shanghai"
        className="min-h-[7rem] w-full resize-none bg-transparent text-lg leading-8 text-ink outline-none placeholder:text-slate-400"
      />
      <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="flex flex-wrap items-center gap-3">{leftControls}</div>
        <div className="flex w-full items-center justify-between gap-4 md:w-auto md:justify-end">
          <p className="text-xs text-slate-500 md:max-w-[20rem] md:text-right">
            Press Enter to plan, Shift + Enter for a new line, Tab for a demo planning brief.
          </p>
          <button
            type="button"
            onClick={onSubmit}
            disabled={disabled}
            className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white transition hover:bg-tide disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loading ? 'Planning...' : 'Plan Trip'}
          </button>
        </div>
      </div>
    </div>
  );
}
