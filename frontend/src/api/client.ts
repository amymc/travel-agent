import type { ItineraryDraft, ItineraryResponse, TripRequest } from "../types/trip";

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
