import type { ModelId, ModelInfo } from '../lib/models';
import { ModelSelector } from './ModelSelector';
import { QueryComposer } from './QueryComposer';

interface HeroComposerProps {
  query: string;
  selectedModelId: ModelId;
  models: ModelInfo[];
  loading: boolean;
  onQueryChange: (value: string) => void;
  onModelChange: (value: ModelId) => void;
  onSubmit: () => void;
}

export function HeroComposer(props: HeroComposerProps) {
  const { query, selectedModelId, models, loading, onQueryChange, onModelChange, onSubmit } = props;

  return (
    <section className="flex min-h-[52vh] flex-col items-center justify-center px-6 py-12">
      <div className="mb-8 text-center">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-lagoon">Clarification-first travel planning</p>
        <h1 className="mt-4 font-display text-5xl text-ink sm:text-6xl">Plan your next trip</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-slate-600">
          Describe the trip once. The planner will ask only the high-value follow-ups it needs, then render a structured itinerary.
        </p>
      </div>
      <div className="mb-5 w-full max-w-4xl">
        <QueryComposer value={query} onChange={onQueryChange} onSubmit={onSubmit} loading={loading} />
      </div>
      <ModelSelector models={models} selectedModelId={selectedModelId} onChange={onModelChange} />
    </section>
  );
}
