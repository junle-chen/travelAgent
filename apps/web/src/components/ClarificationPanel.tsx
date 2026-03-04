import { useMemo, useState } from 'react';

import type { ClarificationQuestion, InteractionMode } from '../lib/models';

interface ClarificationPanelProps {
  questions: ClarificationQuestion[];
  loading: boolean;
  interactionMode: InteractionMode;
  onSubmit: (message: string) => void;
}

const PREFERENCE_PRESETS = ['Relaxed', 'Food focused', 'Family friendly', 'Packed'];

export function ClarificationPanel({ questions, loading, interactionMode, onSubmit }: ClarificationPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({
    travelers: '2',
    budget: '1500',
    style: 'Relaxed',
  });

  const requiredIds = useMemo(() => questions.map((question) => question.id), [questions]);
  const disabled = useMemo(
    () => requiredIds.some((id) => !answers[id]?.toString().trim()),
    [answers, requiredIds],
  );

  const updateAnswer = (id: string, value: string) => {
    setAnswers((current) => ({ ...current, [id]: value }));
  };

  const submit = () => {
    const message = questions
      .map((question) => `${question.label}: ${answers[question.id] ?? ''}`)
      .join('\n');
    onSubmit(message);
  };

  if (interactionMode === 'planning') {
    const has = (id: string) => requiredIds.includes(id);
    const travelerCount = Math.max(1, Number(answers.travelers || '2'));
    const budgetValue = Math.max(100, Number(answers.budget || '1500'));

    return (
      <section className="rounded-[2rem] border border-white/70 bg-white/92 p-6 shadow-panel backdrop-blur">
        <div className="mb-6">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-lagoon">Planning Brief</p>
          <h2 className="mt-2 font-display text-3xl text-ink">Fill the trip details, then generate the route</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {has('origin') ? (
            <div className="rounded-3xl border border-slate-200 p-4">
              <p className="text-sm font-semibold text-slate-500">Start</p>
              <input
                value={answers.origin ?? ''}
                onChange={(event) => updateAnswer('origin', event.target.value)}
                placeholder="e.g. Shenzhen"
                className="mt-3 w-full rounded-2xl border border-slate-200 px-3 py-3 text-sm text-ink outline-none focus:border-lagoon"
              />
            </div>
          ) : null}

          {has('destination') ? (
            <div className="rounded-3xl border border-slate-200 p-4">
              <p className="text-sm font-semibold text-slate-500">Destination</p>
              <input
                value={answers.destination ?? ''}
                onChange={(event) => updateAnswer('destination', event.target.value)}
                placeholder="e.g. Hong Kong"
                className="mt-3 w-full rounded-2xl border border-slate-200 px-3 py-3 text-sm text-ink outline-none focus:border-lagoon"
              />
            </div>
          ) : null}

          {has('travelers') ? (
            <div className="rounded-3xl border border-slate-200 p-4">
              <p className="text-sm font-semibold text-slate-500">Travelers</p>
              <div className="mt-3 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => updateAnswer('travelers', String(Math.max(1, travelerCount - 1)))}
                  className="h-10 w-10 rounded-full bg-slate-100 text-lg font-semibold text-ink"
                >
                  -
                </button>
                <div className="min-w-20 rounded-2xl bg-slate-50 px-4 py-3 text-center text-lg font-semibold text-ink">
                  {travelerCount}
                </div>
                <button
                  type="button"
                  onClick={() => updateAnswer('travelers', String(Math.min(12, travelerCount + 1)))}
                  className="h-10 w-10 rounded-full bg-slate-100 text-lg font-semibold text-ink"
                >
                  +
                </button>
              </div>
            </div>
          ) : null}

          {has('budget') ? (
            <div className="rounded-3xl border border-slate-200 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-500">Budget</p>
                <span className="text-sm font-semibold text-ink">${budgetValue}</span>
              </div>
              <input
                type="range"
                min="100"
                max="10000"
                step="100"
                value={budgetValue}
                onChange={(event) => updateAnswer('budget', event.target.value)}
                className="mt-4 w-full accent-[#0f766e]"
              />
              <input
                type="number"
                min="100"
                step="100"
                value={budgetValue}
                onChange={(event) => updateAnswer('budget', event.target.value)}
                className="mt-3 w-full rounded-2xl border border-slate-200 px-3 py-3 text-sm text-ink outline-none focus:border-lagoon"
              />
            </div>
          ) : null}
        </div>

        {has('style') ? (
          <div className="mt-4 rounded-3xl border border-slate-200 p-4">
            <p className="text-sm font-semibold text-slate-500">Preference</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {PREFERENCE_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => updateAnswer('style', preset)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
                    answers.style === preset ? 'bg-lagoon text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {preset}
                </button>
              ))}
            </div>
            <input
              value={answers.style ?? ''}
              onChange={(event) => updateAnswer('style', event.target.value)}
              placeholder="Or type a custom preference"
              className="mt-3 w-full rounded-2xl border border-slate-200 px-3 py-3 text-sm text-ink outline-none focus:border-lagoon"
            />
          </div>
        ) : null}

        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={submit}
            disabled={loading || disabled}
            className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white transition hover:bg-tide disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loading ? 'Planning...' : 'Generate Plan'}
          </button>
        </div>
      </section>
    );
  }

  const title = 'Answer these and I’ll build the itinerary';
  const subtitle = 'Need a bit more signal';

  return (
    <section className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel backdrop-blur">
      <div className="mb-5">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-lagoon">{subtitle}</p>
        <h2 className="mt-2 font-display text-3xl text-ink">{title}</h2>
      </div>
      <div className="space-y-4">
        {questions.map((question) => (
          <div key={question.id} className="rounded-3xl border border-slate-200 p-4">
            <p className="text-sm font-semibold text-slate-500">{question.label}</p>
            <p className="mt-1 text-base font-medium text-ink">{question.question}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {question.suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => updateAnswer(question.id, suggestion)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
                    answers[question.id] === suggestion
                      ? 'bg-lagoon text-white'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {suggestion}
                </button>
              ))}
            </div>
            <input
              value={answers[question.id] ?? ''}
              onChange={(event) => updateAnswer(question.id, event.target.value)}
              placeholder="Or type your answer"
              className="mt-3 w-full rounded-2xl border border-slate-200 px-3 py-2 text-sm text-ink outline-none focus:border-lagoon"
            />
          </div>
        ))}
      </div>
      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={loading || disabled}
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-tide disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading ? 'Planning...' : 'Continue Planning'}
        </button>
      </div>
    </section>
  );
}
