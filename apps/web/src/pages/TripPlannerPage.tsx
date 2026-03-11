import { useEffect, useMemo, useState } from 'react';

import { createTrip, fetchModels, fetchTrip, fetchTrips, postTripMessage } from '../lib/api';
import type { InteractionMode, ModelId, ModelInfo, TripState, TripSummary, ViewState } from '../lib/models';
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

const PLANNER_STATE_STORAGE_KEY = 'travel-agent-planner-state-v1';

interface PersistedPlannerState {
  selectedModelId: ModelId;
  interactionMode: InteractionMode;
  query: string;
  trip: TripState | null;
  viewState: ViewState;
  selectedTripId: string | null;
}

function loadPersistedPlannerState(): PersistedPlannerState | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(PLANNER_STATE_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as PersistedPlannerState;
  } catch {
    return null;
  }
}

function persistPlannerState(state: PersistedPlannerState) {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(PLANNER_STATE_STORAGE_KEY, JSON.stringify(state));
}

export function TripPlannerPage() {
  const [persistedState] = useState<PersistedPlannerState | null>(() => loadPersistedPlannerState());
  const [models, setModels] = useState<ModelInfo[]>(FALLBACK_MODELS);
  const [selectedModelId, setSelectedModelId] = useState<ModelId>(persistedState?.selectedModelId ?? 'gpt-5.1-chat');
  const [interactionMode, setInteractionMode] = useState<InteractionMode>(persistedState?.interactionMode ?? 'direct');
  const [query, setQuery] = useState(persistedState?.query ?? '');
  const [trip, setTrip] = useState<TripState | null>(persistedState?.trip ?? null);
  const [selectedTripId, setSelectedTripId] = useState<string | null>(persistedState?.selectedTripId ?? persistedState?.trip?.trip_id ?? null);
  const [historyTrips, setHistoryTrips] = useState<TripSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<ViewState>(persistedState?.viewState ?? 'idle');

  const refreshTripHistory = async () => {
    setHistoryLoading(true);
    try {
      const response = await fetchTrips(80);
      setHistoryTrips(response.trips);
    } catch {
      setHistoryTrips([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetchModels();
        setModels(response.models);
        setSelectedModelId((previous) =>
          response.models.some((model) => model.model_id === previous) ? previous : response.default_model_id,
        );
      } catch {
        setModels(FALLBACK_MODELS);
      }
    })();
  }, []);

  useEffect(() => {
    void refreshTripHistory();
  }, []);

  const modelConfig = useMemo(
    () => ({ model_id: selectedModelId, api_key: null, base_url: null }),
    [selectedModelId],
  );

  useEffect(() => {
    persistPlannerState({ selectedModelId, interactionMode, query, trip, viewState, selectedTripId });
  }, [interactionMode, query, selectedModelId, selectedTripId, trip, viewState]);

  const submitNewTrip = async () => {
    if (!query.trim()) {
      return;
    }
    const submittedQuery = query.trim();
    setLoading(true);
    setError(null);
    setViewState('submitting');
    try {
      const response = await createTrip(submittedQuery, modelConfig, interactionMode);
      setTrip(response.trip);
      setSelectedTripId(response.trip.trip_id);
      setViewState(response.trip.view_state);
      await refreshTripHistory();
      if (response.trip.view_state === 'itinerary_ready' || response.trip.view_state === 'partial_itinerary_with_warnings') {
        setQuery('');
      } else {
        setQuery(submittedQuery);
      }
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
    setViewState('submitting');
    try {
      const response = await postTripMessage(trip.trip_id, nextMessage, modelConfig, interactionMode);
      setTrip(response.trip);
      setSelectedTripId(response.trip.trip_id);
      setViewState(response.trip.view_state);
      await refreshTripHistory();
      if (response.trip.view_state === 'itinerary_ready' || response.trip.view_state === 'partial_itinerary_with_warnings') {
        setQuery('');
      } else {
        setQuery(nextMessage);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to update trip');
      setViewState('error_recoverable');
    } finally {
      setLoading(false);
    }
  };

  const startNewChat = () => {
    setTrip(null);
    setSelectedTripId(null);
    setQuery('');
    setError(null);
    setViewState('idle');
  };

  const openTripFromHistory = async (tripId: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchTrip(tripId);
      setTrip(response.trip);
      setSelectedTripId(response.trip.trip_id);
      setViewState(response.trip.view_state);
      setQuery('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load trip');
    } finally {
      setLoading(false);
    }
  };

  const showHero =
    !trip ||
    viewState === 'idle' ||
    viewState === 'needs_clarification' ||
    viewState === 'error_recoverable';

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#fef7eb_0%,#f7f2e8_45%,#edf6f4_100%)] text-ink">
      <div className="mx-auto flex max-w-[1600px]">
        <aside className="hidden h-screen w-80 shrink-0 flex-col border-r border-slate-200 bg-white/80 lg:flex">
          <div className="border-b border-slate-200 p-4">
            <button
              type="button"
              onClick={startNewChat}
              className="inline-flex w-full items-center justify-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-ink shadow-sm transition hover:bg-slate-50"
            >
              <span className="text-base leading-none">+</span>
              <span>新建对话</span>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {historyLoading ? <p className="px-2 py-2 text-sm text-slate-500">加载历史中...</p> : null}
            {!historyLoading && !historyTrips.length ? <p className="px-2 py-2 text-sm text-slate-500">暂无历史行程</p> : null}
            <div className="space-y-2">
              {historyTrips.map((item) => (
                <button
                  key={item.trip_id}
                  type="button"
                  onClick={() => void openTripFromHistory(item.trip_id)}
                  className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                    selectedTripId === item.trip_id
                      ? 'border-lagoon bg-lagoon/10'
                      : 'border-slate-200 bg-white/90 hover:border-slate-300 hover:bg-white'
                  }`}
                >
                  <p className="line-clamp-2 text-sm font-semibold text-ink">{item.query || item.headline || '未命名行程'}</p>
                  <p className="mt-1 line-clamp-1 text-xs text-slate-500">{item.destination}</p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {new Date(item.updated_at).toLocaleString('zh-CN', {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 p-3 backdrop-blur lg:hidden">
            <button
              type="button"
              onClick={startNewChat}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-ink shadow-sm"
            >
              <span className="text-base leading-none">+</span>
              <span>新建对话</span>
            </button>
          </div>

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
        </div>
      </div>
    </main>
  );
}
