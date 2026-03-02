import type { ModelConfigRequest, ModelsResponse, TripResponse } from './models';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      throw new Error(parsed.detail || 'Request failed');
    } catch {
      throw new Error(text || 'Request failed');
    }
  }

  return (await response.json()) as T;
}

export function fetchModels(): Promise<ModelsResponse> {
  return request<ModelsResponse>('/api/models');
}

export function createTrip(query: string, modelConfig: ModelConfigRequest): Promise<TripResponse> {
  return request<TripResponse>('/api/trips', {
    method: 'POST',
    body: JSON.stringify({ query, model_config: modelConfig }),
  });
}

export function postTripMessage(
  tripId: string,
  message: string,
  modelConfig: ModelConfigRequest,
): Promise<TripResponse> {
  return request<TripResponse>(`/api/trips/${tripId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message, model_config: modelConfig }),
  });
}
