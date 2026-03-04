import { useEffect, useMemo, useState } from 'react';

import { fetchModels, createTrip, postTripMessage } from '../lib/api';
import type { InteractionMode, ModelId, ModelInfo, TripState, ViewState } from '../lib/models';
import { ClarificationPanel } from '../components/ClarificationPanel';
import { HeroComposer } from '../components/HeroComposer';
import { ItineraryWorkspace } from '../components/ItineraryWorkspace';
import { StickyFollowupComposer } from '../components/StickyFollowupComposer';

const FALLBACK_MODELS: ModelInfo[] = [
  {
    model_id: 'gpt-5.1-chat',
    label: 'GPT 5.1 Chat',
    env_configured: false,
    supports_override: true,
    provider: 'openai_compatible',
  },
  {
    model_id: 'gemini-3-flash-preview',
    label: 'Gemini 3 Flash Preview',
    env_configured: false,
    supports_override: true,
    provider: 'gemini_compatible',
  },
  {
    model_id: 'deepseek-v3.2',
    label: 'DeepSeek V3.2',
    env_configured: false,
    supports_override: true,
    provider: 'deepseek_compatible',
  },
];

export function TripPlannerPage() {
  const [models, setModels] = useState<ModelInfo[]>(FALLBACK_MODELS);
  const [selectedModelId, setSelectedModelId] = useState<ModelId>('gpt-5.1-chat');
  const [interactionMode, setInteractionMode] = useState<InteractionMode>('direct');
  const [query, setQuery] = useState('');
  const [trip, setTrip] = useState<TripState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<ViewState>('idle');

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetchModels();
        setModels(response.models);
        setSelectedModelId(response.default_model_id);
      } catch {
        setModels(FALLBACK_MODELS);
      }
    })();
  }, []);

  const modelConfig = useMemo(
    () => ({ model_id: selectedModelId, api_key: null, base_url: null }),
    [selectedModelId],
  );

  const submitNewTrip = async () => {
    if (!query.trim()) {
      return;
    }
    setLoading(true);
    setError(null);
    setViewState('submitting');
    try {
      const response = await createTrip(query.trim(), modelConfig, interactionMode);
      setTrip(response.trip);
      setViewState(response.trip.view_state);
      setQuery('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create trip');
      setViewState('error_recoverable');
    } finally {
      setLoading(false);
    }
  };

  const submitFollowup = async (message?: string) => {
    const nextMessage = (message ?? query).trim();
    if (!nextMessage) {
      return;
    }
    if (!trip) {
      await submitNewTrip();
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await postTripMessage(trip.trip_id, nextMessage, modelConfig, interactionMode);
      setTrip(response.trip);
      setViewState(response.trip.view_state);
      setQuery('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to update trip');
      setViewState('error_recoverable');
    } finally {
      setLoading(false);
    }
  };

  const showHero = !trip || viewState === 'idle';

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#fef7eb_0%,#f7f2e8_45%,#edf6f4_100%)] text-ink">
      {showHero ? (
        <HeroComposer
          query={query}
          selectedModelId={selectedModelId}
          interactionMode={interactionMode}
          models={models}
          loading={loading}
          onQueryChange={setQuery}
          onModelChange={setSelectedModelId}
          onModeChange={setInteractionMode}
          onSubmit={() => void submitNewTrip()}
        />
      ) : (
        <StickyFollowupComposer
          query={query}
          selectedModelId={selectedModelId}
          interactionMode={interactionMode}
          models={models}
          loading={loading}
          onQueryChange={setQuery}
          onModelChange={setSelectedModelId}
          onModeChange={setInteractionMode}
          onSubmit={() => void submitFollowup()}
        />
      )}

      <section className="mx-auto max-w-7xl px-4 pb-16">
        {error ? (
          <div className="mb-6 rounded-3xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        ) : null}

        {viewState === 'submitting' ? (
          <div className="rounded-[2rem] border border-white/70 bg-white/90 px-6 py-8 shadow-panel">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-lagoon">Planning...</p>
            <div className="mt-4 h-3 w-40 rounded-full bg-slate-200" />
            <div className="mt-3 h-3 w-80 rounded-full bg-slate-100" />
          </div>
        ) : null}

        {trip && viewState === 'needs_clarification' ? (
          <ClarificationPanel
            questions={trip.clarification_questions}
            loading={loading}
            interactionMode={trip.interaction_mode}
            onSubmit={(message) => void submitFollowup(message)}
          />
        ) : null}

        {trip && (viewState === 'itinerary_ready' || viewState === 'partial_itinerary_with_warnings') ? (
          <ItineraryWorkspace trip={trip} />
        ) : null}
      </section>
    </main>
  );
}
