import type { ModelId, ModelInfo } from '../lib/models';
import { ModelSelector } from './ModelSelector';
import { QueryComposer } from './QueryComposer';

interface StickyFollowupComposerProps {
  query: string;
  selectedModelId: ModelId;
  models: ModelInfo[];
  loading: boolean;
  onQueryChange: (value: string) => void;
  onModelChange: (value: ModelId) => void;
  onSubmit: () => void;
}

export function StickyFollowupComposer(props: StickyFollowupComposerProps) {
  const { query, selectedModelId, models, loading, onQueryChange, onModelChange, onSubmit } = props;

  return (
    <div className="sticky top-0 z-20 border-b border-white/70 bg-[#f7f2e8]/90 px-4 py-4 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 lg:flex-row lg:items-end">
        <div className="flex-1">
          <QueryComposer
            value={query}
            onChange={onQueryChange}
            onSubmit={onSubmit}
            loading={loading}
            compact
          />
        </div>
        <ModelSelector models={models} selectedModelId={selectedModelId} onChange={onModelChange} />
      </div>
    </div>
  );
}
