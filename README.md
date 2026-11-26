# AI Travel Agent

A learning project for building an AI travel planning application with **React + TypeScript**, **Python (FastAPI + uv)**, and **Google Gemini**.

## Milestone 2: Iterative Agent Tool-Calling Loop

- **Backend (`backend/`):** FastAPI app running an explicit Gemini tool-calling loop (`app/agent/loop.py`) with `search_places`, `get_travel_time`, `validate_draft_itinerary`, and `submit_itinerary` backed by mock datasets for Lisbon, Kyoto, and Barcelona (`app/data/places.json`), plus automatic validation repair and model fallback.
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
