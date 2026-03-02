import type { ProviderWarning } from '../lib/models';

interface ConflictBannerProps {
  warnings: ProviderWarning[];
}

export function ConflictBanner({ warnings }: ConflictBannerProps) {
  if (!warnings.length) {
    return null;
  }

  return (
    <div className="space-y-3">
      {warnings.map((warning, index) => (
        <div
          key={`${warning.source}-${index}`}
          className="rounded-3xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <span className="font-semibold">{warning.source}:</span> {warning.message}
        </div>
      ))}
    </div>
  );
}
