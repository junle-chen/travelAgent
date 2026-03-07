import type { TripState } from '../lib/models';

interface ItineraryHeaderProps {
    trip: TripState;
}

export function ItineraryHeader({ trip }: ItineraryHeaderProps) {
    return (
        <section className="relative overflow-hidden rounded-[2rem] bg-[linear-gradient(135deg,#0c4a6e_0%,#0e7490_35%,#0d9488_65%,#5b21b6_100%)] p-6 text-white shadow-panel sm:p-8">
            {/* Decorative background art */}
            <svg className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]" aria-hidden="true">
                <circle cx="85%" cy="20%" r="180" fill="white" />
                <circle cx="10%" cy="80%" r="120" fill="white" />
                <circle cx="60%" cy="90%" r="80" fill="white" />
                <line x1="0" y1="50%" x2="100%" y2="30%" stroke="white" strokeWidth="1" />
                <line x1="20%" y1="0" x2="80%" y2="100%" stroke="white" strokeWidth="0.5" />
            </svg>
            <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.28em] text-white/70">Travel Plan</p>
                    <h2
                        className="mt-3 max-w-5xl font-display text-4xl leading-tight sm:text-5xl"
                        style={{ textShadow: '0 2px 12px rgba(0,0,0,0.18)' }}
                    >
                        {trip.plan_summary.headline}
                    </h2>
                    <p className="mt-4 max-w-3xl text-base leading-8 text-white/85">{trip.plan_summary.body}</p>
                </div>
            </div>
            <div className="relative z-10 mt-5 flex flex-wrap gap-2">
                {trip.plan_summary.highlights.map((highlight, index) => {
                    const icons = ['✨', '🏛️', '🍜', '🌄', '🎭', '🏖️'];
                    return (
                        <span
                            key={highlight}
                            className="rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em] backdrop-blur-sm"
                        >
                            <span className="mr-1.5">{icons[index % icons.length]}</span>
                            {highlight}
                        </span>
                    );
                })}
            </div>
        </section>
    );
}
