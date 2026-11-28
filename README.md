# AI Travel Agent

A learning project for building an AI travel planning application with **React + TypeScript**, **Python (FastAPI + uv)**, and **Google Gemini**.

## Milestone 3: External Place Search, Routing, and Cache

- **Backend (`backend/`):** FastAPI app running an explicit Gemini tool-calling loop (`app/agent/loop.py`) with `search_places`, `get_travel_time`, `validate_draft_itinerary`, and `submit_itinerary`. Place search uses Nominatim geocoding and Overpass OpenStreetMap POIs; walking and driving directions use OSRM. Geocodes, POI searches, and routes are persisted in a local SQLite cache (`backend/data/api_cache.sqlite3`).
- **Frontend (`frontend/`):** Vite + React + TypeScript + Tailwind UI with trip prompt/constraint inputs, a day-by-day itinerary viewer, and a collapsible **Agent Tool-Calling Trace** panel.

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

The geocoding, POI, and routing endpoints are configurable with the `NOMINATIM_URL`, `OVERPASS_URL`, `OVERPASS_FALLBACK_URL`, `OSRM_DRIVING_URL`, and `OSRM_FOOT_URL` environment variables. They use public OpenStreetMap services and do not require API keys. A transient Overpass error automatically tries the fallback instance. Requests identify this app with `OSM_USER_AGENT`; keep public-service use modest. The SQLite cache path is configurable with `CACHE_DB_PATH`. Cached results persist across backend restarts. OpenStreetMap data is © OpenStreetMap contributors and available under the ODbL; public services have usage limits and no uptime guarantee.

Gemini requests are limited to `GEMINI_REQUEST_TIMEOUT_MS` (default 120 seconds), and an agent run is limited to `AGENT_RUN_TIMEOUT_SECONDS` (default 300 seconds). The browser stops waiting after 7 minutes and displays a timeout error if the backend fails to respond.

OSM does not provide dependable admission, meal, hotel, or transit fares. Search results therefore flag pricing as unavailable; taxi and transit fares remain rough estimates. OSRM provides routed walking and driving times; transit duration is estimated from routed distance.
