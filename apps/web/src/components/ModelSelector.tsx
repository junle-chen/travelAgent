import type { ModelId, ModelInfo } from '../lib/models';

interface ModelSelectorProps {
  models: ModelInfo[];
  selectedModelId: ModelId;
  onChange: (value: ModelId) => void;
}

const STATUS_LABELS: Record<string, string> = {
  true: 'Ready',
  false: 'Env Missing',
};

export function ModelSelector({ models, selectedModelId, onChange }: ModelSelectorProps) {
  const current = models.find((model) => model.model_id === selectedModelId);

  return (
    <div className="flex items-center gap-3 rounded-full border border-white/70 bg-white/80 px-4 py-2 shadow-sm backdrop-blur">
      <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Model</span>
      <select
        className="min-w-[12rem] bg-transparent text-sm font-medium text-ink outline-none"
        value={selectedModelId}
        onChange={(event) => onChange(event.target.value as ModelId)}
      >
        {models.map((model) => (
          <option key={model.model_id} value={model.model_id}>
            {model.label}
          </option>
        ))}
      </select>
      <span
        className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
          current?.env_configured
            ? 'bg-emerald-100 text-emerald-700'
            : 'bg-amber-100 text-amber-700'
        }`}
      >
        {STATUS_LABELS[String(Boolean(current?.env_configured))]}
      </span>
    </div>
  );
}
