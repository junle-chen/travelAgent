import { KeyboardEvent, ReactNode, useRef } from 'react';

import type { InteractionMode } from '../lib/models';

interface QueryComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  compact?: boolean;
  leftControls?: ReactNode;
  interactionMode?: InteractionMode;
}

export function QueryComposer({
  value,
  onChange,
  onSubmit,
  loading,
  compact = false,
  leftControls,
  interactionMode = 'direct',
}: QueryComposerProps) {
  const disabled = loading || !value.trim();
  const planningPromptIndex = useRef(0);
  const planningPrompts = [
    'Plan a 3-day Beijing trip from Shanghai, focus on famous landmarks and a realistic hotel budget.',
    'Plan a 2-day Shenzhen trip from Guangzhou, prioritize top attractions, one standout food stop, and efficient routing.',
    'Plan a 4-day Tokyo trip from Hong Kong, include iconic landmarks, a mid-range hotel, and practical transport.',
    'Plan a 3-day Hong Kong trip from Shenzhen for 2 people, with harbor views, local highlights, and a balanced budget.',
  ];

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Tab' && interactionMode === 'planning') {
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
        placeholder="Plan a 4-day Tokyo trip next month with a mid-range budget"
        className="min-h-[7rem] w-full resize-none bg-transparent text-lg leading-8 text-ink outline-none placeholder:text-slate-400"
      />
      <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="flex flex-wrap items-center gap-3">{leftControls}</div>
        <div className="flex items-center justify-between gap-4 md:justify-end">
          <p className="text-sm text-slate-500">
            Press Enter to plan, Shift + Enter for a new line{interactionMode === 'planning' ? ', Tab for a demo planning brief.' : '.'}
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
