import type {
  AgentStreamEvent,
  ItineraryDraft,
  ItineraryResponse,
  TripRequest,
  TripThreadDetail,
  TripThreadSummary,
} from "../types/trip";

async function postTrip(path: string, payload: unknown): Promise<ItineraryResponse> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 420_000);

  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = `Request failed with status ${response.status}`;
      try {
        const payload = (await response.json()) as { detail?: string };
        if (payload.detail) {
          detail = payload.detail;
        }
      } catch {
        // Fall back to default error message when response body is not JSON.
      }
      throw new Error(detail);
    }

    return (await response.json()) as ItineraryResponse;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Planning timed out after 7 minutes. Please try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function planTrip(request: TripRequest): Promise<ItineraryResponse> {
  return postTrip("/api/trips/plan", request);
}

export function reviseTrip(
  trip_request: TripRequest,
  itinerary: ItineraryDraft,
  instruction: string,
): Promise<ItineraryResponse> {
  return postTrip("/api/trips/revise", { trip_request, itinerary, instruction });
}

async function streamTrip(
  path: string,
  payload: unknown,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<ItineraryResponse> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 420_000);

  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = `Request failed with status ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: string };
        if (body.detail) detail = body.detail;
      } catch {
        // Keep the status-based message when the server did not return JSON.
      }
      throw new Error(detail);
    }
    if (!response.body) throw new Error("The server did not open a streaming response.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as AgentStreamEvent;
        onEvent(event);
        if (event.type === "error") {
          throw new Error(typeof event.message === "string" ? event.message : "Trip planning failed.");
        }
        if (event.type === "complete" && event.response) {
          return event.response as ItineraryResponse;
        }
      }
      if (done) break;
    }
    throw new Error("The stream ended before the itinerary was complete.");
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Planning timed out after 7 minutes. Please try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function streamPlanTrip(
  request: TripRequest,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<ItineraryResponse> {
  return streamTrip("/api/trips/stream", request, onEvent);
}

export function streamReviseTrip(
  threadId: string,
  instruction: string,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<ItineraryResponse> {
  return streamTrip(
    `/api/trips/threads/${encodeURIComponent(threadId)}/revise/stream`,
    { instruction },
    onEvent,
  );
}

export async function getTripThreads(): Promise<TripThreadSummary[]> {
  const response = await fetch("/api/trips/threads");
  if (!response.ok) throw new Error("Could not load saved trips.");
  return (await response.json()) as TripThreadSummary[];
}

export async function getTripThread(threadId: string): Promise<TripThreadDetail> {
  const response = await fetch(`/api/trips/threads/${encodeURIComponent(threadId)}`);
  if (!response.ok) throw new Error("Could not load that saved trip.");
  return (await response.json()) as TripThreadDetail;
}
