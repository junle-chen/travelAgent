import { useMemo, useState } from 'react';

import type { ClarificationQuestion } from '../lib/models';

interface ClarificationPanelProps {
  questions: ClarificationQuestion[];
  loading: boolean;
  onSubmit: (message: string) => void;
}

export function ClarificationPanel({ questions, loading, onSubmit }: ClarificationPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const disabled = useMemo(() => questions.some((question) => !answers[question.id]?.trim()), [answers, questions]);

  const submit = () => {
    const message = questions
      .map((question) => `${question.label}: ${answers[question.id] ?? ''}`)
      .join('\n');
    onSubmit(message);
  };

  return (
    <section className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel backdrop-blur">
      <div className="mb-5">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-lagoon">Need a bit more signal</p>
        <h2 className="mt-2 font-display text-3xl text-ink">Answer these and I’ll build the itinerary</h2>
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
                  onClick={() => setAnswers((current) => ({ ...current, [question.id]: suggestion }))}
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
              onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))}
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
