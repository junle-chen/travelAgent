import type { TripState } from '../lib/models';

interface ReferenceLinksPanelProps {
  trip: TripState;
}

export function ReferenceLinksPanel({ trip }: ReferenceLinksPanelProps) {
  const links = trip.reference_links.filter((link) => {
    const label = link.label.toLowerCase();
    const url = link.url.toLowerCase();
    if (url.includes('example.com') || url.includes('xiaohongshu.com/search_result')) {
      return false;
    }
    return (
      label.includes('blog') ||
      label.includes('report') ||
      label.includes('forum') ||
      label.includes('攻略') ||
      label.includes('游记') ||
      label.includes('论坛')
    );
  });

  if (!links.length) {
    return null;
  }

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">More Travel References</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {links.map((link) => (
          <a
            key={`${link.title}-${link.url}`}
            href={link.url}
            target="_blank"
            rel="noreferrer"
            className="rounded-3xl border border-slate-200 bg-slate-50 px-4 py-4 transition hover:border-lagoon"
          >
            <p className="text-sm font-semibold text-ink">{link.title}</p>
            <p className="mt-2 text-xs font-semibold uppercase tracking-[0.16em] text-lagoon">{link.label}</p>
          </a>
        ))}
      </div>
    </section>
  );
}
