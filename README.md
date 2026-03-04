# Travel Agent

Interactive travel planning application with:

- React frontend for query input, model selection, clarification, itinerary display, and per-day route maps
- FastAPI backend for trip orchestration
- model-first planning using your existing LLM API endpoint
- search-augmented itinerary generation using `SerpApi`, `Serper`, and `Amap`
- optional LangChain prompt composition layer (`langchain-core`) while keeping the existing model transport client

## Demo
### Front-end input interface
<img src="images/image.png" width="600" />

It allows users to input their travel needs and then generates travel plans through two modes: 
- Direct Mode: quickly generates a draft itinerary directly. 
- Planning Mode: first inquires with the user for more information, and then generates a more reliable travel plan.

It support different models
- GPT-5.1-chat
- Gemini-3-flash-preview
- Deepseek-v3.2

### Backend interface
#### Overview
<img src="images/image-1.png" width="600" />

#### Specific daily plans.
<img src="images/image-2.png" width="600" />

- Itineraries for each time period
- Scenery corresponding to POIs

#### Daily route map.
<img src="images/image-3.png" width="600" />

#### Budget and memory.
<img src="images/image-4.png" width="600" />

#### Supplementary search results
<img src="images/image-5.png" width="600" />

- Hotel information
- POI information

#### Other VISUALS
<img src="images/image-6.png" width="600" />

- Other POI pictures

### MOre travel blog links
<img src="images/image-7.png" width="600" />

### Static HTML Export
You can view a pre-generated interactive travel plan here: [Travel Agent Demo](./images/Travel%20Agent.html) (Download and open in browser)

## What This Project Does

The app accepts a free-form travel request such as:

- `2 People, plan a 3-day Beijing trip from Shanghai, focus on famous landmarks`

The backend then:

1. extracts structured constraints from the free-form request
2. gathers search and map context from external tools
3. generates an initial itinerary draft with the selected LLM
4. refines the draft with search-grounded context in a second LLM pass
5. enriches the result with:
   - transport timing hints
   - hotel candidates
   - POI candidates
   - image lookup for major POIs and notable food stops
   - per-day route coordinates and an interactive route panel
6. emits backend logs for each major planning stage so you can inspect:
   - request received
   - extraction complete
   - search complete
   - draft/refine status
   - final itinerary readiness

The frontend preserves the current UI style:

- long ChatGPT-style input box
- model switcher
- direct / planning mode
- planning mode supports `Tab` to cycle demo trip briefs for quick demos
- structured itinerary timeline
- side panels for budget, memory, visuals, and references

## Architecture

### Frontend

Path: `apps/web`

Main responsibilities:

- collect user query and selected model
- submit to FastAPI
- render clarification form when needed
- render timeline, logistics, references, and route map when itinerary is ready

Key components:

- [TripPlannerPage.tsx](./apps/web/src/pages/TripPlannerPage.tsx)
- [HeroComposer.tsx](./apps/web/src/components/HeroComposer.tsx)
- [Timeline.tsx](./apps/web/src/components/Timeline.tsx)
- [DayRouteMap.tsx](./apps/web/src/components/DayRouteMap.tsx)

### Backend

Path: `backend`

Main responsibilities:

- resolve model credentials from `.env`
- call the selected LLM using the existing compatible chat-completions client
- collect grounding context from tools
- generate and refine itinerary data
- persist trips in SQLite

Key modules:

- [main.py](./backend/app/main.py)
- [trips.py](./backend/app/api/routes/trips.py)
- [orchestrator.py](./backend/app/agent/orchestrator.py)
- [client.py](./backend/app/models/client.py)

## Planning Flow

The current planning flow is:

1. user enters a free-form query
2. backend parses the request heuristically
3. backend asks the selected model to extract normalized constraints
4. backend gathers tool context:
   - `Amap` for hotels, restaurants, POIs, and walking directions
   - `SerpApi` as the primary search engine
   - `Serper` as fallback search/image support
5. backend runs a draft LLM pass
6. backend runs a refinement LLM pass with search-grounded context
7. backend hydrates:
   - hotel
   - POIs
   - route timing
   - images
   - day route coordinates
8. frontend renders the final result

## Tooling

### LLM

The backend keeps the existing transport layer:

- `POST {BASE_URL}/v1/chat/completions`

Supported models:

- `gpt-5.1-chat`
- `gemini-3-flash-preview`
- `deepseek-v3.2`

