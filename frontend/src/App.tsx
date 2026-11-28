import { useEffect, useState } from "react";
import { getTripThread, getTripThreads, streamPlanTrip, streamReviseTrip } from "./api/client";
import { ItineraryView } from "./components/ItineraryView";
import { TripPromptForm } from "./components/TripPromptForm";
import type {
  AgentStreamEvent,
  ItineraryResponse,
  TripRequest,
  TripThreadSummary,
} from "./types/trip";

export function App() {
  const [result, setResult] = useState<ItineraryResponse | null>(null);
  const [lastBudget, setLastBudget] = useState<number>(650);
  const [tripRequest, setTripRequest] = useState<TripRequest | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [threads, setThreads] = useState<TripThreadSummary[]>([]);
  const [streamEvents, setStreamEvents] = useState<AgentStreamEvent[]>([]);

  const refreshThreads = async () => {
    try {
      setThreads(await getTripThreads());
    } catch {
      // Planning remains usable when the saved-trip list cannot be loaded.
    }
  };

  useEffect(() => {
    void refreshThreads();
  }, []);

  const receiveAgentEvent = (event: AgentStreamEvent) => {
    setStreamEvents((current) => [...current, event].slice(-80));
  };

  const handlePlanTrip = async (request: TripRequest) => {
    setIsLoading(true);
    setError(null);
    setStreamEvents([]);
    setLastBudget(request.max_budget);
    setTripRequest(request);

    try {
      const response = await streamPlanTrip(request, receiveAgentEvent);
      setResult(response);
      await refreshThreads();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate itinerary.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleReviseTrip = async (instruction: string) => {
    if (!result?.thread_id || !tripRequest) return;
    setIsLoading(true);
    setError(null);
    setStreamEvents([]);
    try {
      const response = await streamReviseTrip(result.thread_id, instruction, receiveAgentEvent);
      const revisedBudget = response.total_estimated_cost + response.budget_remaining;
      setResult(response);
      setLastBudget(revisedBudget);
      setTripRequest({ ...tripRequest, max_budget: revisedBudget });
      await refreshThreads();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revise itinerary.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenThread = async (threadId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const thread = await getTripThread(threadId);
      const latest = thread.snapshots[thread.snapshots.length - 1];
      if (!latest) throw new Error("This saved thread has no completed itinerary.");
      setResult(latest.response);
      setTripRequest(latest.request);
      setLastBudget(latest.response.total_estimated_cost + latest.response.budget_remaining);
      setStreamEvents(thread.events.map((event) => event.payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open saved trip.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">AI Travel Agent</h1>
            <p className="text-xs text-slate-500">Milestone 5 — Streaming, Saved Trips & Polish</p>
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
            {threads.length > 0 && (
              <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="mb-3 text-sm font-semibold text-slate-900">Saved trip threads</h2>
                <div className="max-h-52 space-y-1.5 overflow-y-auto">
                  {threads.map((thread) => (
                    <button
                      key={thread.thread_id}
                      type="button"
                      disabled={isLoading}
                      onClick={() => void handleOpenThread(thread.thread_id)}
                      className={`block w-full rounded-lg px-3 py-2 text-left hover:bg-indigo-50 disabled:opacity-50 ${
                        result?.thread_id === thread.thread_id ? "bg-indigo-50" : "bg-slate-50"
                      }`}
                    >
                      <span className="block truncate text-xs font-medium text-slate-800">
                        {thread.itinerary_title || thread.title}
                      </span>
                      <span className="text-[11px] text-slate-500">
                        {thread.revision_number ?? 0} saved{" "}
                        {thread.revision_number === 1 ? "version" : "versions"}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            <TripPromptForm isLoading={isLoading} onSubmit={handlePlanTrip} />
          </div>
          <div className="lg:col-span-7">
            {isLoading && streamEvents.length > 0 && (
              <section className="mb-5 rounded-2xl border border-indigo-200 bg-white p-4 shadow-sm">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
                  <h2 className="text-sm font-semibold text-slate-900">Agent activity</h2>
                </div>
                <div className="mt-3 space-y-2">
                  {streamEvents.slice(-5).map((event, index) => {
                    const message =
                      typeof event.message === "string"
                        ? event.message
                        : event.type === "tool_call_started"
                          ? `Calling ${String(event.name)}()`
                          : event.type === "tool_call_completed"
                            ? String(event.result_summary ?? `${String(event.name)} completed`)
                            : event.type === "started"
                              ? "Trip thread saved; planning started"
                              : event.type.replaceAll("_", " ");
                    return (
                      <p
                        key={`${String(event.type)}-${index}`}
                        className="truncate text-xs text-slate-600"
                      >
                        {message}
                      </p>
                    );
                  })}
                </div>
              </section>
            )}
            <ItineraryView
              data={result}
              maxBudget={lastBudget}
              isLoading={isLoading}
              onRevise={handleReviseTrip}
            />
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
