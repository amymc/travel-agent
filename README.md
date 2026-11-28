# AI Travel Agent

A learning project for building an AI travel planning application with **React + TypeScript**, **Python (FastAPI + uv)**, and **Google Gemini**.

## Milestone 5: Streaming UX, Persistence, and Polish

- **Backend (`backend/`):** FastAPI app running an explicit Gemini tool-calling loop (`app/agent/loop.py`) with `search_places`, `get_travel_time`, `validate_draft_itinerary`, and `submit_itinerary`. Place search uses Nominatim geocoding and Overpass OpenStreetMap POIs; walking and driving directions use OSRM. Geospatial responses, trip threads, messages, itinerary revisions, and agent events persist in SQLite (`backend/data/api_cache.sqlite3` by default).
- **Frontend (`frontend/`):** Vite + React + TypeScript + Tailwind UI with trip prompt/constraint inputs, a day-by-day itinerary viewer, and a collapsible **Agent Tool-Calling Trace** panel.
- **Constraint engine:** Python recalculates budget totals and checks day counts, time formats, overlaps, measured travel gaps, available opening hours, and pace. Unavailable source data is shown as a warning; known violations block itinerary submission and enter the repair loop.
- **Revisions:** Use the “Revise this itinerary” field after planning. The current itinerary and trip constraints are sent to the agent, which edits the existing draft and runs the same validation/repair workflow. Examples: “Day 2 feels too rushed” or “Reduce the budget by 300”. Budget amounts use the original trip currency automatically and lower the hard budget ceiling before the agent revises.
- **Dates and opening hours:** The optional first travel date enables weekday-specific opening-hours checks. Without a date, the validator only makes a definite check for schedules that apply every day; unsupported or unavailable hours remain warnings.
- **Streaming and saved threads:** The UI uses Server-Sent Events for live status and completed tool-call events. Trip requests, chat messages, itinerary revisions, full tool results, and stream events are stored in SQLite. Use **Saved trip threads** to restore a conversation after restarting the app.
- **Cost and debugging:** Select a category in the interactive cost breakdown to filter the itinerary. Expand each trace call to inspect its arguments and full tool result. Internal model reasoning is not streamed; progress and tool activity are.

## Setup & Running Locally

### 1. Configure your free Gemini API key

Get a free API key from [Google AI Studio](https://aistudio.google.com/), then create `.env` in the repo root:

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=...
```

### 2. Run the Python backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Run backend tests (offline, mocked LLM):

```bash
cd backend
uv run pytest -v
```

### 3. Run the React frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to `http://localhost:8000`.

### External map data

The geocoding, POI, and routing endpoints are configurable with the `NOMINATIM_URL`, `OVERPASS_URL`, `OVERPASS_FALLBACK_URL`, `OSRM_DRIVING_URL`, and `OSRM_FOOT_URL` environment variables. They use public OpenStreetMap services and do not require API keys. A transient Overpass error automatically tries the fallback instance. Requests identify this app with `OSM_USER_AGENT`; keep public-service use modest. The SQLite database path is configurable with `CACHE_DB_PATH`; it stores geocodes, POI searches, routes, trip threads, messages, revision snapshots, and agent events. The stream endpoints are `POST /api/trips/stream` and `POST /api/trips/threads/{thread_id}/revise/stream`. OpenStreetMap data is © OpenStreetMap contributors and available under the ODbL; public services have usage limits and no uptime guarantee.

Gemini requests are limited to `GEMINI_REQUEST_TIMEOUT_MS` (default 120 seconds), and an agent run is limited to `AGENT_RUN_TIMEOUT_SECONDS` (default 300 seconds). The browser stops waiting after 7 minutes and displays a timeout error if the backend fails to respond.

OSM does not provide dependable admission, meal, hotel, or transit fares. Search results therefore flag pricing as unavailable; taxi and transit fares remain rough estimates. OSRM provides routed walking and driving times; transit duration is estimated from routed distance.