### LangChain

LangChain is used as a lightweight prompt-composition layer:

- `langchain-core`
- `langchain`
- `langsmith`

Current use:

- prompt rendering via [langchain_bridge.py](./backend/app/agent/langchain_bridge.py)

This keeps the existing model client intact while making prompt wiring easier to extend into a fuller tool-calling graph later.

### Search and Travel Tools

- `SerpApi`
  - primary search for attractions, food, images, and transport snippets
- `Serper`
  - fallback search and image support
- `Amap`
  - POI lookup
  - geocoding
  - walking route geometry

## Environment Configuration

All backend secrets live in:

- `backend/.env`

Template:

- [backend/.env.example](./backend/.env.example)

### Required variables

#### Models

- `GPT_5_1_CHAT_API_KEY`
- `GPT_5_1_CHAT_BASE_URL`
- `GEMINI_3_FLASH_PREVIEW_API_KEY`
- `GEMINI_3_FLASH_PREVIEW_BASE_URL`
- `DEEPSEEK_V3_2_API_KEY`
- `DEEPSEEK_V3_2_BASE_URL`

#### Search and travel tools

- `AMAP_API_KEY`
- `AMAP_MAPS_API_KEY`
- `SERPER_API_KEY`
- `SERPAPI_API_KEY`

#### Optional

- `LANGCHAIN_API_KEY`
- `TAVILY_API_KEY`

### Frontend map configuration

To enable the real interactive Amap base map in the browser, configure:

- `apps/web/.env`

Template:

- [apps/web/.env.example](./apps/web/.env.example)

Variables:

- `VITE_API_BASE_URL`
- `VITE_AMAP_KEY` (your browser JS AMap key)
- `VITE_AMAP_SECURITY_JS_CODE` (your AMap JS security code)

Important:

- `VITE_AMAP_KEY` and `VITE_AMAP_SECURITY_JS_CODE` are different values
- if you set the same string for both, the frontend ignores the security code and logs a warning in the browser console

#### Feature flags

- `ENABLE_MOCK_MODEL_FALLBACK`
- `ENABLE_MOCK_TOOL_FALLBACK`

## Installation

### Backend

```bash
cd backend
uv sync
```

### Frontend

```bash
cd .
pnpm install
```

## Running Locally

### Start backend

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Backend default URL:

- `http://127.0.0.1:8000`

Backend logs:

- the planner now logs each major stage at `INFO`
- watch the backend terminal to inspect:
  - request parsing
  - extracted constraints
  - prompt payloads
  - model raw responses
  - tool invocations
  - geocode success/failures
  - fallback decisions

### Start frontend

```bash
cd .
pnpm dev:web
```

Frontend default URL:

- `http://localhost:5173`

## How To Test

Try these example prompts:

- `Plan a 3-day Beijing trip from Shanghai, focus on famous landmarks and skip routine meals`
- `Plan a 2-day Shenzhen trip from Shanghai`
- `We are 2 friends leaving from Shenzhen, want a food-focused Xiamen weekend, budget around 2200`

Expected behavior:

- `direct` mode returns an itinerary immediately
- `planning` mode asks for a structured brief first, then generates the itinerary

## Route Maps

Each day can include a route panel generated from Amap route geometry:

- route points are derived from event coordinates
- Amap walking directions are used when coordinate pairs are available
- the frontend renders a real Amap JS map when `VITE_AMAP_KEY` is present
- if no browser Amap key is configured, the UI falls back to the lightweight SVG route panel
- if only one marker appears, the backend likely could not geocode enough events for that day; check backend logs for search/geocode details
- if the map canvas is blank but markers appear, verify:
  - your frontend Amap key is valid for browser JS usage
  - your JS security code is correct
  - `VITE_AMAP_SECURITY_JS_CODE` is not just a copy of `VITE_AMAP_KEY`

This keeps a working fallback while still supporting a real interactive map in environments where a frontend Amap key is available.

## Performance Notes

The backend now reduces blocking latency by:

- caching SerpApi and Serper search responses
- caching image lookups
- caching Amap POI lookups
- batching geocode lookups in parallel
- batching route construction per day in parallel
- reusing Amap/search results from the `search` stage in `enrich`

If the response still feels slow, the remaining dominant cost is usually:

- external search engine latency
- image search latency
- the selected LLM response time

