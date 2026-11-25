# AI Travel Agent

A learning project for building an AI travel planning application with **React + TypeScript**, **Python (FastAPI + uv)**, and **Google Gemini**.

## Milestone 1: Walking Skeleton

- **Backend (`backend/`):** FastAPI app using `google-genai` structured outputs (`ItineraryDraft` Pydantic schema) paired with a deterministic Python validator (`app/domain/validator.py`) for budget totals, time overlaps, and pace limits.
- **Frontend (`frontend/`):** Vite + React + TypeScript + Tailwind UI with trip prompt/constraint inputs and a day-by-day itinerary viewer.

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
