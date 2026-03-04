import type { TripState } from '../lib/models';

interface TravelSearchPanelProps {
  trip: TripState;
}

function normalizeLabel(label: string) {
  return label.toLowerCase();
}

export function TravelSearchPanel({ trip }: TravelSearchPanelProps) {
  const links = trip.reference_links.filter((link) => {
    const label = normalizeLabel(link.label);
    return (
      label.includes('flight') ||
      label.includes('rail') ||
      label.includes('hotel') ||
      label.includes('poi') ||
      label.includes('food')
    );
  });

  if (!links.length) {
    return null;
  }

  const groups = [
    {
      title: 'Transport Searches',
      labels: ['flight', 'rail'],
    },
    {
      title: 'Stay Searches',
      labels: ['hotel'],
    },
    {
      title: 'Place Searches',
      labels: ['poi', 'food'],
    },
  ] as const;

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Live Search Results</p>
      <div className="mt-4 space-y-4">
        {groups.map((group) => {
          const groupLinks = links.filter((link) => group.labels.some((token) => normalizeLabel(link.label).includes(token)));
          if (!groupLinks.length) {
            return null;
          }
          return (
            <div key={group.title}>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{group.title}</p>
              <div className="mt-2 space-y-2">
                {groupLinks.map((link) => (
                  <a
                    key={`${group.title}-${link.url}`}
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 transition hover:border-lagoon"
                  >
                    <p className="text-sm font-semibold text-ink">{link.title}</p>
                    <p className="mt-1 text-xs font-semibold uppercase tracking-[0.16em] text-lagoon">{link.label}</p>
                  </a>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
