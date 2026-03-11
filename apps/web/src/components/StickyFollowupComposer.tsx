import type { InteractionMode, ModelId, ModelInfo } from '../lib/models';
import { ModeSelector } from './ModeSelector';
import { ModelSelector } from './ModelSelector';
import { QueryComposer } from './QueryComposer';

interface StickyFollowupComposerProps {
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

export function StickyFollowupComposer(props: StickyFollowupComposerProps) {
  const { query, selectedModelId, interactionMode, models, loading, onQueryChange, onModelChange, onModeChange, onSubmit } = props;

  return (
    <div className="sticky top-0 z-20 border-b border-white/70 bg-[#f7f2e8]/90 px-4 py-4 backdrop-blur">
      <div className="mx-auto max-w-7xl">
        <QueryComposer
          value={query}
          onChange={onQueryChange}
          onSubmit={onSubmit}
          loading={loading}
          compact
          leftControls={
            <>
              <ModelSelector models={models} selectedModelId={selectedModelId} onChange={onModelChange} />
              <ModeSelector value={interactionMode} onChange={onModeChange} />
            </>
          }
        />
      </div>
    </div>
  );
}
