import { useState } from "react";
import { planTrip } from "./api/client";
import { ItineraryView } from "./components/ItineraryView";
import { TripPromptForm } from "./components/TripPromptForm";
import type { ItineraryResponse, TripRequest } from "./types/trip";

export function App() {
  const [result, setResult] = useState<ItineraryResponse | null>(null);
  const [lastBudget, setLastBudget] = useState<number>(650);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePlanTrip = async (request: TripRequest) => {
    setIsLoading(true);
    setError(null);
    setLastBudget(request.max_budget);

    try {
      const response = await planTrip(request);
      setResult(response);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to generate itinerary.",
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">
              AI Travel Agent
            </h1>
            <p className="text-xs text-slate-500">
              Milestone 3 — External Place Search, Routing, and Cache Validation
            </p>
          </div>
          <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
            React · FastAPI · Gemini
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {error && (
          <div className="mb-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            <strong>Error:</strong> {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <TripPromptForm isLoading={isLoading} onSubmit={handlePlanTrip} />
          </div>
          <div className="lg:col-span-7">
            <ItineraryView data={result} maxBudget={lastBudget} />
          </div>
        </div>
        <footer className="mt-8 text-center text-xs text-slate-500">
          Place data © OpenStreetMap contributors · Routing by OSRM
        </footer>
      </main>
    </div>
  );
}

export default App;
