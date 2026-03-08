export type ViewState =
  | 'idle'
  | 'submitting'
  | 'needs_clarification'
  | 'itinerary_ready'
  | 'partial_itinerary_with_warnings'
  | 'error_recoverable';

export type ModelId = 'gpt-5.1-chat' | 'gemini-3-flash-preview' | 'deepseek-v3.2';
export type InteractionMode = 'direct' | 'planning';

export interface ModelInfo {
  model_id: ModelId;
  label: string;
  env_configured: boolean;
  supports_override: boolean;
  provider: string;
}

export interface ModelsResponse {
  models: ModelInfo[];
  default_model_id: ModelId;
  mock_model_fallback_enabled: boolean;
}

export interface ClarificationQuestion {
  id: string;
  label: string;
  question: string;
  suggestions: string[];
}

export interface ProviderWarning {
  source: string;
  message: string;
  severity: 'low' | 'medium' | 'high';
}

export interface TimelineEvent {
  id: string;
  start_time: string;
  end_time: string;
  title: string;
  location: string;
  travel_time_from_previous: string;
  cost_estimate?: string | null;
  description: string;
  image_url?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  risk_flags: string[];
}

export interface DayPlan {
  day_index: number;
  title: string;
  theme: string;
  events: TimelineEvent[];
  route_points: Array<{
    label: string;
    latitude: number;
    longitude: number;
  }>;
}

export interface TripState {
  trip_id: string;
  view_state: ViewState;
  interaction_mode: InteractionMode;
  selected_model_id: ModelId;
  model_source: 'request' | 'env' | 'mock';
  query: string;
  plan_summary: {
    headline: string;
    body: string;
    highlights: string[];
  };
  clarification_questions: ClarificationQuestion[];
  timeline_days: DayPlan[];
  budget_summary: {
    trip_total_estimate: string;
    current_day_estimate: string;
    budget_status: 'on_track' | 'watch' | 'over';
    transport_total_estimate?: string | null;
    flight_total_estimate?: string | null;
    rail_total_estimate?: string | null;
    city_transport_total_estimate?: string | null;
    car_rental_total_estimate?: string | null;
    hotel_total_estimate?: string | null;
    notes?: string[];
  };
  memory_summary: {
    fixed_anchors: string[];
    open_constraints: string[];
    user_preferences: string[];
    last_selected_model: ModelId;
    route_mode: string;
  };
  provider_warnings: ProviderWarning[];
  conflict_warnings: ProviderWarning[];
  map_preview: {
    route_label: string;
    stops: string[];
    total_transit_time: string;
    image_references: Array<{
      title: string;
      image_url?: string | null;
      source_url?: string | null;
    }>;
  };
  travel_logistics: {
    origin: string;
    destination: string;
    travelers: number;
    outbound_transport: string;
    return_transport: string;
    outbound_schedule: string;
    return_schedule: string;
    hotel_name: string;
  };
  reference_links: Array<{
    title: string;
    url: string;
    label: string;
  }>;
  created_at: string;
  updated_at: string;
}

export interface TripResponse {
  trip: TripState;
}

export interface ModelConfigRequest {
  model_id: ModelId;
  api_key: string | null;
  base_url: string | null;
}
