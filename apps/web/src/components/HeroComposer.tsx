import type { InteractionMode, ModelId, ModelInfo } from '../lib/models';
import { ModeSelector } from './ModeSelector';
import { ModelSelector } from './ModelSelector';
import { QueryComposer } from './QueryComposer';

interface HeroComposerProps {
  query: string;
  selectedModelId: ModelId;
  interactionMode: InteractionMode;
  models: ModelInfo[];
  loading: boolean;
  onQueryChange: (value: string) => void;
  onModelChange: (value: ModelId) => void;
  onModeChange: (value: InteractionMode) => void;
  onSubmit: () => void;
}

export function HeroComposer(props: HeroComposerProps) {
  const { query, selectedModelId, interactionMode, models, loading, onQueryChange, onModelChange, onModeChange, onSubmit } = props;

  return (
    <section className="flex min-h-[52vh] flex-col items-center justify-center px-6 py-12">
      <div className="mb-8 text-center">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-lagoon">Clarification-first travel planning</p>
        <h1 className="mt-4 font-display text-5xl text-ink sm:text-6xl">Plan your next trip</h1>
        <p className="mx-auto mt-4 max-w-3xl text-lg leading-8 text-slate-600">
          Direct mode returns a fast draft immediately. Planning mode asks for a full brief first, then builds a more grounded itinerary.
        </p>
      </div>
      <div className="mb-5 w-full max-w-6xl">
        <QueryComposer
          value={query}
          onChange={onQueryChange}
          onSubmit={onSubmit}
          loading={loading}
          interactionMode={interactionMode}
          leftControls={
            <>
              <ModelSelector models={models} selectedModelId={selectedModelId} onChange={onModelChange} />
              <ModeSelector value={interactionMode} onChange={onModeChange} />
            </>
          }
        />
      </div>
    </section>
  );
}
